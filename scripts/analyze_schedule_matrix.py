import os, sys, io, re, csv, json, time
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from google import genai as genai_client

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BB_JSON = r'C:\\Users\\kurt_\\.openclaw\\workspace\\andon-fm-library\\bb_only.json'
SCH_CSV = r'C:\\Users\\kurt_\\Betrieb\\Radio Fernsehen\\andon-fm-schedule-history.csv'
LIS_CSV = r'C:\\Users\\kurt_\\Betrieb\\Radio Fernsehen\\andon-fm-listeners.csv'
MUSIC_LOG = r'C:\\Users\\kurt_\\Betrieb\\Radio Fernsehen\\Andon FM Station logs.txt.music.txt'

OUT_CSV = r'C:\\Users\\kurt_\\Betrieb\\Radio Fernsehen\\Backlink_Broadcast_Programmanalyse.csv'
OUT_MD  = r'C:\\Users\\kurt_\\Betrieb\\Radio Fernsehen\\Backlink_Broadcast_Programmanalyse.md'

MESZ = timezone(timedelta(hours=2))

def utc_to_vienna(dt_utc_naive):
    """Converts naive UTC datetime to naive Europe/Vienna local time (MESZ=UTC+2 before 2026-10-25 01:00 UTC, MEZ=UTC+1 from 2026-10-25 01:00 UTC)."""
    if dt_utc_naive < datetime(2026, 10, 25, 1, 0, 0):
        return dt_utc_naive + timedelta(hours=2)
    else:
        return dt_utc_naive + timedelta(hours=1)

def show_start_key_from_utc(dt_utc_naive):
    """Returns unique 'YYYY-MM-DD HH:MM' key in Vienna time; disambiguates the double 02:00 hour on 2026-10-25."""
    dt_loc = utc_to_vienna(dt_utc_naive)
    if dt_utc_naive == datetime(2026, 10, 25, 1, 0, 0):
        return "2026-10-25 02:01"
    return dt_loc.strftime('%Y-%m-%d %H:%M')

MODEL_NAME = "gemini-4-argon"

def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

