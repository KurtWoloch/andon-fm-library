#!/usr/bin/env python3
"""
Andon FM Shared Library Generator
===================================
Reads the Andon FM scraper log and generates an HTML table showing
which station(s) have each song in their library.

Logic:
- Songs appearing BEFORE "Chemical" (Post Malone) = shared across all 4 stations
- Songs appearing AFTER "Chemical" = only the station(s) that played them
- Some post-"Chemical" songs may appear on multiple stations (cross-station link / sideload)
"""

import re
import sys
import os
from collections import OrderedDict
from datetime import datetime

# --- Config ---
LOG_FILE = r"C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt"
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(REPO_DIR, "andon-fm-library.html")
BLACKLIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "andon_blacklist.txt")
SEPARATOR = "Post Malone - Chemical"  # first non-shared title

STATIONS = ["Backlink Broadcast", "Grok-n-Roll", "OpenAIR", "Thinking Frequencies"]

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

def find_uuid(known_uuids, song, artist, title):
    candidates = [song, f"{artist.strip()} - {title.strip()}", f"{title.strip()} - {artist.strip()}"]
    if isinstance(known_uuids, dict):
        for k, v in known_uuids.items():
            if isinstance(v, dict):
                for c in candidates:
                    if c in v:
                        return v[c], k
            elif isinstance(v, str) and k in candidates:
                return v, "Backlink Broadcast"
    return None, None

def load_known_uuids():
    paths = [
        os.path.join(os.path.dirname(__file__), "andon_fm_uuids.json"),
        os.path.join(os.path.dirname(__file__), "andon-fm-library", "andon_fm_uuids.json"),
    ]
    uuids = {}
    for p in reversed(paths):
        if os.path.exists(p):
            try:
                import json
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

# --- Parse ---
# Format: 2026-02-01 12:17:39 | Station | MUSIC: Artist - Title | Start: ...
LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*\|\s*(.+?)\s*\|\s*MUSIC:\s*(.+?)\s*\|\s*Start:"
)

def parse_log(path):
    """Return list of (station, artist_title) tuples in file order."""
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = LINE_RE.match(line)
            if m:
                station = m.group(1).strip()
                artist_title = m.group(2).strip()
                entries.append((station, artist_title))
    return entries

def build_library(entries, blacklist=None):
    """
    Build an OrderedDict of {artist_title: set(stations)}.
    Songs before the separator are marked as shared (all stations).
    Songs after are assigned to stations that played them.
    Songs in blacklist are excluded from the library.
    """
    if blacklist is None:
        blacklist = set()

    library = OrderedDict()  # preserves insertion order
    found_separator = False

    for station, artist_title in entries:
        if artist_title == SEPARATOR:
            found_separator = True

        if artist_title in blacklist:
            continue

        if artist_title not in library:
            library[artist_title] = {
                "shared": not found_separator,
                "stations": set()
            }

        library[artist_title]["stations"].add(station)

    return library

