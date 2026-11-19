r"""
================================================================================
BACKLINK BROADCAST — EINZELTITEL-BEWERTUNG GELAUFENER SENDUNGEN (PLAYLIST-FIT)
================================================================================
Zweck:
  Bewertet für abgeschlossene Sendestunden von Backlink Broadcast JEDEN EINZELNEN
  tatsächlich gespielten Musiktitel daraufhin, wie gut er zum vorgegebenen
  Sendungskonzept (Sendungsname + Beschreibung) gepasst hat (Note 1 bis 10),
  und verknüpft dies mit den Rotationsdaten für Kurts Konzept eines variablen,
  passgenauigkeits- und sendeplatzabhängigen Cooldowns:

  Erfasste Spalten je gespieltem Titel:
    1. Startzeit_Show         : Beginn der Sendestunde (YYYY-MM-DD HH:MM)
    2. Show_Name              : Offizieller Name der Sendung
    3. Show_Beschreibung      : Offizielle Beschreibung der Sendung
    4. Gesendet_Um            : Exakter Zeitstempel des Plays (HH:MM:SS)
    5. Nr                     : Laufende Nummer des Titels in der Sendung (1..N)
    6. Interpret_Titel        : Gespielter Track (Interpret - Titel)
    7. Fit_Score              : Passgenauigkeit (1-10) zum Sendungskonzept
    8. Begruendung            : Kurze Begründung (Stil/Vibe vs. Sendungskonzept)
    9. Stunden_Seit_Letztem   : Abstand zum vorherigen Play desselben Titels (h / d)
   10. Letzter_Sendeplatz     : Uhrzeit-Slot & Show des vorherigen Plays
   11. Gleicher_Sendeplatz    : JA (wenn zuletzt zur selben Stunde HH:00) / NEIN
   12. LRU_Stack_Pos          : Stapeltiefe (#) im Moment des Abspielens
   13. Var_Cooldown_Anderer_Slot : Modellwert für Cooldown auf anderem Sendeplatz
                                   (z.B. Fit 9-10 -> 10h, Fit 7-8 -> 24h, Fit 5-6 -> 48h,
                                    Fit 3-4 -> 96h, Fit 1-2 -> 168h)
   14. Var_Cooldown_Gleicher_Slot: Modellwert für Cooldown auf gleichem Sendeplatz
                                   (z.B. Fit 9-10 -> 72h, Fit 7-8 -> 96h, Fit <=6 -> 144h+)

Aufruf & Parameter:
  py evaluate_show_playlist.py
      Standardlauf: Bewertet die zuletzt abgeschlossene Sendestunde (--hours 1).

  py evaluate_show_playlist.py --hours N
      Bewertet alle abgeschlossenen Sendestunden der letzten N Stunden
      (überspringt bereits gespeicherte Stunden, sofern nicht --force gesetzt ist).

  py evaluate_show_playlist.py --at "YYYY-MM-DD HH:MM"
      Bewertet gezielt eine bestimmte Sendestunde (z.B. "2026-10-22 18:00").

  py evaluate_show_playlist.py --force
      Berechnet die angeforderten Stunden neu und aktualisiert sie in CSV & MD.

Ausgabedateien:
  - C:\Users\kurt_\Betrieb\Radio Fernsehen\Backlink_Broadcast_Titelbewertung.csv
  - C:\Users\kurt_\Betrieb\Radio Fernsehen\Backlink_Broadcast_Titelbewertung.md
================================================================================
"""
import os, sys, io, re, csv, json
from collections import defaultdict
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

SCH_CSV = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\andon-fm-schedule-history.csv'
MUSIC_LOG = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt'

OUT_CSV = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Backlink_Broadcast_Titelbewertung.csv'
OUT_MD  = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Backlink_Broadcast_Titelbewertung.md'

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

