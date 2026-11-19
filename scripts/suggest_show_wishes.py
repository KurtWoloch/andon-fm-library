import os, sys, io, re, json, math
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from google import genai as genai_client
import concurrent.futures

def call_gemini_with_retry(client, model_name, prompt, timeout_sec=45, max_retries=3):
    """Calls Gemini with a hard wall-clock timeout and automatic retry so scripts never hang."""
    for attempt in range(1, max_retries + 1):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(client.models.generate_content, model=model_name, contents=prompt)
        try:
            resp = future.result(timeout=timeout_sec)
            executor.shutdown(wait=False)
            return resp
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            print(f"  [Warnung] Gemini-Antwort dauert länger als {timeout_sec}s (Versuch {attempt}/{max_retries}) – sende Anfrage neu...", flush=True)
            if attempt == max_retries:
                raise RuntimeError(f"Gemini antwortete nach {max_retries} Versuchen à {timeout_sec}s nicht.")
        except Exception as e:
            executor.shutdown(wait=False)
            print(f"  [Warnung] Gemini-Fehler bei Versuch {attempt}/{max_retries}: {e}", flush=True)
            if attempt == max_retries:
                raise

import bb_fit_db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BB_JSON = r'C:\Users\kurt_\.openclaw\workspace\andon-fm-library\bb_only.json'
SHOWS_LOG = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.shows.txt'
MUSIC_LOG = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt'

MESZ = timezone(timedelta(hours=2))

def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

def load_archive():
    with open(BB_JSON, 'r', encoding='utf-8') as f:
        bb_lib = json.load(f)
    return bb_lib

def lookup_show_by_slot_or_name(query_str):
    """
    If query_str is a time like '17:00' (or '17') or a known show name without description,
    resolves (show_name, show_desc, slot_hm) from the latest schedule history and database.
    """
    q = query_str.strip()
    m_time = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?', q)
    if m_time:
        hh = int(m_time.group(1)) % 24
        slot_hm = f"{hh:02d}:00"
        # 1. Check the most recent show on this local hour in andon-fm-schedule-history.csv
        latest_name_on_slot = None
        latest_desc_on_slot = ""
        sch_csv = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\andon-fm-schedule-history.csv'
        if os.path.exists(sch_csv):
            try:
                import csv as _csv
                with open(sch_csv, 'r', encoding='utf-8', errors='replace') as f:
                    for r in _csv.reader(f):
                        if len(r) >= 6 and r[1] == 'Backlink Broadcast':
                            try:
                                dt_utc = datetime.fromisoformat(r[3].replace('Z', '+00:00')).replace(tzinfo=None)
                                dt_loc = bb_fit_db.utc_to_vienna(dt_utc)
                                if dt_loc.strftime('%H:00') == slot_hm:
                                    latest_name_on_slot = r[2].strip()
                                    latest_desc_on_slot = r[5].strip()
                            except Exception:
                                pass
            except Exception:
                pass
        if latest_name_on_slot:
            # Check if DB has an even richer description for this show
            try:
                conn = bb_fit_db.get_conn()
                cur = conn.cursor()
                cur.execute("SELECT show_desc FROM shows WHERE show_id = ?", (bb_fit_db.canonical_show_id(latest_name_on_slot),))
                row = cur.fetchone()
                conn.close()
                if row and row['show_desc'] and len(row['show_desc']) > len(latest_desc_on_slot):
                    latest_desc_on_slot = row['show_desc']
            except Exception:
                pass
            return latest_name_on_slot, latest_desc_on_slot, slot_hm

        # Fallback: check shows table by slot_hm
        try:
            conn = bb_fit_db.get_conn()
            bb_fit_db.sync_shows_and_tracks(conn)
            cur = conn.cursor()
            cur.execute("SELECT show_name, show_desc, slot_hm FROM shows WHERE slot_hm = ? ORDER BY updated_at DESC LIMIT 1", (slot_hm,))
            row = cur.fetchone()
            conn.close()
            if row and row['show_name']:
                return row['show_name'], row['show_desc'] or '', slot_hm
        except Exception:
            pass
    else:
        try:
            conn = bb_fit_db.get_conn()
            bb_fit_db.sync_shows_and_tracks(conn)
            cur = conn.cursor()
            cur.execute("""
                SELECT show_name, show_desc, slot_hm
                FROM shows
                WHERE show_id = ? OR lower(show_name) LIKE ?
                ORDER BY updated_at DESC LIMIT 1
            """, (norm(q), f"%{q.lower()}%"))
            row = cur.fetchone()
            conn.close()
            if row and row['show_name']:
                return row['show_name'], row['show_desc'] or '', row['slot_hm'] or ''
        except Exception:
            pass
    return q, "", ""