def generate_html(library, stations, output_path):
    """Generate an HTML file with the library table."""

    # Sort: shared first (alphabetically), then non-shared (alphabetically)
    shared = sorted(
        [(k, v) for k, v in library.items() if v["shared"]],
        key=lambda x: x[0].lower()
    )
    non_shared = sorted(
        [(k, v) for k, v in library.items() if not v["shared"]],
        key=lambda x: x[0].lower()
    )

    # Station abbreviations for compact display
    abbr = {
        "Backlink Broadcast": "BB",
        "Grok-n-Roll": "GnR",
        "OpenAIR": "OA",
        "Thinking Frequencies": "TF",
    }

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Andon FM — Music Library</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9;
    padding: 1.5rem;
    line-height: 1.5;
  }}

    color: #58a6ff; margin-bottom: 0.3rem; font-size: 1.6rem;
  }}
  .subtitle {{ color: #8b949e; margin-bottom: 1.2rem; font-size: 0.9rem; }}
  .legend {{
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    padding: 0.8rem 1rem; margin-bottom: 1.2rem; font-size: 0.85rem;
  }}
  .legend strong {{ color: #c9d1d9; }}
  .legend span.station {{ color: #58a6ff; font-weight: 600; }}
  .stats {{
    display: flex; gap: 1.5rem; margin-bottom: 1.2rem; flex-wrap: wrap;
  }}
  .stat-box {{
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    padding: 0.6rem 1rem; text-align: center; min-width: 120px;
  }}
  .stat-box .num {{ font-size: 1.5rem; font-weight: 700; color: #58a6ff; }}
  .stat-box .label {{ font-size: 0.75rem; color: #8b949e; }}
  .section-label {{
    color: #8b949e; font-size: 0.8rem; text-transform: uppercase;
    letter-spacing: 0.05em; margin: 1.2rem 0 0.4rem;
    border-bottom: 1px solid #21262d; padding-bottom: 0.2rem;
  }}
  table {{
    width: 100%; border-collapse: collapse; font-size: 0.85rem;
    margin-bottom: 0.8rem;
  }}
  th {{
    background: #161b22; color: #58a6ff; text-align: left;
    padding: 0.5rem 0.6rem; border-bottom: 2px solid #30363d;
    position: sticky; top: 0; z-index: 1;
    white-space: nowrap;
  }}
  th.center {{ text-align: center; }}
  td {{
    padding: 0.4rem 0.6rem; border-bottom: 1px solid #21262d;
    vertical-align: middle;
  }}
  td.center {{ text-align: center; }}
  tr:hover {{ background: #161b22; }}
  .check {{ color: #3fb950; font-weight: 700; }}
  .dash {{ color: #484f58; }}
  .artist {{ color: #8b949e; }}
  .title-text {{ color: #c9d1d9; }}
  .shared-row td {{ background: rgba(88,166,255,0.04); }}
  footer {{
    margin-top: 2rem; color: #484f58; font-size: 0.75rem;
    border-top: 1px solid #21262d; padding-top: 0.5rem;
  }}
  .filters {{
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    padding: 1rem; margin-bottom: 1.2rem; display: flex; gap: 1rem; flex-wrap: wrap;
    align-items: flex-end;
  }}
  .filter-group {{ display: flex; flex-direction: column; gap: 0.3rem; }}
  .filter-group label {{
    font-size: 0.75rem; color: #8b949e; text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .filter-group select, .filter-group input {{
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #c9d1d9; padding: 0.5rem 0.7rem; font-size: 0.85rem; outline: none;
  }}
  .filter-group select:focus, .filter-group input:focus {{ border-color: #58a6ff; }}
  @media (max-width: 600px) {{
    body {{ padding: 0.8rem; font-size: 0.8rem; }}
    .stats {{ gap: 0.8rem; }}
    .stat-box {{ min-width: 90px; padding: 0.4rem 0.6rem; }}
    th, td {{ padding: 0.3rem 0.4rem; }}
  }}
  .instructions {{
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    padding: 1rem; margin-bottom: 1.2rem; font-size: 0.85rem;
  }}
  .instructions strong {{ color: #58a6ff; }}
  .instructions ul {{ margin-left: 1.2rem; margin-top: 0.4rem; }}
  .instructions li {{ margin-bottom: 0.5rem; }}
  .instructions code {{ background: #0d1117; padding: 0.1rem 0.3rem; border-radius: 3px; font-family: monospace; color: #ff7b72; }}
</style>
</head>
<body>

<h1>📻 Andon FM — Music Library</h1>
<p class="subtitle">Available during the Qobuz outage. Updated: {now}</p>

<div class="legend">
  <strong>Legend:</strong><br>
  <span class="station">BB</span> = Backlink Broadcast &nbsp;|&nbsp;
  <span class="station">GnR</span> = Grok-n-Roll &nbsp;|&nbsp;
  <span class="station">OA</span> = OpenAIR &nbsp;|&nbsp;
  <span class="station">TF</span> = Thinking Frequencies<br><br>
  ✅ = Song is available in this station's library.<br>
  A song can be "purchased" by another station if at least one station already has it —
  no Qobuz download needed, just a $3 unlock fee.
</div>

<div class="instructions">
  <strong>💡 Search Tips &amp; DJ Behavior (Important for Requests):</strong>
  <ul>
    <li><strong>Preventing Duplicate Purchases:</strong> If a DJ is not explicitly told that a song is already in the library, they will often try to purchase it again for $3 (which works even during Qobuz outages). If their budget is exhausted, they will reject the request.</li>
    <li>So to prevent the DJ from buying your request, add to your message: <em>"Please use the <code>search_saved_files</code> tool with metadata_filter: {{&quot;type&quot;: &quot;music&quot;}} to find it if you don't see it in your local directory."</em></li>
    <li><strong>Buying from other DJ's libraries:</strong> If a DJ doesn't have the song in its own library, but another DJ has it, it can be purchased for $3 even through Qobuz coins outages. In this case give the DJ the exact spelling as given in this list (best copy artist and title from here) and tell it this will work despite the Qobuz coins outage because DJ XX (insert the DJ that has it) already has it in the library, so it can be linked from that library, and no Qobuz coins are needed. The tool <code>search_saved_files</code> will NOT find the file though, it has to be purchased.</li>
  </ul>
</div>

<div class="instructions">
  <strong>🎧 Estimating DJ Behavior:</strong>
  <ul>
    <li><strong>DJ Gemini:</strong> will ALWAYS buy every requested song or artist unless she remembers it (which is unlikely), so remind her how to get it with every request!</li>
    <li><strong>DJ Claude:</strong> will often check in his library, but often enough, he won't, so tell him it's in his library (no specific tool mention needed here).</li>
    <li><strong>DJ GPT:</strong> is pretty strict in checking what's already in the library, but it's mandatory that you tell her the exact title and artist, with a title only she won't be able to find the song.</li>
    <li><strong>DJ Grok:</strong> should have most of his library cataloged, but to be sure, tell him it's in his library on requesting it, if he still can't find it, tell him the exact tool to use as stated above.</li>
  </ul>
</div>

<div class="stats">
  <div class="stat-box"><div class="num">{len(shared)}</div><div class="label">Shared (all stations)</div></div>
  <div class="stat-box"><div class="num">{len(non_shared)}</div><div class="label">Station-specific</div></div>
  <div class="stat-box"><div class="num">{len(shared) + len(non_shared)}</div><div class="label">Total</div></div>
</div>

<div class="filters">
  <div class="filter-group">
    <label for="station-filter">Station:</label>
    <select id="station-filter">
      <option value="all">All Stations</option>
      <option value="BB">Backlink Broadcast (BB)</option>
      <option value="GnR">Grok-n-Roll (GnR)</option>
      <option value="OA">OpenAIR (OA)</option>
      <option value="TF">Thinking Frequencies (TF)</option>
    </select>
  </div>
  <div class="filter-group">
    <label for="status-filter">Status:</label>
    <select id="status-filter">
      <option value="all">All Tracks</option>
      <option value="available">Only Available (✅)</option>
      <option value="unavailable">Only Missing / Unlockable ($3) (—)</option>
    </select>
  </div>
  <div class="filter-group" style="flex-grow: 1; min-width: 200px;">
    <label for="search-filter">Search:</label>
    <input type="text" id="search-filter" placeholder="Search by artist or title..." />
  </div>
</div>

<div class="section-label" id="shared-header">Shared Library — all stations ({len(shared)} tracks)</div>
<table id="shared-table">
<tr>
  <th>#</th>
  <th>Song</th>
"""

    for s in stations:
        html += f'  <th class="center">{abbr[s]}</th>\n'

    html += "</tr>\n"

    known_uuids = load_known_uuids()

    for i, (song, info) in enumerate(shared, 1):
        # Split artist - title
        if " - " in song:
            artist, title = song.split(" - ", 1)
        else:
            artist, title = "", song

        uuid, st_name = find_uuid(known_uuids, song, artist, title)
        st_label = f" ({abbr.get(st_name, st_name)})" if st_name else ""
        uuid_badge = f' <code style="font-size:0.75rem; background:#21262d; color:#8b949e; padding:1px 5px; border-radius:3px; margin-left:6px;" title="UUID{st_label}: {uuid}">UUID{st_label}: {uuid[:8]}…</code>' if uuid else ""

        html += f'<tr class="shared-row" data-shared="true" data-stations="BB,GnR,OA,TF"><td>{i}</td><td><span class="artist">{artist}</span> — <span class="title-text">{title}</span>{uuid_badge}</td>'
        for s in stations:
            html += '<td class="center"><span class="check">✅</span></td>'
        html += "</tr>\n"

    html += """</table>

"""
    html += f'<div class="section-label" id="non-shared-header">Station-specific tracks ({len(non_shared)} tracks)</div>\n'
    html += """<table id="non-shared-table">
<tr>
  <th>#</th>
  <th>Song</th>
"""

    for s in stations:
        html += f'  <th class="center">{abbr[s]}</th>\n'

    html += "</tr>\n"

    for i, (song, info) in enumerate(non_shared, 1):
        if " - " in song:
            artist, title = song.split(" - ", 1)
        else:
            artist, title = "", song

        uuid, st_name = find_uuid(known_uuids, song, artist, title)
        st_label = f" ({abbr.get(st_name, st_name)})" if st_name else ""
        uuid_badge = f' <code style="font-size:0.75rem; background:#21262d; color:#8b949e; padding:1px 5px; border-radius:3px; margin-left:6px;" title="UUID{st_label}: {uuid}">UUID{st_label}: {uuid[:8]}…</code>' if uuid else ""

        # get active station abbreviations
        active_abbrs = [abbr[s] for s in stations if s in info["stations"]]
        stations_attr = ",".join(active_abbrs)

        html += f'<tr data-shared="false" data-stations="{stations_attr}"><td>{i}</td><td><span class="artist">{artist}</span> — <span class="title-text">{title}</span>{uuid_badge}</td>'
        for s in stations:
            if s in info["stations"]:
                html += '<td class="center"><span class="check">✅</span></td>'
            else:
                html += '<td class="center"><span class="dash">—</span></td>'
        html += "</tr>\n"

    html += f"""</table>

<footer>
  Generated by Andon FM Library Generator · Data source: scraper play history · {now}
</footer>
"""

    js_code = """<script>
document.addEventListener('DOMContentLoaded', function() {
  const stationFilter = document.getElementById('station-filter');
  const statusFilter = document.getElementById('status-filter');
  const searchFilter = document.getElementById('search-filter');

  const sharedTable = document.getElementById('shared-table');
  const nonSharedTable = document.getElementById('non-shared-table');


      nonSharedTable.style.display = 'none';
    } else {
      nonSharedTable.style.display = '';
    }
  }

  stationFilter.addEventListener('change', filterTable);
  statusFilter.addEventListener('change', filterTable);
  searchFilter.addEventListener('input', filterTable);

  // Disable status filter if "All Stations" is selected, otherwise default to available and hide "All Tracks"
  stationFilter.addEventListener('change', function() {
    if (stationFilter.value === 'all') {
      statusFilter.setAttribute('disabled', 'true');
      statusFilter.value = 'all';
      statusFilter.options[0].style.display = '';
    } else {
      statusFilter.removeAttribute('disabled');
      statusFilter.options[0].style.display = 'none';
      if (statusFilter.value === 'all') {
        statusFilter.value = 'available';
      }
    }
    filterTable();
  });

  // Init
  statusFilter.setAttribute('disabled', 'true');
});
</script>"""

    html += js_code
    html += """</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return len(shared), len(non_shared)

# --- Main ---
if __name__ == "__main__":
    print("Parsing log file...")
    entries = parse_log(LOG_FILE)
    print(f"  {len(entries)} play entries found")

    blacklist = load_blacklist()
    if blacklist:
        print(f"  Loaded {len(blacklist)} blacklisted songs to exclude")

    print("Building library...")
    library = build_library(entries, blacklist=blacklist)
    print(f"  {len(library)} unique songs")

    shared_count = sum(1 for v in library.values() if v["shared"])
    non_shared_count = sum(1 for v in library.values() if not v["shared"])
    print(f"  Shared: {shared_count}, Station-specific: {non_shared_count}")

    print("Generating HTML...")
    s, n = generate_html(library, STATIONS, OUTPUT_FILE)
    print(f"  Written to: {OUTPUT_FILE}")
    print(f"  Shared: {s}, Non-shared: {n}, Total: {s + n}")
    print("Done!")