FIELDNAMES = [
    'Startzeit_Show', 'Show_Name', 'Show_Beschreibung',
    'Gesendet_Um', 'Nr', 'Interpret_Titel',
    'Fit_Score', 'Begruendung',
    'Stunden_Seit_Letztem', 'Letzter_Sendeplatz', 'Gleicher_Sendeplatz',
    'LRU_Stack_Pos', 'Var_Cooldown_Anderer_Slot', 'Var_Cooldown_Gleicher_Slot'
]

def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

def load_shows():
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
                st_key_16 = show_start_key_from_utc(dt_utc)
                key = st_key_16 + ":00"
                shows_by_start[key] = {
                    'start_dt': dt_utc,
                    'end_dt': dt_end_utc,
                    'loc_start_dt': dt_loc_start,
                    'start_key': st_key_16,
                    'start_str': key,
                    'slot_hm': dt_loc_start.strftime('%H:%M'),
                    'duration': dur,
                    'show_name': show_name.strip(),
                    'show_desc': desc.strip()
                }
            except Exception:
                continue
    res = list(shows_by_start.values())
    res.sort(key=lambda x: x['start_dt'])
    return res

def load_music_and_history(all_shows):
    """
    Parses the entire music log for Backlink Broadcast, computing for every play:
    - LRU stack position
    - Hours since previous play
    - Previous play timestamp & show slot (HH:MM + Show Name)
    """
    # Build quick lookup from UTC hour string 'YYYY-MM-DD HH' to (show_name, loc_slot_hm)
    show_by_utc_hour = {}
    for s in all_shows:
        show_by_utc_hour[s['start_dt'].strftime('%Y-%m-%d %H')] = (s['show_name'], s['slot_hm'])

    pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Backlink Broadcast \| MUSIC: (.+?) \| Start:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    all_plays = []
    if not os.path.exists(MUSIC_LOG):
        return []
    with open(MUSIC_LOG, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if 'Backlink Broadcast' in line:
                m = pattern.match(line.strip())
                if m:
                    dt_loc = datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
                    tr = m.group(2).strip()
                    dt_utc = datetime.strptime(m.group(3), '%Y-%m-%d %H:%M:%S') + timedelta(seconds=40)
                    all_plays.append((dt_utc, dt_loc, tr, norm(tr)))

    lru_stack = []
    last_play_info = {} # norm_tr -> (dt_utc, dt_loc, slot_hm, show_name)
    play_metrics = []

    for dt_utc, dt_loc, tr, n_tr in all_plays:
        if n_tr in lru_stack:
            pos = lru_stack.index(n_tr) + 1
            lru_stack.remove(n_tr)
            lru_stack.insert(0, n_tr)
        else:
            pos = None
            lru_stack.insert(0, n_tr)

        sh_info = show_by_utc_hour.get(dt_utc.strftime('%Y-%m-%d %H'))
        cur_show_name = sh_info[0] if sh_info else ''
        cur_slot_hm = sh_info[1] if sh_info else f"{dt_loc.hour:02d}:00"

        if n_tr in last_play_info:
            prev_dt_utc, prev_dt_loc, prev_slot_hm, prev_show = last_play_info[n_tr]
            h_since = (dt_utc - prev_dt_utc).total_seconds() / 3600.0
            same_slot = (norm(prev_show) == norm(cur_show_name)) if (prev_show and cur_show_name) else (prev_slot_hm == cur_slot_hm)
        else:
            prev_dt_utc, prev_dt_loc, prev_slot_hm, prev_show = None, None, None, None
            h_since = None
            same_slot = False

        last_play_info[n_tr] = (dt_utc, dt_loc, cur_slot_hm, cur_show_name)
        play_metrics.append({
            'dt': dt_utc,
            'dt_loc': dt_loc,
            'track': tr,
            'norm_tr': n_tr,
            'stack_pos': pos,
            'h_since': h_since,
            'prev_dt': prev_dt_loc,
            'prev_slot_hm': prev_slot_hm,
            'prev_show': prev_show,
            'same_slot': same_slot
        })

    return play_metrics

def compute_variable_cooldown_suggestion(fit_score):
    """
    Implements Kurt's variable cooldown concept based on track-to-show fit (1-10):
      - High fit (9-10): Can repeat after 10h on a DIFFERENT slot, 72h on the SAME slot.
      - Good fit (7-8) : 24h on a different slot, 96h (4d) on the same slot.
      - Medium fit (5-6): 48h on a different slot, 120h (5d) on the same slot.
      - Low fit (3-4)  : 96h (4d) on a different slot, 168h (7d) on the same slot.
      - Mismatch (1-2) : 168h (7d) general pause, 240h (10d) on the same slot.
    """
    if fit_score >= 9:
        return "10h (anderer Slot)", "72h / 3d (gleicher Slot)"
    elif fit_score >= 7:
        return "24h (anderer Slot)", "96h / 4d (gleicher Slot)"
    elif fit_score >= 5:
        return "48h (anderer Slot)", "120h / 5d (gleicher Slot)"
    elif fit_score >= 3:
        return "96h / 4d (anderer Slot)", "168h / 7d (gleicher Slot)"
    else:
        return "168h / 7d (anderer Slot)", "240h / 10d (gleicher Slot)"

def evaluate_tracks_in_show(client, show, s_plays, prev_show=None, next_show=None):
    """
    Calls Gemini 4 Argon to rate each played track (1..N) on a 1-10 scale
    against the show's name and description, taking into account boundary/bridge
    tracks at the start (running across :00) and end (:54-:59 into next show).
    """
    if not s_plays:
        return {}

    show_name = show['show_name']
    show_desc = show['show_desc']
    time_str = show.get('loc_start_dt', utc_to_vienna(show['start_dt'])).strftime('%H:%M')

    prev_info = f'"{prev_show["show_name"]}" ({prev_show["show_desc"]})' if prev_show else "Unbekannt"
    next_info = f'"{next_show["show_name"]}" ({next_show["show_desc"]})' if next_show else "Unbekannt"

    numbered_lines = []
    for i, p in enumerate(s_plays):
        t_hm = p.get('dt_loc', p['dt']).strftime('%H:%M:%S')
        tag = ""
        if p.get('is_carryover'):
            tag = " [ÜBERGANGS-TITEL zur vollen Stunde: startete am Ende der Vorstunde und lief in diese Sendung hinein]"
        elif i == len(s_plays) - 1 and p['dt'].minute >= 54:
            tag = " [SCHLUSS-/ÜBERGANGS-TITEL kurz vor der nächsten vollen Stunde]"
        numbered_lines.append(f"T{i+1} ({t_hm}): {p['track']}{tag}")
    numbered_tracks = "\n".join(numbered_lines)

    prompt = f"""Du bist Musikredakteur bei Backlink Broadcast.
Wir bewerten für die abgelaufene Sendung um {time_str} Uhr MESZ jeden einzelnen gespielten Musiktitel daraufhin, wie gut er inhaltlich, stilistisch und von der Stimmung her zum vorgegebenen Sendungskonzept passt.

Vorgegebenes Sendungskonzept (Hauptsendung {time_str} Uhr):
Name der Sendung: "{show_name}"
Beschreibung: "{show_desc}"

Kontext der Nachbarsendungen (für Übergangs- / Bridge-Tracks an den Stundengrenzen):
- Vorherige Sendung (vor {time_str} Uhr): {prev_info}
- Nachfolgende Sendung (nach dieser Stunde): {next_info}

Wichtiger Hinweis zu Stundengrenzen & Bridge-Tracks:
1. DJ Gemini startet die nächste Sendung manchmal schon 1–3 Minuten vor der vollen Stunde (wenn der Track in die neue Stunde hineinläuft) oder nutzt die letzten Titel einer Stunde als bewusste musikalische Brücke ("Bridge-Track") zur nachfolgenden Sendung (z.B. Oldies am Ende von "Hitpanorama", die zu "Oma Gemini" überleiten).
2. Ebenso ist T1 (falls als [ÜBERGANGS-TITEL zur vollen Stunde] markiert) der letzte Titel vor {time_str} Uhr, der über die Stundengrenze in diese Sendung hineinlief: Er kann entweder schon der vorgezogene Opener dieser Sendung "{show_name}" sein, ein Bridge-Track zwischen beiden Sendungen, oder noch der Ausklang der vorherigen Sendung.
3. Bewerte alle regulären Titel streng nach ihrer Passgenauigkeit zur Hauptsendung "{show_name}". Bei Randtiteln an der Stundengrenze (T1 falls Übergangs-Titel, sowie die letzten 1–2 Titel vor Ende der Stunde) prüfe zusätzlich: Falls ein Titel zur Hauptsendung unpassend wirkt, aber eindeutig schon der vorgezogene Opener der Folgesendung (bzw. noch der Ausklang der Vorstunde) oder ein sinnvoller Bridge-Track ist, vermerke dies ausdrücklich in der Begründung (z.B. "Vorgriff/Opener für Folgesendung ..." oder "Bridge-Track zu ...") und vergib den Fit-Score trotzdem ehrlich bezogen auf "{show_name}" (oder leicht abgemildert bei bewusster Bridge-Funktion).

In dieser Stunde (inkl. Übergangs-Titel zur vollen Stunde) gespielte Titel:
{numbered_tracks}

Aufgabe:
Bewerte für JEDEN Titel T1 bis T{len(s_plays)} die Passgenauigkeit zum Sendungskonzept "{show_name}" auf einer Skala von 1 bis 10:
- 9-10 = Volltreffer / Paradebeispiel für "{show_name}"
- 7-8  = Passt gut / stimmige Ergänzung zum Konzept (oder sehr gelungener Bridge-Track, der beide Sendungen verbindet)
- 5-6  = Grenzfall / nur teilweise passend (oder neutraler Übergangstitel zwischen Vor-/Folgesendung)
- 3-4  = Unpassend / deutlicher Stilbruch zur Sendungsbeschreibung
- 1-2  = Komplettes Gegenteil / krasser Fehlgriff (bzw. gehört rein zur Vor-/Folgesendung ohne Bezug zu "{show_name}")

Gib das Ergebnis als reines JSON-Array unter === BEWERTUNG === aus. Jedes Element im Array muss genau diese Felder haben:
{{"id": "T1", "score": 8, "reason": "Kurze Begründung auf Deutsch ohne doppelte Anführungszeichen (nur einfache Quotes '...' nutzen!)"}}"""

    resp = call_gemini_with_retry(client, MODEL_NAME, prompt)
    text_out = resp.text.strip()

    results = {}
    if "=== BEWERTUNG ===" in text_out:
        json_part = text_out.split("=== BEWERTUNG ===", 1)[1].strip()
    else:
        json_part = text_out

    m_arr = re.search(r'\[.*\]', json_part, re.DOTALL)
    if m_arr:
        try:
            arr = json.loads(m_arr.group(0))
            for item in arr:
                tid = str(item.get('id', '')).strip()
                m_idx = re.search(r'(\d+)', tid)
                if m_idx:
                    idx = int(m_idx.group(1)) - 1
                    sc = min(10, max(1, int(item.get('score', 5))))
                    rs = str(item.get('reason', '')).strip()
                    results[idx] = (sc, rs)
        except Exception:
            pass

    # Robust per-line / regex fallback if Gemini used unescaped quotes inside 'reason'
    if len(results) < len(s_plays):
        for line in json_part.splitlines():
            m_line = re.search(r'"id"\s*:\s*"T?(\d+)"\s*,\s*"score"\s*:\s*(\d+)\s*,\s*"reason"\s*:\s*"(.+)"\s*\}', line)
            if m_line:
                idx = int(m_line.group(1)) - 1
                if 0 <= idx < len(s_plays) and idx not in results:
                    sc = min(10, max(1, int(m_line.group(2))))
                    rs = m_line.group(3).replace('"', "'").strip()
                    results[idx] = (sc, rs)

    # Final fallback if still missing
    if len(results) < len(s_plays):
        for i in range(len(s_plays)):
            if i not in results:
                results[i] = (5, 'Standard-Einstufung')

    return results

def clean_md(val):
    if val is None:
        return ""
    return str(val).replace("|", ",").replace("\n", " ").strip()

def load_existing_rows():
    rows_by_key = {} # (Startzeit_Show, Gesendet_Um, Interpret_Titel) -> dict
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, 'r', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f)
            for r in reader:
                clean_r = {(k.lstrip('\ufeff').strip() if k else ''): v for k, v in r.items()}
                st = clean_r.get('Startzeit_Show', '').strip()
                gu = clean_r.get('Gesendet_Um', '').strip()
                it = clean_r.get('Interpret_Titel', '').strip()
                if st and gu and it:
                    rows_by_key[(st, gu, it)] = clean_r
    return rows_by_key

