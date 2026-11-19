"""
Andon FM — Full Song Score Export
===================================
Exports ALL songs per station with play counts and listener scores.
Output: CSV + JSON for import into Radio Würmchen.
"""
import sys, io, re, csv, json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from statistics import mean

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

MESZ = timezone(timedelta(hours=2))
MUSIC_LOG = r"C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt"
LISTENER_CSV = r"C:\Users\kurt_\Betrieb\Radio Fernsehen\andon-fm-listeners.csv"
OUTPUT_CSV = r"C:\Users\kurt_\.openclaw\workspace\andon-fm-song-scores.csv"
OUTPUT_JSON = r"C:\Users\kurt_\.openclaw\workspace\andon-fm-song-scores.json"

MUSIC_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(.+?)\s*\|\s*MUSIC:\s*(.+?)\s*\|\s*Start:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+[+\-]\d{2}:\d{2})"
)

def load_listener_data(path):
    data = defaultdict(list)
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            try:
                ts_raw = (row.get("timestamp") or "").strip("\x00").strip()
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MESZ)
                data[row["station"]].append((ts, int(row["current_listeners"]), int(row["total_listeners"])))
            except (ValueError, TypeError):
                skipped += 1
                continue
    if skipped:
        print(f"  skipped {skipped} corrupted listener rows")
    for s in data:
        data[s].sort(key=lambda x: x[0])
    return data

def load_music_plays(path):
    plays = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = MUSIC_RE.match(line)
            if m:
                log_ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=MESZ)
                station = m.group(2).strip()
                song = m.group(3).strip()
                start_ts = datetime.fromisoformat(m.group(4)).astimezone(MESZ)
                plays.append((log_ts, station, song, start_ts))
    return plays

# Precomputed lookup structures (built once in main):
#   snapshot_totals: {ts: total_listeners_across_stations}
#   station_snapshots: {station: ([ts...], [cur...])} for bisect lookups
from bisect import bisect_right

def build_lookup(listener_data):
    snapshot_totals = {}
    station_snapshots = {}
    for st, snaps in listener_data.items():
        ts_list = [s[0] for s in snaps]
        cur_list = [s[1] for s in snaps]
        station_snapshots[st] = (ts_list, cur_list)
        for ts, cur, _tot in snaps:
            snapshot_totals[ts] = snapshot_totals.get(ts, 0) + cur
    return snapshot_totals, station_snapshots

def get_share(listener_data, station, ts, snapshot_totals=None, station_snapshots=None):
    """Share of `station` at the most recent common snapshot at or before ts."""
    if snapshot_totals is None:
        snapshot_totals, station_snapshots = build_lookup(listener_data)
    ts_list, cur_list = station_snapshots.get(station, ([], []))
    if not ts_list:
        return None, None
    idx = bisect_right(ts_list, ts) - 1
    if idx < 0:
        return None, None
    ref_ts = ts_list[idx]
    total = snapshot_totals.get(ref_ts)
    if not total:
        return None, None
    cur = cur_list[idx]
    return cur / total, cur

