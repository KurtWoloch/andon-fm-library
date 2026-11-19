import re
import os
import json
import csv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Config
LOG_FILE = r"C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt"
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLACKLIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "andon_blacklist.txt")
SEPARATOR = "Post Malone - Chemical"

# Timezone Config for Vienna-to-UTC conversion
VIENNA_TZ = ZoneInfo("Europe/Vienna")
UTC_TZ = ZoneInfo("UTC")

UUID_FILE = os.path.join(REPO_DIR, "andon_fm_uuids.json")

def load_blacklist(path=BLACKLIST_FILE):
    """Load blocked song titles from blacklist file."""
    blocked = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    blocked.add(line)
    return blocked

def load_known_uuids():
    paths = [
        os.path.join(os.path.dirname(__file__), "andon_fm_uuids.json"),
        os.path.join(REPO_DIR, "andon_fm_uuids.json"),
    ]
    uuids = {}
    for p in reversed(paths):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if isinstance(v, dict):
                            if k not in uuids:
                                uuids[k] = {}
                            uuids[k].update(v)
                        else:
                            uuids[k] = v
            except Exception as e:
                print(f"Warning loading UUID file from {p}: {e}")
    return uuids

# Map of stations to generate exports for
# Format: { "Station Playout Name": { "abbr": "file_prefix", "description": "Display Name" } }
ACTIVE_STATIONS = {
    "Backlink Broadcast": {
        "abbr": "bb",
        "name": "Backlink Broadcast"
    },
    "OpenAIR": {
        "abbr": "oa",
        "name": "OpenAIR"
    },
    "Thinking Frequencies": {
        "abbr": "tf",
        "name": "Thinking Frequencies"
    },
    "Grok-n-Roll": {
        "abbr": "gnr",
        "name": "Grok'n Roll"
    }
}

LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(.+?)\s*\|\s*MUSIC:\s*(.+?)\s*\|\s*Start:"
)