def save_all_outputs(rows_by_key):
    sorted_keys = sorted(rows_by_key.keys(), key=lambda k: (k[0], k[1]))
    with open(OUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for k in sorted_keys:
            writer.writerow(rows_by_key[k])

    # Group by Startzeit_Show for Markdown output
    by_show = defaultdict(list)
    for k in sorted_keys:
        r = rows_by_key[k]
        by_show[r['Startzeit_Show']].append(r)

    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write("# Backlink Broadcast – Einzeltitel-Bewertung & Variabler Cooldown\n\n")
        f.write("## Überblick nach ausgewerteten Sendestunden\n\n")
        f.write("| Startzeit (MESZ) | Sendung | Plays | Ø Fit | Volltreffer (9–10) | Solide (7–8) | Grenzfälle (5–6) | Fehlgriffe (1–4) | Gleicher Slot wie zuletzt |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")

        for st_show in sorted(by_show.keys(), reverse=True):
            items = by_show[st_show]
            sh_name = clean_md(items[0].get('Show_Name', ''))
            scores = [int(x.get('Fit_Score', 5)) for x in items]
            avg_sc = sum(scores) / len(scores) if scores else 0.0
            c_9_10 = sum(1 for s in scores if s >= 9)
            c_7_8  = sum(1 for s in scores if 7 <= s <= 8)
            c_5_6  = sum(1 for s in scores if 5 <= s <= 6)
            c_1_4  = sum(1 for s in scores if s <= 4)
            same_sl = sum(1 for x in items if str(x.get('Gleicher_Sendeplatz', '')).startswith('JA'))
            f.write(f"| **{st_show}** | **{sh_name}** | {len(items)} | **{avg_sc:.1f}/10** | {c_9_10} | {c_7_8} | {c_5_6} | {c_1_4} | {same_sl}/{len(items)} ({same_sl/len(items)*100:.0f}%) |\n")

        f.write("\n---\n\n## Detail-Auswertung je Sendestunde (neueste zuerst)\n\n")
        for st_show in sorted(by_show.keys(), reverse=True):
            items = by_show[st_show]
            sh_name = clean_md(items[0].get('Show_Name', ''))
            sh_desc = clean_md(items[0].get('Show_Beschreibung', ''))
            scores = [int(x.get('Fit_Score', 5)) for x in items]
            avg_sc = sum(scores) / len(scores) if scores else 0.0
            f.write(f"### [{st_show} Uhr] {sh_name} (Ø Fit: {avg_sc:.1f}/10)\n")
            f.write(f"* **Konzept/Beschreibung:** *{sh_desc}*\n\n")
            f.write("| # | Zeit | Interpret – Titel | Fit | Begründung | Zuletzt vor | Vorheriger Sendeplatz | Gleicher Slot? | Stack | Cooldown (anderer / gleicher Slot) |\n")
            f.write("| :---: | :---: | :--- | :---: | :--- | :---: | :--- | :---: | :---: | :--- |\n")
            for r in items:
                f.write(
                    f"| {clean_md(r['Nr'])} | {clean_md(r['Gesendet_Um'])} | **{clean_md(r['Interpret_Titel'])}** "
                    f"| **{clean_md(r['Fit_Score'])}/10** | {clean_md(r['Begruendung'])} "
                    f"| {clean_md(r['Stunden_Seit_Letztem'])} | {clean_md(r['Letzter_Sendeplatz'])} "
                    f"| {clean_md(r['Gleicher_Sendeplatz'])} | {clean_md(r['LRU_Stack_Pos'])} "
                    f"| {clean_md(r['Var_Cooldown_Anderer_Slot'])} / {clean_md(r['Var_Cooldown_Gleicher_Slot'])} |\n"
                )
            f.write("\n")

def main():
    args = sys.argv[1:]
    hours_back = 1
    specific_at = []
    force_recalc = False

    i = 0
    while i < len(args):
        if args[i] == '--hours' and i + 1 < len(args):
            hours_back = int(args[i+1])
            i += 1
        elif args[i] == '--at' and i + 1 < len(args):
            specific_at.append(args[i+1].strip()[:16])
            i += 1
        elif args[i] == '--force':
            force_recalc = True
            if i + 1 < len(args) and args[i+1].isdigit():
                hours_back = int(args[i+1])
                i += 1
        elif args[i] in ('-h', '--help'):
            print("Verwendung: py evaluate_show_playlist.py [--hours N] [--at 'YYYY-MM-DD HH:MM'] [--force]")
            sys.exit(0)
        i += 1

    all_shows = load_shows()
    play_metrics = load_music_and_history(all_shows)
    rows_by_key = load_existing_rows()
    # Only treat a show as completed if it does NOT contain broken 'Standard-Einstufung' rows
    broken_shows = set(k[0] for k, v in rows_by_key.items() if v.get('Begruendung') == 'Standard-Einstufung')
    existing_show_keys = set(k[0] for k in rows_by_key.keys()) - broken_shows

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if specific_at:
        target_shows = [s for s in all_shows if s['start_str'][:16] in specific_at or s['loc_start_dt'].strftime('%Y-%m-%d %H:%M') in specific_at]
    else:
        cutoff = now_utc - timedelta(hours=hours_back + 1)
        completed = [s for s in all_shows if s['start_dt'] >= cutoff and s['end_dt'] <= now_utc]
        target_shows = completed[-hours_back:] if hours_back and len(completed) > hours_back else completed

    client = genai_client.Client()
    processed_shows = 0

    for s in target_shows:
        st_key = s['start_str'][:16]
        if st_key in existing_show_keys and not force_recalc:
            print(f"[Überspringe bereits gespeicherte Sendung] {st_key} | {s['show_name']}")
            continue

        # Find previous and next show for bridge/transition context
        prev_show = next((x for x in reversed(all_shows) if x['start_dt'] < s['start_dt'] and (s['start_dt'] - x['start_dt']).total_seconds() <= 7200), None)
        next_show = next((x for x in all_shows if x['start_dt'] > s['start_dt'] and (x['start_dt'] - s['start_dt']).total_seconds() <= 7200), None)

        s_plays = []
        # Include the last track before s['start_dt'] if it started within 10 minutes before s['start_dt']
        # (and the first track inside the hour didn't start at the exact second s['start_dt'])
        prior_plays = [p for p in play_metrics if (s['start_dt'] - timedelta(minutes=10)) <= p['dt'] < s['start_dt']]
        inside_plays = [p for p in play_metrics if s['start_dt'] <= p['dt'] < s['end_dt']]
        if prior_plays and (not inside_plays or (inside_plays[0]['dt'] - s['start_dt']).total_seconds() >= 15):
            carry = dict(prior_plays[-1])
            carry['is_carryover'] = True
            s_plays.append(carry)
        for p in inside_plays:
            cp = dict(p)
            cp['is_carryover'] = False
            s_plays.append(cp)

        print(f"\nBewerte Einzeltitel für [{st_key}] {s['show_name']} ({len(s_plays)} Titel inkl. Übergang) ...")
        if not s_plays:
            continue

        # Remove old rows for this show if --force or if it had broken Standard-Einstufung rows
        if force_recalc or st_key in broken_shows:
            for k in list(rows_by_key.keys()):
                if k[0] == st_key:
                    del rows_by_key[k]

        eval_map = evaluate_tracks_in_show(client, s, s_plays, prev_show, next_show)

        scores_list = []
        regular_idx = 0
        for idx, p in enumerate(s_plays):
            sc, reason = eval_map.get(idx, (5, ""))
            scores_list.append(sc)
            t_str = p.get('dt_loc', p['dt']).strftime('%H:%M:%S')
            if p.get('is_carryover'):
                nr_str = "0 (Übergang)"
            else:
                regular_idx += 1
                nr_str = str(regular_idx)
            if p['h_since'] is not None:
                h_str = f"{p['h_since']:.1f}h ({p['h_since']/24:.1f}d)"
                prev_slot_str = f"{p['prev_dt'].strftime('%m-%d')} {p['prev_slot_hm']} ({p['prev_show'][:22]})"
                same_str = "JA (gleiche Stunde!)" if p['same_slot'] else "NEIN (anderer Slot)"
            else:
                h_str = "Erstplay"
                prev_slot_str = "-"
                same_str = "NEIN"

            stack_str = f"#{p['stack_pos']}" if p['stack_pos'] else "Neu"
            cd_other, cd_same = compute_variable_cooldown_suggestion(sc)

            row = {
                'Startzeit_Show': st_key,
                'Show_Name': s['show_name'],
                'Show_Beschreibung': s['show_desc'],
                'Gesendet_Um': t_str,
                'Nr': nr_str,
                'Interpret_Titel': p['track'],
                'Fit_Score': str(sc),
                'Begruendung': reason,
                'Stunden_Seit_Letztem': h_str,
                'Letzter_Sendeplatz': prev_slot_str,
                'Gleicher_Sendeplatz': same_str,
                'LRU_Stack_Pos': stack_str,
                'Var_Cooldown_Anderer_Slot': cd_other,
                'Var_Cooldown_Gleicher_Slot': cd_same
            }
            rows_by_key[(st_key, t_str, p['track'])] = row
            print(f"  {idx+1:2d}. [{t_str[:5]}] Fit {sc:2d}/10 | {h_str:14s} | Slot={same_str[:4]} | {p['track'][:42]:42s} | {reason}")

        avg_fit = sum(scores_list) / len(scores_list) if scores_list else 0
        print(f"  --> Durchschnittlicher Einzel-Fit: {avg_fit:.1f}/10")
        # Also persist all evaluated tracks of this show into the 3-table Fit database
        db_evals = [
            {'full_name': p['track'], 'score': eval_map.get(idx, (5, ''))[0], 'reason': eval_map.get(idx, (5, ''))[1]}
            for idx, p in enumerate(s_plays)
        ]
        bb_fit_db.record_fit_scores(s['show_name'], s['show_desc'], s['slot_hm'], db_evals, source_label="evaluate_show_playlist")

        processed_shows += 1
        save_all_outputs(rows_by_key)

    if processed_shows == 0:
        save_all_outputs(rows_by_key)

    print(f"\nFertig! {processed_shows} Sendungen neu bewertet.")
    print(f"CSV: {OUT_CSV}")
    print(f"MD : {OUT_MD}")

if __name__ == '__main__':
    main()