def get_current_live_show():
    if os.path.exists(SHOWS_LOG):
        with open(SHOWS_LOG, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f if '| Backlink Broadcast |' in l and '| SHOW:' in l]
            if lines:
                last_l = lines[-1]
                parts = last_l.split('|')
                if len(parts) >= 6:
                    show_name = parts[2].replace('SHOW:', '').strip()
                    desc = parts[5].replace('Desc:', '').strip()
                    return show_name, desc
    return "AKTUELLE SENDUNG", "Beste Musik auf Backlink Broadcast"

def get_recent_played_tracks(n=None, since_time=None):
    if not os.path.exists(MUSIC_LOG):
        return [], "Kein Musik-Log vorhanden"
    
    pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Backlink Broadcast \| MUSIC: (.+?) \| Start:')
    now_dt = datetime.now(MESZ)
    today_str = now_dt.strftime('%Y-%m-%d')
    
    tracks = []
    with open(MUSIC_LOG, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if 'Backlink Broadcast' in line:
                m = pattern.match(line.strip())
                if m:
                    ts_str, track = m.group(1), m.group(2).strip()
                    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    tracks.append((dt, ts_str, track))
                    
    if not tracks:
        return [], "Keine Tracks gefunden"
        
    if since_time:
        parts = since_time.strip().split(':')
        if len(parts) >= 2:
            h, m = int(parts[0]), int(parts[1])
            s = int(parts[2]) if len(parts) >= 3 else 0
            cutoff_dt = datetime.strptime(f"{today_str} {h:02d}:{m:02d}:{s:02d}", '%Y-%m-%d %H:%M:%S')
            matched = [t for t in tracks if t[0] >= cutoff_dt]
            return matched, f"Alle Titel seit {h:02d}:{m:02d} Uhr"
            
    if n is not None:
        count = min(len(tracks), max(1, n))
        return tracks[-count:], f"Letzte {count} Titel"
        
    # Smart auto mode:
    # Check last 10 tracks, find last pause >= 8 min
    last10 = tracks[-10:] if len(tracks) >= 10 else tracks
    pause_idx = -1
    for i in range(len(last10) - 1, 0, -1):
        delta = (last10[i][0] - last10[i-1][0]).total_seconds()
        if delta >= 480: # >= 8 minutes
            pause_idx = i
            break
            
    if pause_idx != -1 and (len(last10) - pause_idx) >= 2:
        res = last10[pause_idx:]
        return res, f"Auto: {len(res)} Titel seit letzter Pause (>8 min)"
    else:
        count = min(len(tracks), 5)
        return tracks[-count:], f"Auto: Letzte {count} Titel"

def parse_days_unplayed(item, now_dt):
    lp_v = item.get('last_played_vienna', '')
    lp_r = item.get('last_played', '')
    date_str = lp_v[:10] if lp_v else (lp_r[:10] if lp_r else '')
    
    if not date_str:
        # Never played -> very high days
        return 130.0, "Nie (0 Plays!)"
    
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d').date()
        days = (now_dt.date() - d).days
        return max(1.0, float(days)), date_str
    except:
        return 1.0, date_str

def main():
    now_dt = datetime.now(MESZ)
    now_str = now_dt.strftime('%H:%M')
    
    # Parse CLI arguments
    args = sys.argv[1:]
    recent_mode = False
    recent_n = None
    since_time = None
    positional = []
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--recent':
            recent_mode = True
            if i + 1 < len(args) and args[i+1].isdigit():
                recent_n = int(args[i+1])
                i += 1
        elif arg.startswith('--recent='):
            recent_mode = True
            val = arg.split('=', 1)[1]
            if val.isdigit():
                recent_n = int(val)
        elif arg == '--since':
            recent_mode = True
            if i + 1 < len(args):
                since_time = args[i+1].strip()
                i += 1
        elif arg.startswith('--since='):
            recent_mode = True
            since_time = arg.split('=', 1)[1].strip()
        elif arg == '--slot':
            if i + 1 < len(args):
                positional.insert(0, args[i+1].strip())
                i += 1
        elif arg.startswith('--slot='):
            positional.insert(0, arg.split('=', 1)[1].strip())
        elif arg in ('-h', '--help'):
            print("Verwendung: py suggest_show_wishes.py [OPTIONS] [SHOW_NAME] [SHOW_DESC]")
            print("Optionen:")
            print("  --recent [N]     Orientiere Wunschtitel an den letzten N gespielten Titeln (Default: Auto-Erkennung)")
            print("  --since HH:MM    Orientiere Wunschtitel an allen Titeln, die seit HH:MM Uhr gelaufen sind")
            print("  -h, --help       Diese Hilfe anzeigen")
            sys.exit(0)
        else:
            positional.append(arg)
        i += 1
        
    if len(positional) >= 2:
        show_name = positional[0].strip()
        show_desc = positional[1].strip()
    elif len(positional) == 1:
        resolved_name, resolved_desc, resolved_slot = lookup_show_by_slot_or_name(positional[0])
        show_name = resolved_name
        show_desc = resolved_desc
        if resolved_slot:
            now_str = resolved_slot
    else:
        show_name, show_desc = get_current_live_show()
        
    recent_tracks = []
    recent_label = ""
    if recent_mode:
        recent_tracks, recent_label = get_recent_played_tracks(n=recent_n, since_time=since_time)
        
    print("="*85)
    print("ANDON FM — INTELLIGENTER WUNSCHTITEL-GENERATOR (GEMINI 4 ARGON)")
    print("="*85)
    print(f"📻 Sendung       : {show_name}")
    if show_desc:
        print(f"📄 Beschreibung   : {show_desc}")
    print(f"⏰ Uhrzeit        : {now_str} Uhr MESZ")
    if recent_mode:
        print(f"🎶 Vibe-Referenz  : {recent_label} ({len(recent_tracks)} Titel)")
        for dt, ts_s, tr in recent_tracks:
            print(f"     [{ts_s[11:16]}] {tr}")
    print("="*85)

    # 1. Initialize Gemini Client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("FEHLER: GEMINI_API_KEY nicht gesetzt!", file=sys.stderr)
        sys.exit(1)
        
    client = genai_client.Client(api_key=api_key)
    model_name = "gemini-4-argon"
    
    # 2. LLM Call 1: Playlist erzeugen
    print("\n[Schritt 1/4] Frage Gemini 4 Argon nach einer idealen Playlist...")
    
    if recent_mode and recent_tracks:
        recent_list_str = "\n".join(f"- {tr}" for dt, ts_s, tr in recent_tracks)
        prompt1 = f"""Du bist Musikchef eines abwechslungsreichen Radiosenders (Backlink Broadcast).
Im Sendeplan steht aktuell die Sendung: "{show_name}" ({show_desc}).

Die zuletzt im Sender gelaufenen Titel (der tatsächliche musikalische Vibe / Klangteppich) sind:
{recent_list_str}

Erkenne den aktuellen musikalischen Stil, das Genre, die Stimmung und Energie dieser vorangegangenen Titel.
Erstelle eine Playlist von genau 25 passenden, starken Anschlusstiteln für {now_str} Uhr, die diesen Vibe harmonisch, stimmig und abwechslungsreich fortführen.

Wichtig: Gib ausschließlich eine nummerierte Liste im Format "Interpret - Titel" aus, genau ein Lied pro Zeile, ohne Begrüßung oder Schlusstext.
Beispiel:
1. Queen - Bohemian Rhapsody
2. Oasis - Wonderwall"""
    else:
        prompt1 = f"""Du bist Musikchef eines abwechslungsreichen Radiosenders.
Erstelle eine Playlist von genau 25 passenden, starken Titeln für die folgende Radiosendung, die um {now_str} Uhr gesendet wird:
Sendung: "{show_name}"
Beschreibung: "{show_desc}"

Wichtig: Gib ausschließlich eine nummerierte Liste im Format "Interpret - Titel" aus, genau ein Lied pro Zeile, ohne Begrüßung oder Schlusstext.
Beispiel:
1. Queen - Bohemian Rhapsody
2. Oasis - Wonderwall"""

    resp1 = call_gemini_with_retry(client, model_name, prompt1)
    
    playlist_text = resp1.text.strip()
    
    # Parse playlist lines
    playlist_items = []
    for line in playlist_text.splitlines():
        line = re.sub(r'^\d+[\.\)\-]\s*', '', line.strip()) # remove numbering
        if '-' in line:
            parts = line.split('-', 1)
            art = parts[0].strip()
            tit = parts[1].strip()
            playlist_items.append((art, tit, f"{art} - {tit}"))

    print(f"  -> Gemini hat {len(playlist_items)} Titel vorgeschlagen.")

    # 3. Load archive and match
    print("[Schritt 2/4] Gleiche Playlist mit Archivliste (bb_only.json) ab...")
    bb_lib = load_archive()
    
    # Pre-index archive by normalized strings
    archive_by_norm = {}
    archive_by_artist = defaultdict(list)
    for item in bb_lib:
        art = item.get('artist', '')
        tit = item.get('title', '')
        full = f"{art} - {tit}"
        n_full = norm(full)
        archive_by_norm[n_full] = item
        archive_by_artist[norm(art)].append(item)

    archiv_vorhanden = [] # (item, original_suggested_str)
    wunschliste = []      # (art, tit, full_str)
    
    suggested_artists_norm = set()
    
    for art, tit, full in playlist_items:
        n_art = norm(art)
        n_tit = norm(tit)
        n_full = norm(full)
        suggested_artists_norm.add(n_art)
        
        # Check if in archive
        match = None
        if n_full in archive_by_norm:
            match = archive_by_norm[n_full]
        else:
            # check artist + title fuzzy
            if n_art in archive_by_artist:
                for a_item in archive_by_artist[n_art]:
                    if n_tit in norm(a_item.get('title', '')) or norm(a_item.get('title', '')) in n_tit:
                        match = a_item
                        break
        
        if match:
            archiv_vorhanden.append((match, full))
        else:
            wunschliste.append((art, tit, full))

    print(f"  -> Direkt im Archiv vorhanden: {len(archiv_vorhanden)} Titel (automatisch Score 10)")
    print(f"  -> Nicht im Archiv (Wunschliste für Zukäufe): {len(wunschliste)} Titel")

    # 4. Find other tracks by these artists in archive
    kandidaten_pool = {} # norm_full -> item
    for n_art in suggested_artists_norm:
        if n_art in archive_by_artist:
            for a_item in archive_by_artist[n_art]:
                n_f = norm(f"{a_item.get('artist', '')} - {a_item.get('title', '')}")
                # Exclude if already in archiv_vorhanden
                if not any(norm(f"{m.get('artist')} - {m.get('title')}") == n_f for m, _ in archiv_vorhanden):
                    kandidaten_pool[n_f] = a_item

    # 5. Enrich with 20 longest unplayed tracks from archive (LRP)
    # Sort unplayed by days unplayed desc
    unplayed_all = []
    for item in bb_lib:
        days, date_str = parse_days_unplayed(item, now_dt)
        unplayed_all.append((days, item))
    unplayed_all.sort(key=lambda x: x[0], reverse=True)
    
    added_lrp = 0
    for days, item in unplayed_all:
        n_f = norm(f"{item.get('artist', '')} - {item.get('title', '')}")
        if n_f not in kandidaten_pool and not any(norm(f"{m.get('artist')} - {m.get('title')}") == n_f for m, _ in archiv_vorhanden):
            kandidaten_pool[n_f] = item
            added_lrp += 1
            if added_lrp >= 20:
                break

    kandidaten_liste = list(kandidaten_pool.values())
    print(f"  -> Kandidatenliste zusammengestellt: {len(kandidaten_liste)} Titel (Interpreten-Matches + 20 LRP-Schätze)")

    # 6. LLM Call 2: Bewertung der Kandidatenliste
    print("[Schritt 3/4] Lasse Gemini 4 Argon die Kandidatenliste bewerten (Scores 1-10)...")
    kandidaten_prompt_lines = [f"- {item.get('artist')} - {item.get('title')}" for item in kandidaten_liste[:45]] # limit to 45
    
    if recent_mode and recent_tracks:
        recent_list_str = "\n".join(f"- {tr}" for dt, ts_s, tr in recent_tracks)
        prompt2 = f"""Bewerte die folgenden Musiktitel daraufhin, wie gut sie als Anschlusstitel zu dem aktuellen musikalischen Vibe passen:
Sendung im Sendeplan: "{show_name}" ({show_desc})
Zuletzt gespielte Titel (aktueller Vibe):
{recent_list_str}
Sendezeit: {now_str} Uhr MESZ

Vergib für JEDEN Titel eine ganzzahlige Bewertung von 1 bis 10 (10 = absolute Traum-Besetzung für diesen Vibe, 1 = völlig unpassend).
Wichtig: Antworte ausschließlich mit einer Liste im Format:
[Note] Interpret - Titel
Beispiel:
[10] The Rolling Stones - Paint It, Black
[4] ABBA - Waterloo

Hier sind die Titel zur Bewertung:
""" + "\n".join(kandidaten_prompt_lines)
    else:
        prompt2 = f"""Bewerte die folgenden Musiktitel daraufhin, wie gut sie zu dieser Radiosendung passen:
Sendung: "{show_name}"
Beschreibung: "{show_desc}"
Sendezeit: {now_str} Uhr MESZ

Vergib für JEDEN Titel eine ganzzahlige Bewertung von 1 bis 10 (10 = absolute Traum-Besetzung für diese Show, 1 = völlig unpassend).
Wichtig: Antworte ausschließlich mit einer Liste im Format:
[Note] Interpret - Titel
Beispiel:
[10] The Rolling Stones - Paint It, Black
[4] ABBA - Waterloo

Hier sind die Titel zur Bewertung:
""" + "\n".join(kandidaten_prompt_lines)

    resp2 = call_gemini_with_retry(client, model_name, prompt2)
    
    # Parse scores from resp2
    scores = {} # norm_full -> score (1..10)
    for line in resp2.text.strip().splitlines():
        m = re.search(r'\[\s*(\d+)\s*\]\s*(.+)', line)
        if m:
            sc = int(m.group(1))
            t_str = m.group(2).strip()
            scores[norm(t_str)] = min(10, max(1, sc))

    # 7. Merge and calculate Kurt's formula: Gesamtwertung = Score * Tage_ungespielt
    print("[Schritt 4/4] Berechne Gesamtwertung (Score * Tage ungespielt) und sortiere...")
    gesamtliste = []
    
    # Add Archiv-Vorhanden-Liste with Score 10
    for item, orig_str in archiv_vorhanden:
        days, date_str = parse_days_unplayed(item, now_dt)
        score = 10
        total_val = score * days
        gesamtliste.append({
            'artist': item.get('artist'),
            'title': item.get('title'),
            'score': score,
            'days': days,
            'date_str': date_str,
            'total_val': total_val,
            'source': 'Direkter Playlist-Treffer'
        })
        
    # Add evaluated candidates
    for item in kandidaten_liste:
        n_f = norm(f"{item.get('artist')} - {item.get('title')}")
        # find score
        sc = 5 # default fallback
        if n_f in scores:
            sc = scores[n_f]
        else:
            for k, val in scores.items():
                if n_f in k or k in n_f:
                    sc = val
                    break
                    
        days, date_str = parse_days_unplayed(item, now_dt)
        total_val = sc * days
        gesamtliste.append({
            'artist': item.get('artist'),
            'title': item.get('title'),
            'score': sc,
            'days': days,
            'date_str': date_str,
            'total_val': total_val,
            'source': 'Kandidat bewertet'
        })

    # Save evaluated tracks into the 3-table Fit database ONLY if:
    # 1. NOT in recent_mode (--recent / --since evaluates current track vibe, not the show concept!)
    # 2. The show_name matches an actual known show in the schedule database!
    try:
        if recent_mode:
            print("  -> [Info] Vibe-Modus (--recent/--since) aktiv: Bewertungen werden NICHT in der Sendungs-Datenbank gespeichert.")
        elif not bb_fit_db.is_known_schedule_show(show_name):
            print(f"  -> [Info] '{show_name}' ist keine reguläre Sendung im Sendeplan: Bewertungen werden NICHT in der Datenbank gespeichert.")
        else:
            db_evals = []
            for x in gesamtliste:
                db_evals.append({
                    'full_name': f"{x['artist']} - {x['title']}",
                    'score': int(x['score']),
                    'reason': x['source']
                })
            saved_db = bb_fit_db.record_fit_scores(show_name, show_desc, "", db_evals, source_label="suggest_show_wishes")
            print(f"  -> {saved_db} Titel-Bewertungen (inkl. verworfener Kandidaten) für '{show_name}' in Fit-Datenbank gespeichert.")
    except Exception as e:
        print(f"  -> [Hinweis] Datenbank-Speicherung übersprungen: {e}")

    # Prepare ranked list of directly matched playlist tracks (Score 10)
    archiv_vorhanden_ranked = [x for x in gesamtliste if x['source'] == 'Direkter Playlist-Treffer']
    archiv_vorhanden_ranked.sort(key=lambda x: (-x['total_val'], -x['days']))

    # Build Top 15 recommendations:
    # 1. Primary: candidates with score >= 4, sorted by total_val (score * days) desc
    passende = [x for x in gesamtliste if x['score'] >= 4]
    passende.sort(key=lambda x: (-x['total_val'], -x['score'], -x['days']))

    # 2. Backfill: candidates with score < 4, sorted by score desc, then unplayed days desc
    nachruecker = [x for x in gesamtliste if x['score'] < 4]
    nachruecker.sort(key=lambda x: (-x['score'], -x['days'], -x['total_val']))

    empfohlene_liste = passende[:15]
    if len(empfohlene_liste) < 15:
        fehlen = 15 - len(empfohlene_liste)
        empfohlene_liste.extend(nachruecker[:fehlen])

    print("\n" + "="*95)
    print(f"DIREKT IM ARCHIV VORHANDENE PLAYLIST-TITEL ({len(archiv_vorhanden_ranked)} TITEL | AUTOMATISCH SCORE 10)")
    print("="*95)
    if archiv_vorhanden_ranked:
        print(f"{'Rang':4s} | {'Gesamtwertung':13s} | {'Score':5s} | {'Ungespielt':10s} | {'Zuletzt gespielt':16s} | Interpret & Titel")
        print("-" * 95)
        for idx, item in enumerate(archiv_vorhanden_ranked, 1):
            print(f"#{idx:2d}  | {item['total_val']:10.0f} Pkt | [{item['score']:2d}]  | {item['days']:4.0f} Tage  | {item['date_str']:16s} | {item['artist']} - {item['title']}")
    else:
        print("  Keine direkten Treffer aus der vorgeschlagenen Playlist im Archiv vorhanden.")

    print("\n" + "="*95)
    print(f"TOP 15 EMPFOHLENE WUNSCHTITEL (SCORE ≥ 4 BEVORZUGT; SCORE × TAGE UNGESPIELT)")
    print("="*95)
    print(f"{'Rang':4s} | {'Gesamtwertung':13s} | {'Score':5s} | {'Ungespielt':10s} | {'Zuletzt gespielt':16s} | Interpret & Titel")
    print("-" * 95)

    for idx, item in enumerate(empfohlene_liste, 1):
        hinweis = " (Nachrücker)" if item['score'] < 4 else ""
        print(f"#{idx:2d}  | {item['total_val']:10.0f} Pkt | [{item['score']:2d}]  | {item['days']:4.0f} Tage  | {item['date_str']:16s} | {item['artist']} - {item['title']}{hinweis}")

    # Print top tweet from recommended list
    if empfohlene_liste:
        top1 = empfohlene_liste[0]
        tweet = f'Könntest Du bitte "{top1["title"]}" von {top1["artist"]} spielen? Du kannst es mit dem Tool search_saved_files mit Metadaten-Filter auf type Music finden, falls Du es noch nicht im Katalog hast... und dann vergiß nicht, es dort einzutragen!'
        print("\n" + "="*80)
        print("FERTIGER WUNSCH-TWEET FÜR PLATZ 1:")
        print("="*80)
        print(tweet)
        print(f"(Länge: {len(tweet)} Zeichen)")
        print("="*80)

    # Print wishlist (titles from playlist not in library)
    print("\n" + "="*80)
    print(f"WUNSCHLISTE: VORGESCHLAGEN, ABER NOCH NICHT IM ARCHIV ({len(wunschliste)} TITEL)")
    print("="*80)
    if wunschliste:
        for i, (art, tit, full) in enumerate(wunschliste, 1):
            print(f"{i:2d}. {full}")
    else:
        print("  Alle 25 vorgeschlagenen Titel sind bereits im Archiv vorhanden!")
    print("=" * 80)

if __name__ == '__main__':
    main()