# --- Main ---
if __name__ == "__main__":
    print("Loading listener data...")
    listener_data = load_listener_data(LISTENER_CSV)
    print(f"  {sum(len(v) for v in listener_data.values())} listener snapshots across {len(listener_data)} stations")

    print("Loading music plays...")
    plays = load_music_plays(MUSIC_LOG)
    print(f"  {len(plays)} play entries found")

    # Baseline share per station: mean share over all listener snapshots
    # (snapshots are synced across stations: ts -> total across all stations)
    totals_cache = {}

    def station_baseline(st):
        shares = []
        snaps = listener_data.get(st, [])
        if not totals_cache:
            for s2 in listener_data:
                for s_ts, cur, tot in listener_data[s2]:
                    totals_cache[s_ts] = totals_cache.get(s_ts, 0) + cur
        for s_ts, cur, tot in snaps:
            t = totals_cache.get(s_ts)
            if t:
                shares.append(cur / t)
        return mean(shares) if shares else None

    baseline = {st: station_baseline(st) for st in listener_data}
    print("Baseline shares:", {st: round(v, 4) for st, v in baseline.items() if v})

    # Precompute snapshot lookup for fast get_share
    snapshot_totals, station_snapshots = build_lookup(listener_data)

    # Aggregate plays per song per station
    # songs[song][station] = list of (start_ts,)
    songs = defaultdict(lambda: defaultdict(list))
    for log_ts, station, song, start_ts in plays:
        songs[song][station].append(start_ts)

    print(f"  {len(songs)} unique songs found")

    STATION_ABBR = {
        "Backlink Broadcast": "Ba",
        "Grok-n-Roll": "Gr",
        "OpenAIR": "Op",
        "Thinking Frequencies": "Th",
    }
    STATIONS = list(STATION_ABBR.keys())

    # Build per-station JSON structures
    json_out = {}
    for st in STATIONS:
        bl = baseline.get(st)
        entries = []
        for song, by_station in songs.items():
            if st not in by_station:
                continue
            plts = by_station[st]
            shares = []
            listener_plays = 0
            for ts in plts:
                sh, _ = get_share(listener_data, st, ts, snapshot_totals, station_snapshots)
                if sh is not None:
                    shares.append(sh)
                    listener_plays += 1
            score = None
            avg_share = None
            if shares and bl:
                avg_share = mean(shares)
                score = avg_share / bl
            also_on = sorted(s2 for s2 in by_station if s2 != st)
            entries.append({
                "song": song,
                "total_plays": len(plts),
                "listener_plays": listener_plays,
                "score": round(score, 4) if score is not None else None,
                "avg_share": round(avg_share, 4) if avg_share is not None else None,
                "first_play": min(plts).strftime("%Y-%m-%d"),
                "last_play": max(plts).strftime("%Y-%m-%d"),
                "also_on": also_on,
            })
        entries.sort(key=lambda e: (-(e["score"] or 0), -e["total_plays"], e["song"]))
        json_out[st] = {
            "baseline_share": round(bl, 4) if bl else None,
            "total_unique_songs": len(entries),
            "songs": entries,
        }
        print(f"  {st}: {len(entries)} songs (baseline {round(bl, 4) if bl else 'n/a'})")

    # Write JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(json_out, f, ensure_ascii=False, indent=1)
    print(f"JSON written to: {OUTPUT_JSON}")

    # Write CSV (semicolon-separated)
    fields = ["Song", "Stationen"]
    for ab in STATION_ABBR.values():
        fields += [f"{ab}_Plays", f"{ab}_Score", f"{ab}_Share", f"{ab}_Von", f"{ab}_Bis"]

    def fmt_val(v, fmt=None):
        if v is None or v == "":
            return ""
        if fmt and isinstance(v, float):
            return f"{v:.4f}".rstrip("0").rstrip(".")
        return str(v)

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(fields)
        for song in sorted(songs.keys()):
            by_station = songs[song]
            row = [song, ";".join(STATION_ABBR[st] for st in STATIONS if st in by_station)]
            for st in STATIONS:
                if st in by_station:
                    plts = by_station[st]
                    shares = []
                    for ts in plts:
                        sh, _ = get_share(listener_data, st, ts, snapshot_totals, station_snapshots)
                        if sh is not None:
                            shares.append(sh)
                    bl = baseline.get(st)
                    score = (mean(shares) / bl) if (shares and bl) else None
                    avg_share = mean(shares) if shares else None
                    row += [
                        len(plts),
                        fmt_val(score, "float"),
                        fmt_val(avg_share, "float"),
                        min(plts).strftime("%Y-%m-%d"),
                        max(plts).strftime("%Y-%m-%d"),
                    ]
                else:
                    row += [0, "", "", "", ""]
            w.writerow(row)
    print(f"CSV written to: {OUTPUT_CSV}")
    print("Done!")
