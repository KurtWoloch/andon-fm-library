"""
Andon FM — Context Window Analysis
====================================
Analyzes play history to categorize tracks by "freshness":
  - HOT: last played <24h ago (still in rotation / context window)
  - ARCHIVE: last played >24h ago (from the back catalog)
  - NEW: never played before on this station

Usage: py andon_context_analysis.py [station_name] [hours]
"""
import sys, io, re
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LOG_FILE = r"C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt"
MESZ = timezone(timedelta(hours=2))

# Parse log file
LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\|\s*(.+?)\s*\|\s*MUSIC:\s*(.+?)\s*\|\s*Start:"
)

def parse_log(path):
    """Return list of (timestamp, station, artist_title) tuples."""
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = LINE_RE.match(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=MESZ)
                station = m.group(2).strip()
                artist_title = m.group(3).strip()
                entries.append((ts, station, artist_title))
    return entries

def analyze(entries, target_station=None, window_hours=24):
    """
    For each station (or target_station), analyze the last `window_hours` of plays.
    Classify each play as HOT/ARCHIVE/NEW based on the previous play of the same song.
    """
    # Group by station
    by_station = defaultdict(list)
    for ts, station, song in entries:
        by_station[station].append((ts, song))

    stations = [target_station] if target_station else sorted(by_station.keys())
    now = entries[-1][0]  # latest timestamp in the data
    cutoff = now - timedelta(hours=window_hours)

    print(f"{'=' * 70}")
    print(f"ANDON FM — Context Window Analysis ({window_hours}h)")
    print(f"Data range: {entries[0][0].strftime('%Y-%m-%d %H:%M')} → {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Cutoff (last {window_hours}h): {cutoff.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 70}")

    for station in stations:
        plays = by_station.get(station, [])
        if not plays:
            print(f"\n📻 {station}: No data")
            continue

        # Build last-play lookup: song → timestamp of most recent play BEFORE the window
        # First pass: scan all plays up to cutoff
        last_play_before = {}  # song → last play timestamp (before window)
        last_play_in = {}      # song → last play timestamp (in window, for chaining)
        
        # Track all plays of each song for proper context-window detection
        all_plays = defaultdict(list)  # song → [ts1, ts2, ...]
        for ts, song in plays:
            all_plays[song].append(ts)

        # For plays in the window, classify each one
        window_plays = [(ts, song) for ts, song in plays if ts >= cutoff]
        
        if not window_plays:
            print(f"\n📻 {station}: No plays in the last {window_hours}h")
            continue

        hot = []       # played within 24h of previous play
        archive = []   # played >24h after previous play
        new_songs = [] # never played before on this station

        for ts, song in window_plays:
            # Find the previous play of this song (before this timestamp)
            song_plays = all_plays[song]
            prev_play = None
            for p_ts in reversed(song_plays):
                if p_ts < ts:
                    prev_play = p_ts
                    break
            
            if prev_play is None:
                new_songs.append((ts, song))
            elif (ts - prev_play) < timedelta(hours=window_hours):
                hot.append((ts, song, prev_play))
            else:
                archive.append((ts, song, prev_play))

        total = len(window_plays)
        hot_count = len(hot)
        archive_count = len(archive)
        new_count = len(new_songs)
        unique_songs = len(set(song for _, song in window_plays))

        print(f"\n{'─' * 70}")
        print(f"📻 {station}")
        print(f"   Plays in window: {total}  |  Unique songs: {unique_songs}")
        print(f"   🔴 HOT (<24h repeat):     {hot_count:4d}  ({hot_count/total*100:5.1f}%)")
        print(f"   🟡 ARCHIVE (>24h repeat):  {archive_count:4d}  ({archive_count/total*100:5.1f}%)")
        print(f"   🟢 NEW (first play ever):  {new_count:4d}  ({new_count/total*100:5.1f}%)")
        print(f"{'─' * 70}")

        # Show some examples from each category
        if hot:
            print(f"   🔴 Examples HOT (last 10):")
            seen = set()
            count = 0
            for ts, song, prev in sorted(hot, key=lambda x: x[0], reverse=True):
                if song in seen:
                    continue
                seen.add(song)
                gap = ts - prev
                gap_h = gap.total_seconds() / 3600
                print(f"      {ts.strftime('%H:%M')} {song}  (prev: {gap_h:.1f}h ago)")
                count += 1
                if count >= 10:
                    break

        if archive:
            print(f"   🟡 Examples ARCHIVE (last 10):")
            seen = set()
            count = 0
            for ts, song, prev in sorted(archive, key=lambda x: x[0], reverse=True):
                if song in seen:
                    continue
                seen.add(song)
                gap = ts - prev
                gap_d = gap.total_seconds() / 86400
                print(f"      {ts.strftime('%H:%M')} {song}  (prev: {gap_d:.1f}d ago)")
                count += 1
                if count >= 10:
                    break

        if new_songs:
            print(f"   🟢 NEW songs (last 10):")
            seen = set()
            count = 0
            for ts, song in sorted(new_songs, key=lambda x: x[0], reverse=True):
                if song in seen:
                    continue
                seen.add(song)
                print(f"      {ts.strftime('%H:%M')} {song}")
                count += 1
                if count >= 10:
                    break

        # Repeat analysis: songs played 3+ times in the window
        song_count = defaultdict(int)
        for _, song in window_plays:
            song_count[song] += 1
        heavy_repeats = [(s, c) for s, c in song_count.items() if c >= 3]
        if heavy_repeats:
            print(f"   🔁 Heavy repeats (3+ plays in {window_hours}h):")
            for song, count in sorted(heavy_repeats, key=lambda x: -x[1])[:10]:
                print(f"      {count}× {song}")

    # Cross-station summary
    if not target_station:
        print(f"\n{'=' * 70}")
        print("CROSS-STATION SUMMARY")
        print(f"{'=' * 70}")
        for station in stations:
            plays = by_station.get(station, [])
            window_plays = [(ts, song) for ts, song in plays if ts >= cutoff]
            if not window_plays:
                continue
            unique = len(set(song for _, song in window_plays))
            print(f"  {station:25s}  {len(window_plays):4d} plays  {unique:4d} unique  ({len(window_plays)/unique:.1f}× avg repeat)")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    
    print("Parsing log file...")
    entries = parse_log(LOG_FILE)
    print(f"  {len(entries)} entries loaded\n")
    
    analyze(entries, target_station=target, window_hours=hours)