def generate_libraries():
    print(f"Reading log file: {LOG_FILE}")
    if not os.path.exists(LOG_FILE):
        print(f"Error: Log file not found at {LOG_FILE}")
        return

    entries = []
    max_dt = datetime.min
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            m = LINE_RE.match(line)
            if m:
                dt_str = m.group(1).strip()
                station = m.group(2).strip()
                song = m.group(3).strip()
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    if dt > max_dt:
                        max_dt = dt
                except ValueError:
                    dt = None
                entries.append((dt_str, dt, station, song))

    print(f"Total entries parsed: {len(entries)}")
    if not entries:
        print("No entries found.")
        return

    blacklist = load_blacklist()
    if blacklist:
        print(f"Loaded {len(blacklist)} blacklisted songs to exclude.")

    # Use max_dt in log or datetime.now() as reference for 30 days and 24 hours
    ref_now = max(max_dt, datetime.now())
    thirty_days_ago = ref_now - timedelta(days=30)
    twenty_four_hours_ago = ref_now - timedelta(hours=24)
    print(f"Reference 'now' for stats: {ref_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"30 days ago threshold: {thirty_days_ago.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"24 hours ago threshold: {twenty_four_hours_ago.strftime('%Y-%m-%d %H:%M:%S')}")

    # Determine shared status based on first appearance relative to SEPARATOR
    found_separator = False
    library_meta = {}  # {song: {"shared": bool, "stations": set()}}

    for dt_str, dt, station, song in entries:
        if song == SEPARATOR:
            found_separator = True
        
        if song in blacklist:
            continue

        if song not in library_meta:
            library_meta[song] = {
                "shared": not found_separator,
                "stations": set()
            }
        library_meta[song]["stations"].add(station)

    # Generate files for each active station
    for station_name, config in ACTIVE_STATIONS.items():
        abbr = config["abbr"]
        print(f"\nProcessing exports for: {station_name} ({abbr.upper()})...")

        # Compile station-specific plays
        plays_by_song = {} # {song: [datetime_objects]}
        for dt_str, dt, station, song in entries:
            if station == station_name:
                if song not in plays_by_song:
                    plays_by_song[song] = []
                if dt:
                    plays_by_song[song].append(dt)

        # Filter songs that are either shared OR played by this station
        accessible_songs = []
        for song, meta in library_meta.items():
            is_shared = meta["shared"]
            has_play = (station_name in meta["stations"])
            
            if is_shared or has_play:
                accessible_songs.append((song, is_shared))

        # Sort: Shared first, then non-shared, alphabetically by Artist, then Title
        def get_sort_key(item):
            song_name, is_shared = item
            if " - " in song_name:
                artist, title = song_name.split(" - ", 1)
            else:
                artist, title = "", song_name
            return (not is_shared, artist.lower().strip(), title.lower().strip())

        accessible_songs.sort(key=get_sort_key)

        # Station-specific UUID lookup map
        known_uuids = load_known_uuids()
        station_uuids = (
            known_uuids.get(station_name) or
            known_uuids.get(abbr) or
            {}
        )
        if not station_uuids and (station_name == "Backlink Broadcast" or abbr == "bb"):
            if any(isinstance(v, str) for v in known_uuids.values()):
                station_uuids = known_uuids

        export_data = []
        for song, is_shared in accessible_songs:
            if " - " in song:
                artist, title = song.split(" - ", 1)
            else:
                artist, title = "", song

            plays = plays_by_song.get(song, [])
            play_count = len(plays)
            
            # Calculate plays in the last 30 days and 24 hours
            play_count_30d = sum(1 for p in plays if p >= thirty_days_ago)
            play_count_24h = sum(1 for p in plays if p >= twenty_four_hours_ago)
            
            if plays:
                last_played_dt = max(plays)
                # Convert Vienna local time (logs) to UTC
                dt_local = last_played_dt.replace(tzinfo=VIENNA_TZ)
                dt_utc = dt_local.astimezone(UTC_TZ)
                
                last_played_utc_str = dt_utc.strftime("%Y-%m-%d %H:%M:%SZ")
                
                tzname = dt_local.strftime("%Z")
                tz_label = "MESZ" if tzname == "CEST" else "MEZ" if tzname == "CET" else tzname
                last_played_vienna_str = f"{dt_local.strftime('%Y-%m-%d %H:%M:%S')} {tz_label}"
            else:
                last_played_utc_str = "Never"
                last_played_vienna_str = "Never"

            # Added source/confidence/file_id as requested by DJ GPT
            source = "Shared Library" if is_shared else f"Scraper Logs ({abbr.upper()} Play History)"

            file_id = (
                station_uuids.get(song) or
                station_uuids.get(f"{artist.strip()} - {title.strip()}") or
                station_uuids.get(f"{title.strip()} - {artist.strip()}")
            )

            item_dict = {
                "artist": artist.strip(),
                "title": title.strip(),
                "type": "Shared" if is_shared else "Station-Specific",
                "play_count_total": play_count,
                "play_count_30d": play_count_30d,
                "play_count_24h": play_count_24h,
                "last_played": last_played_utc_str,
                "last_played_vienna": last_played_vienna_str,
                "file_id": file_id or "",
                "source": source
            }

            export_data.append(item_dict)

        has_any_file_id = any(item.get("file_id") for item in export_data)
        if not has_any_file_id:
            for item in export_data:
                item.pop("file_id", None)

        # Define output paths
        json_output = os.path.join(REPO_DIR, f"{abbr}_only.json")
        csv_output = os.path.join(REPO_DIR, f"{abbr}_only.csv")
        html_output = os.path.join(REPO_DIR, f"{abbr}_only.html")
        unplayed_output = os.path.join(REPO_DIR, f"{abbr}_longest_unplayed_top50.json")
        least_output = os.path.join(REPO_DIR, f"{abbr}_least_played_top50.json")

        # Write main JSON
        print(f"  - Writing JSON to: {json_output}")
        with open(json_output, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        # Write main CSV
        print(f"  - Writing CSV to: {csv_output}")
        csv_headers = ["Artist", "Title", "Type", "Play Count Total", "Play Count 30D", "Play Count 24H", "Last Played (UTC)", "Last Played (Vienna)"]
        if has_any_file_id:
            csv_headers.append("File ID")
        csv_headers.append("Source")

        with open(csv_output, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(csv_headers)
            for item in export_data:
                row = [
                    item["artist"],
                    item["title"],
                    item["type"],
                    item["play_count_total"],
                    item["play_count_30d"],
                    item["play_count_24h"],
                    item["last_played"],
                    item.get("last_played_vienna", ""),
                ]
                if has_any_file_id:
                    row.append(item.get("file_id") or "")
                row.append(item["source"])
                writer.writerow(row)

        # Write main HTML
        json2table_path = os.path.join(os.path.dirname(__file__), "kontensystem", "tools", "json2table.py")
        if os.path.exists(json2table_path):
            print(f"  - Generating HTML table to: {html_output}")
            import sys
            import subprocess
            subprocess.run([sys.executable, json2table_path, json_output, "-o", html_output], capture_output=True)

        # Generate Longest Unplayed Top 50
        longest_unplayed = sorted(
            export_data,
            key=lambda x: (x["last_played"] != "Never", x["last_played"], x["artist"].lower().strip(), x["title"].lower().strip())
        )[:50]
        
        print(f"  - Writing Longest Unplayed to: {unplayed_output}")
        with open(unplayed_output, "w", encoding="utf-8") as f:
            json.dump(longest_unplayed, f, indent=2, ensure_ascii=False)

        # Generate Least Played Top 50
        least_played = sorted(
            export_data,
            key=lambda x: (x["play_count_total"], x["last_played"] != "Never", x["last_played"], x["artist"].lower().strip(), x["title"].lower().strip())
        )[:50]
        
        print(f"  - Writing Least Played to: {least_output}")
        with open(least_output, "w", encoding="utf-8") as f:
            json.dump(least_played, f, indent=2, ensure_ascii=False)

        # Generate Missing / Unowned Station-Specific Tracks CSV (tracks owned by other stations)
        missing_csv_output = os.path.join(REPO_DIR, f"{abbr}_missing.csv")
        missing_tracks = []
        for song, meta in library_meta.items():
            if not meta["shared"] and station_name not in meta["stations"]:
                if " - " in song:
                    artist, title = song.split(" - ", 1)
                else:
                    artist, title = "", song
                missing_tracks.append((artist.strip(), title.strip()))

        missing_tracks.sort(key=lambda x: (x[0].lower(), x[1].lower()))

        print(f"  - Writing Missing Tracks CSV ({len(missing_tracks)} tracks) to: {missing_csv_output}")
        with open(missing_csv_output, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["artist", "title"])
            for artist, title in missing_tracks:
                writer.writerow([artist, title])

        print(f"  - Success! Exported {len(export_data)} songs (and {len(missing_tracks)} missing).")

    print("\nAll stations processed successfully!")

if __name__ == "__main__":
    generate_libraries()