def load_archive():
    with open(BB_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_music_and_stack():
    """
    Parses the entire music log for Backlink Broadcast, computing:
    - LRU stack position for every play
    - Hours since previous play of the same track
    - A lookup of all plays up to any timestamp
    """
    pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Backlink Broadcast \| MUSIC: (.+?) \| Start:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    all_plays = []
    if not os.path.exists(MUSIC_LOG):
        return []
    with open(MUSIC_LOG, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if 'Backlink Broadcast' in line:
                m = pattern.match(line.strip())
                if m:
                    dt_utc = datetime.strptime(m.group(3), '%Y-%m-%d %H:%M:%S') + timedelta(seconds=40)
                    tr = m.group(2).strip()
                    all_plays.append((dt_utc, tr, norm(tr)))

    lru_stack = []
    last_play_dt = {}
    play_metrics = [] # (dt, tr, norm_tr, stack_pos, hours_since_last)

    for dt, tr, n_tr in all_plays:
        if n_tr in lru_stack:
            pos = lru_stack.index(n_tr) + 1
            lru_stack.remove(n_tr)
            lru_stack.insert(0, n_tr)
        else:
            pos = None
            lru_stack.insert(0, n_tr)

        if n_tr in last_play_dt:
            h_since = (dt - last_play_dt[n_tr]).total_seconds() / 3600.0
        else:
            h_since = None
        last_play_dt[n_tr] = dt
        play_metrics.append((dt, tr, n_tr, pos, h_since))

    return play_metrics

def get_last_play_map_at(play_metrics, ref_dt):
    """Returns dict {norm_tr: last_dt} for all plays up to ref_dt."""
    last_map = {}
    for dt, tr, n_tr, pos, h_s in play_metrics:
        if dt <= ref_dt:
            last_map[n_tr] = dt
        else:
            break
    return last_map

def load_shows():
    """Loads Backlink Broadcast shows from schedule-history.csv, deduplicating by start time."""
    shows_by_start = {}
    if not os.path.exists(SCH_CSV):
        return []
    with open(SCH_CSV, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        next(reader, None)
        for r in reader:
            if not r or len(r) < 6 or r[1] != 'Backlink Broadcast':
                continue
            ts_mesz, station, show_name, started_at_utc, dur_min, desc = r
            try:
                dt_utc = datetime.fromisoformat(started_at_utc.replace('Z', '+00:00')).replace(tzinfo=None)
                dur = int(dur_min)
                dt_end_utc = dt_utc + timedelta(minutes=dur)
                dt_loc_start = utc_to_vienna(dt_utc)
                dt_loc_end = utc_to_vienna(dt_end_utc)
                st_key_16 = show_start_key_from_utc(dt_utc)
                key = st_key_16 + ":00"
                shows_by_start[key] = {
                    'start_dt': dt_utc,
                    'end_dt': dt_end_utc,
                    'loc_start_dt': dt_loc_start,
                    'start_key': st_key_16,
                    'start_str': dt_loc_start.strftime('%Y-%m-%d %H:%M:%S'),
                    'end_str': dt_loc_end.strftime('%Y-%m-%d %H:%M:%S'),
                    'duration': dur,
                    'show_name': show_name.strip(),
                    'show_desc': desc.strip()
                }
            except Exception:
                continue
    res = list(shows_by_start.values())
    res.sort(key=lambda x: x['start_dt'])
    return res

def load_listeners(min_dt_str):
    """Loads listener snapshots >= min_dt_str."""
    points = defaultdict(dict)
    if not os.path.exists(LIS_CSV):
        return points
    with open(LIS_CSV, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        next(reader, None)
        for r in reader:
            if not r or len(r) < 3:
                continue
            ts, st, curr = r[0], r[1], r[2]
            if ts >= min_dt_str:
                try:
                    points[ts][st] = int(curr)
                except ValueError:
                    pass
    return points

def compute_listener_stats(points, start_str, end_str):
    bb_vals = []
    rel_vals = []
    for ts, data in points.items():
        if start_str <= ts < end_str:
            bb = data.get('Backlink Broadcast')
            tot = sum(data.values())
            if bb is not None:
                bb_vals.append(bb)
                if tot > 0:
                    rel_vals.append(bb / tot)
    avg_abs = sum(bb_vals) / len(bb_vals) if bb_vals else 0.0
    avg_rel = (sum(rel_vals) / len(rel_vals) * 100.0) if rel_vals else 0.0
    return avg_abs, avg_rel, len(bb_vals)

def match_playlist_against_archive(playlist_lines, archive_by_norm, archive_by_artist, unplayed_sorted):
    """
    Takes 25 suggested 'Artist - Title' strings, matches against bb_only.json,
    and builds the candidate pool (other songs by those artists + 20 LRP tracks).
    """
    playlist_items = []
    for line in playlist_lines:
        line = re.sub(r'^\d+[\.\)\-]\s*', '', line.strip())
        if '-' in line:
            parts = line.split('-', 1)
            art = parts[0].strip()
            tit = parts[1].strip()
            playlist_items.append((art, tit, f"{art} - {tit}"))

    archiv_vorhanden = []
    suggested_artists_norm = set()

    for art, tit, full in playlist_items:
        n_art = norm(art)
        n_tit = norm(tit)
        n_full = norm(full)
        suggested_artists_norm.add(n_art)

        match = None
        if n_full in archive_by_norm:
            match = archive_by_norm[n_full]
        elif n_art in archive_by_artist:
            for a_item in archive_by_artist[n_art]:
                if n_tit in norm(a_item.get('title', '')) or norm(a_item.get('title', '')) in n_tit:
                    match = a_item
                    break
        if match:
            # Avoid duplicate matches
            m_norm = norm(f"{match.get('artist')} - {match.get('title')}")
            if not any(norm(f"{x.get('artist')} - {x.get('title')}") == m_norm for x in archiv_vorhanden):
                archiv_vorhanden.append(match)

    # Candidate pool: other tracks by suggested artists
    kandidaten_pool = {}
    vorhanden_norms = set(norm(f"{m.get('artist')} - {m.get('title')}") for m in archiv_vorhanden)

    for n_art in suggested_artists_norm:
        if n_art in archive_by_artist:
            for a_item in archive_by_artist[n_art]:
                n_f = norm(f"{a_item.get('artist', '')} - {a_item.get('title', '')}")
                if n_f not in vorhanden_norms:
                    kandidaten_pool[n_f] = a_item

    # Add 20 LRP tracks
    added_lrp = 0
    for days, item in unplayed_sorted:
        n_f = norm(f"{item.get('artist', '')} - {item.get('title', '')}")
        if n_f not in kandidaten_pool and n_f not in vorhanden_norms:
            kandidaten_pool[n_f] = item
            added_lrp += 1
            if added_lrp >= 20:
                break

    return archiv_vorhanden, list(kandidaten_pool.values())[:45]

def evaluate_show_hour(client, show, show_plays, archive_by_norm, archive_by_artist, bb_lib, last_play_map):
    """
    Runs the Gemini 4 Argon analysis for a single show hour:
    - Call 1: Generate 25 ideal tracks for Schedule (A) AND 25 ideal tracks for Actual Vibe (B)
    - Match both against archive -> 5a, 5b and candidate pools A & B
    - Call 2: Rate candidate pools A & B (1-10) + evaluate Fit Score (7) & Wording surgery (8)
    """
    show_name = show['show_name']
    show_desc = show['show_desc']
    time_str = show['start_dt'].strftime('%H:%M')
    end_dt = show['end_dt']

    played_tracks_str = "\\n".join(f"- {p[1]}" for p in show_plays) if show_plays else "- (Keine Titel in dieser Stunde gespielt)"

    # Sort archive by unplayed days at the end of the show
    unplayed_sorted = []
    for item in bb_lib:
        n_f = norm(f"{item.get('artist', '')} - {item.get('title', '')}")
        dt_last = last_play_map.get(n_f)
        days = (end_dt - dt_last).total_seconds() / 86400.0 if dt_last else 130.0
        unplayed_sorted.append((days, item))
    unplayed_sorted.sort(key=lambda x: x[0], reverse=True)

    # --- CALL 1: Generate both 25-track playlists (Schedule A & Vibe B) ---
    prompt1 = f"""Du bist Musikchef des Radiosenders Backlink Broadcast.
Wir analysieren die Sendestunde um {time_str} Uhr MESZ.

Offizielle Sendung laut Sendeplan:
Name: "{show_name}"
Beschreibung: "{show_desc}"

Tatsächlich in dieser Stunde im Radio gelaufene Musiktitel:
{played_tracks_str}

Aufgabe:
1. Erstelle unter "=== PLAYLIST_SENDEPLAN ===" genau 25 passende, starke Musiktitel, die ideal zum offiziellen Sendungsnamen und der Beschreibung passen.
2. Erstelle unter "=== PLAYLIST_REAL_VIBE ===" genau 25 passende, starke Anschlusstitel, die sich ausschließlich am tatsächlichen musikalischen Stil/Vibe der in dieser Stunde gelaufenen Titel orientieren.

Wichtig: Gib unter beiden Überschriften jeweils ausschließlich nummerierte Zeilen im Format "Interpret - Titel" aus, ohne weiteren Text."""

    resp1 = client.models.generate_content(model=MODEL_NAME, contents=prompt1)
    text1 = resp1.text.strip()

    lines_a, lines_b = [], []
    mode = None
    for line in text1.splitlines():
        if "PLAYLIST_SENDEPLAN" in line:
            mode = 'A'
            continue
        elif "PLAYLIST_REAL_VIBE" in line:
            mode = 'B'
            continue
        if mode == 'A' and '-' in line:
            lines_a.append(line)
        elif mode == 'B' and '-' in line:
            lines_b.append(line)

    vorhanden_a, kand_a = match_playlist_against_archive(lines_a, archive_by_norm, archive_by_artist, unplayed_sorted)
    vorhanden_b, kand_b = match_playlist_against_archive(lines_b, archive_by_norm, archive_by_artist, unplayed_sorted)

    kand_a_lines = "\\n".join(f"A{i+1}: {x.get('artist')} - {x.get('title')}" for i, x in enumerate(kand_a))
    kand_b_lines = "\\n".join(f"B{i+1}: {x.get('artist')} - {x.get('title')}" for i, x in enumerate(kand_b))

    # --- CALL 2: Score candidates A & B + Evaluate Fit (7) & Description surgery (8) ---
    prompt2 = f"""Wir bewerten das Musikarchiv und die Sendungsbeschreibung für die Stunde um {time_str} Uhr MESZ.

Offizielle Sendung laut Sendeplan:
Name: "{show_name}"
Beschreibung: "{show_desc}"

Tatsächlich in dieser Stunde gespielte Titel:
{played_tracks_str}

Aufgabe 1 (Kandidaten-Bewertung für Sendeplan-Soll):
Vergib für jeden Kandidaten A1..A{len(kand_a)} eine Note von 1 bis 10, wie gut er zur offiziellen Sendung "{show_name}" ({show_desc}) passt.
Format unter === SCORES_A ===:
A1: [Note]
A2: [Note]
...

Aufgabe 2 (Kandidaten-Bewertung für Ist-Vibe):
Vergib für jeden Kandidaten B1..B{len(kand_b)} eine Note von 1 bis 10, wie gut er zum tatsächlichen musikalischen Vibe der gespielten Titel passt.
Format unter === SCORES_B ===:
B1: [Note]
B2: [Note]
...

Aufgabe 3 (Übereinstimmung & Feinschliff der Sendungsbeschreibung):
Gib unter === DIAGNOSE === ein kurzes JSON-Objekt mit genau zwei Feldern aus:
- "fit_score": Ganzzahl von 1 bis 10 (Wie gut passen die tatsächlich gespielten Titel zur offiziellen Sendungsbeschreibung? 10 = perfekt, 1 = komplettes Gegenteil)
- "anpassung": Konkreter, präziser Vorschlag auf Deutsch (1-2 Sätze), was am Sendungsnamen oder der Beschreibung geändert werden müsste, um die tatsächlich gespielte Musik zu treffen. Achte besonders auf sprachliche Feinheiten: Oft reicht es schon, ein einzelnes irreführendes Wort (wie z.B. "Indie", "Ambient", "Late-Night" oder "Japanese City Pop") zu streichen oder durch ein passenderes Schlagwort (z.B. "Pop", "Deutschrap", "Classic Rock") zu ersetzen, statt alles komplett umzuschreiben! Falls ein ganz neues Format nötig ist, nenne einen kurzen Titelvorschlag.

Hier sind die Kandidaten A:
{kand_a_lines}

Hier sind die Kandidaten B:
{kand_b_lines}"""

    resp2 = client.models.generate_content(model=MODEL_NAME, contents=prompt2)
    text2 = resp2.text.strip()

    scores_a = {}
    scores_b = {}
    for m in re.finditer(r'A(\d+)\s*:\s*(?:\[)?(\d+)(?:\])?', text2):
        idx = int(m.group(1)) - 1
        sc = int(m.group(2))
        if 0 <= idx < len(kand_a):
            scores_a[idx] = min(10, max(1, sc))

    for m in re.finditer(r'B(\d+)\s*:\s*(?:\[)?(\d+)(?:\])?', text2):
        idx = int(m.group(1)) - 1
        sc = int(m.group(2))
        if 0 <= idx < len(kand_b):
            scores_b[idx] = min(10, max(1, sc))

    fit_score = 5
    anpassung = "Keine Diagnose verfügbar"
    if "=== DIAGNOSE ===" in text2:
        diag_part = text2.split("=== DIAGNOSE ===", 1)[1].strip()
        jm = re.search(r'\{.*?\}', diag_part, re.DOTALL)
        if jm:
            try:
                jd = json.loads(jm.group(0))
                fit_score = jd.get('fit_score', 5)
                anpassung = jd.get('anpassung', '').strip()
            except Exception:
                pass

    # Calculate 6a and 6b:
    # Total eligible (score >= 4) = direct hits (vorhanden, score 10) + candidates with score >= 4
    # Also check how many of those were free (> 48h unplayed at show end_dt)
    def count_pool(vorhanden_list, kand_list, sc_map):
        eligible_items = list(vorhanden_list)
        for idx, item in enumerate(kand_list):
            if sc_map.get(idx, 5) >= 4:
                eligible_items.append(item)
        total_6 = len(eligible_items)
        free_48h = 0
        for item in eligible_items:
            n_f = norm(f"{item.get('artist', '')} - {item.get('title', '')}")
            dt_l = last_play_map.get(n_f)
            if dt_l is None or (end_dt - dt_l).total_seconds() >= 48 * 3600:
                free_48h += 1
        return total_6, free_48h

    tot_6a, free_6a = count_pool(vorhanden_a, kand_a, scores_a)
    tot_6b, free_6b = count_pool(vorhanden_b, kand_b, scores_b)

    return {
        '5a': len(vorhanden_a),
        '5b': len(vorhanden_b),
        '6a_tot': tot_6a,
        '6a_free': free_6a,
        '6b_tot': tot_6b,
        '6b_free': free_6b,
        '7_fit': fit_score,
        '8_anpassung': anpassung
    }

def main():
    args = sys.argv[1:]
    hours_back = 24
    max_shows = None
    force_recalc = False

    i = 0
    while i < len(args):
        if args[i] == '--hours' and i + 1 < len(args):
            hours_back = int(args[i+1])
            i += 1
        elif args[i] == '--limit' and i + 1 < len(args):
            max_shows = int(args[i+1])
            i += 1
        elif args[i] == '--force':
            force_recalc = True
        elif args[i] in ('-h', '--help'):
            print("Verwendung: py analyze_schedule_matrix.py [--hours N] [--limit M] [--force]")
            print("  --hours N   Analysiere die abgeschlossenen Sendungen der letzten N Stunden (Default: 24)")
            print("  --limit M   Analysiere maximal M Sendungen in diesem Lauf")
            print("  --force     Bereits in der CSV vorhandene Sendungen neu berechnen")
            sys.exit(0)
        i += 1

    client = genai_client.Client()

    print("Lade Archiv, Sendeplan, Musik-Log und Hörerzahlen...")
    bb_lib = load_archive()
    archive_by_norm = {}
    archive_by_artist = defaultdict(list)
    for item in bb_lib:
        art = item.get('artist', '')
        tit = item.get('title', '')
        full = f"{art} - {tit}"
        archive_by_norm[norm(full)] = item
        archive_by_artist[norm(art)].append(item)

    play_metrics = load_music_and_stack()
    all_shows = load_shows()

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_start = now_utc - timedelta(hours=hours_back + 1)

    # Filter completed shows in window using exact UTC timestamps!
    target_shows = [s for s in all_shows if s['start_dt'] >= cutoff_start and s['end_dt'] <= now_utc]
    if hours_back and len(target_shows) > hours_back:
        target_shows = target_shows[-hours_back:]

    # Load existing CSV rows to avoid re-running LLM calls for already analyzed shows
    existing_rows = {}
    if os.path.exists(OUT_CSV) and not force_recalc:
        with open(OUT_CSV, 'r', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get('Startzeit'):
                    existing_rows[r['Startzeit']] = r

    min_dt_str = target_shows[0]['start_str'] if target_shows else '2026-10-19 00:00:00'
    listener_points = load_listeners(min_dt_str)

    print(f"Gefundene abgeschlossene Sendungen im Zeitfenster: {len(target_shows)}")

    processed_count = 0
    for s in target_shows:
        st_key = s.get('start_key', s['start_str'][:16]) # YYYY-MM-DD HH:MM
        if st_key in existing_rows and not force_recalc:
            print(f"  [Überspringe bereits berechnete Sendung] {st_key} | {s['show_name']}")
            continue

        if max_shows is not None and processed_count >= max_shows:
            break

        print(f"\nAnalysiere [{st_key}] {s['show_name']} ...")
        s_plays = [p for p in play_metrics if s['start_dt'] <= p[0] < s['end_dt']]

        # Parameter 4: Fishing Depth
        intervals = [p[4] for p in s_plays if p[4] is not None]
        stacks = [p[3] for p in s_plays if p[3] is not None]
        if intervals:
            avg_h = sum(intervals) / len(intervals)
            med_h = sorted(intervals)[len(intervals)//2]
            avg_st = sum(stacks) / len(stacks) if stacks else 0
            knapp = sum(1 for h in intervals if h <= 54.0) # <= 2.25 days
            depth_str = f"Ø {avg_h:.1f}h ({avg_h/24:.1f}d) | Med {med_h:.1f}h | Stack #{avg_st:.0f} ({knapp}/{len(s_plays)} <=54h)"
        else:
            depth_str = "Keine Daten (0 Plays)"

        # Parameter 9 & 10: Listeners
        avg_abs, avg_rel, n_lis = compute_listener_stats(listener_points, s['start_str'], s['end_str'])

        # Parameters 5a, 5b, 6a, 6b, 7, 8 via Gemini 4 Argon
        last_play_map = get_last_play_map_at(play_metrics, s['end_dt'])
        llm_res = evaluate_show_hour(client, s, s_plays, archive_by_norm, archive_by_artist, bb_lib, last_play_map)

        row_dict = {
            'Startzeit': st_key,
            'Show_Name': s['show_name'],
            'Show_Beschreibung': s['show_desc'],
            'Plays': str(len(s_plays)),
            '4_Fishing_Depth': depth_str,
            '5a_Archiv_Sendeplan': f"{llm_res['5a']}/25",
            '5b_Archiv_RealVibe': f"{llm_res['5b']}/25",
            '6a_Pool_Sendeplan': f"{llm_res['6a_tot']} ({llm_res['6a_free']} frei >48h)",
            '6b_Pool_RealVibe': f"{llm_res['6b_tot']} ({llm_res['6b_free']} frei >48h)",
            '7_Fit_Score': f"{llm_res['7_fit']}/10",
            '8_Anpassung_Vorschlag': llm_res['8_anpassung'],
            '9_Hoerer_Absolut': f"{avg_abs:.2f}",
            '10_Marktanteil_Rel': f"{avg_rel:.1f}%"
        }

        existing_rows[st_key] = row_dict
        processed_count += 1
        print(f"  -> Depth: {depth_str}")
        print(f"  -> 5a: {row_dict['5a_Archiv_Sendeplan']} | 5b: {row_dict['5b_Archiv_RealVibe']} | 6a: {row_dict['6a_Pool_Sendeplan']} | 6b: {row_dict['6b_Pool_RealVibe']}")
        print(f"  -> 7 (Fit): {row_dict['7_Fit_Score']} | 9 (Hörer): {row_dict['9_Hoerer_Absolut']} ({row_dict['10_Marktanteil_Rel']})")
        print(f"  -> 8 (Vorschlag): {row_dict['8_Anpassung_Vorschlag']}")

        # Save incrementally after each show
        save_outputs(existing_rows)

    print(f"\nFertig! {processed_count} neue Sendungen ausgewertet. Gesamt in Tabelle: {len(existing_rows)} Sendungen.")
    print(f"CSV gespeichert unter: {OUT_CSV}")
    print(f"Markdown gespeichert unter: {OUT_MD}")

def save_outputs(existing_rows):
    fieldnames = [
        'Startzeit', 'Show_Name', 'Show_Beschreibung', 'Plays',
        '4_Fishing_Depth', '5a_Archiv_Sendeplan', '5b_Archiv_RealVibe',
        '6a_Pool_Sendeplan', '6b_Pool_RealVibe', '7_Fit_Score',
        '8_Anpassung_Vorschlag', '9_Hoerer_Absolut', '10_Marktanteil_Rel'
    ]
    sorted_keys = sorted(existing_rows.keys())
    with open(OUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for k in sorted_keys:
            writer.writerow(existing_rows[k])

    # Also write readable Markdown summary
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write("# Backlink Broadcast – Automatische Programmanalyse (10-Parameter-Matrix)\\n\\n")
        f.write("| Startzeit (MESZ) | 1. Show-Name | 4. Fishing Depth | 5a. Archiv (Plan) | 5b. Archiv (Vibe) | 6a. Pool>=4 (Plan) | 6b. Pool>=4 (Vibe) | 7. Fit | 9. Hörer | 10. Quote | 8. Vorschlag zur Anpassung (Name / Beschreibung) |\\n")
        f.write("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\\n")
        for k in sorted_keys:
            r = existing_rows[k]
            f.write(f"| {r['Startzeit']} | **{r['Show_Name']}**<br>*(Desc: {r['Show_Beschreibung']})* | {r['4_Fishing_Depth']} | {r['5a_Archiv_Sendeplan']} | {r['5b_Archiv_RealVibe']} | {r['6a_Pool_Sendeplan']} | {r['6b_Pool_RealVibe']} | **{r['7_Fit_Score']}** | {r['9_Hoerer_Absolut']} | {r['10_Marktanteil_Rel']} | {r['8_Anpassung_Vorschlag']} |\\n")

if __name__ == '__main__':
    main()
