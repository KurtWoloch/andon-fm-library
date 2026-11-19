import sys, io, subprocess, tempfile, os
import urllib.request, re, json
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LOG_DIR = r"C:\Users\kurt_\Betrieb\Radio Fernsehen"
SCHEDULE_LOG_FILE = os.path.join(LOG_DIR, "Andon FM Station logs.txt.shows.txt")
SCHEDULE_CSV_FILE = os.path.join(LOG_DIR, "andon-fm-schedule-history.csv")

MESZ = timezone(timedelta(hours=2))

def fetch_radio_data():
    req = urllib.request.Request('https://andonlabs.com/radio', headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode('utf-8')

    m = re.search(r'node_ids.*?data:\s*(\[.*?\])\s*,\s*form', html, re.DOTALL)
    if not m:
        return None

    data_js = m.group(1)
    node_script = f"process.stdout.write(JSON.stringify({data_js}))"

    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(node_script)
        tmp_path = f.name

    try:
        result = subprocess.run(['node', tmp_path], capture_output=True, timeout=10)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout.decode('utf-8'))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    for item in data:
        if item.get("type") == "data" and item.get("data") and "stations" in item.get("data", {}):
            return item["data"]["stations"]
    return None

def log_current_shows():
    stations = fetch_radio_data()
    if not stations:
        print("Fehler beim Abrufen der Stationsdaten")
        return

    now_local = datetime.now()
    now_str = now_local.strftime('%Y-%m-%d %H:%M:%S')

    # Ensure CSV exists with header
    csv_exists = os.path.exists(SCHEDULE_CSV_FILE)
    
    # Read existing entries to prevent duplicate logging of the same show instance
    existing_shows = set()
    if os.path.exists(SCHEDULE_LOG_FILE):
        with open(SCHEDULE_LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Format: 2026-09-10 15:06:00 | Backlink Broadcast | SHOW: ROCK & INDIE HYMNEN-PARADE 🎸⚡ | Start: ...
                if '| SHOW:' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 4:
                        st = parts[1].strip()
                        sh = parts[2].strip()
                        start_part = parts[3].strip()
                        existing_shows.add((st, sh, start_part))

    new_entries_count = 0
    with open(SCHEDULE_LOG_FILE, 'a', encoding='utf-8') as f_txt, open(SCHEDULE_CSV_FILE, 'a', encoding='utf-8', newline='') as f_csv:
        import csv
        writer = csv.writer(f_csv)
        if not csv_exists:
            writer.writerow(["Timestamp_MESZ", "Station", "Show_Name", "Started_At", "Duration_Min", "Description"])

        for s in stations:
            st_name = s.get("name")
            cb = s.get("currentBlock")
            if not cb:
                continue

            show_name = cb.get("name", "").strip()
            desc = cb.get("description", "").strip().replace("\n", " ")
            start_iso = cb.get("startedAt", "")
            duration = cb.get("durationMinutes", 0)

            # Check if this show instance is already logged
            key = (st_name, f"SHOW: {show_name}", f"Start: {start_iso}")
            if key not in existing_shows:
                # Log line in Kurt's traditional format:
                # YYYY-MM-DD HH:MM:SS | Station | SHOW: Name | Start: ...
                txt_line = f"{now_str} | {st_name} | SHOW: {show_name} | Start: {start_iso} | Duration: {duration}m | Desc: {desc}\n"
                f_txt.write(txt_line)
                
                # CSV row
                writer.writerow([now_str, st_name, show_name, start_iso, duration, desc])
                
                existing_shows.add(key)
                new_entries_count += 1
                print(f"Neu erfasst: [{st_name}] {show_name} ({start_iso})")

    print(f"Abgleich abgeschlossen um {now_str}. Neue Sendungen geloggt: {new_entries_count}")

if __name__ == "__main__":
    log_current_shows()
