# -*- coding: utf-8 -*-
"""Globaler, artist-unabhaengiger Scan: neue Namen ab 2026-09-09 vs. alte Namen davor."""
import sys, io, re
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LOG = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt'
NEW_FROM = '2026-09-09'

text = open(LOG, 'rb').read().decode('utf-8-sig')
LINE = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \| ([^|]+) \| MUSIC: (.+?) \| Start: (.+)$')

recs = []
for line in text.splitlines():
    m = LINE.match(line.strip())
    if not m:
        continue
    date, tm, sender, payload, start = m.groups()
    recs.append((date, sender.strip(), payload.strip()))

def norm(s):
    return re.sub(r'\s+', ' ', s).strip().casefold()

first = {}
count = defaultdict(int)
for date, sender, payload in recs:
    k = norm(payload)
    count[k] += 1
    if k not in first or date < first[k]:
        first[k] = date

raw_of = {}
for date, sender, payload in recs:
    raw_of.setdefault(norm(payload), payload)

pre = [k for k, d in first.items() if d < NEW_FROM]
new = [k for k, d in first.items() if d >= NEW_FROM]
print(f"Distinct Payloads total: {len(first)}")
print(f"  davon bekannt VOR {NEW_FROM}: {len(pre)}")
print(f"  davon NEU ab {NEW_FROM}: {len(new)}")
print(f"Gesamtzeilen mit neuem Payload ab {NEW_FROM}: {sum(count[k] for k in new)}")

# Index: alle Praefixe alter Namen (>=12 Zeichen) -> alter Name
pref_index = defaultdict(list)
for k in pre:
    for L in range(12, len(k) + 1):
        pref_index[k[:L]].append(k)

print("\n=== Treffer: neuer Payload, dessen Kurzform schon VOR dem Cutoff lief ===")
hits = 0
for k in new:
    if len(k) < 13:
        continue
    for L in range(len(k) - 1, 11, -1):
        if k[:L] in pref_index:
            olds = pref_index[k[:L]]
            print(f"  NEU  ({first[k]}): {raw_of[k]!r}")
            for o in olds[:3]:
                print(f"       ALT ({first[o]}, {count[o]}x): {raw_of[o]!r}")
            hits += 1
            break
print(f"  Treffer: {hits}")

# Zusatz: exakte Substring-Treffer (nicht nur Praefix) mit Laenge >= 15
print("\n=== Treffer: exakter Substring (Laenge >=15) im neuen Payload ===")
hits2 = 0
for k in new:
    if len(k) < 16:
        continue
    found = None
    for o in pre:
        if len(o) >= 15 and len(o) < len(k) and o in k:
            found = o
            break
    if found:
        print(f"  NEU  ({first[k]}): {raw_of[k]!r}")
        print(f"       ALT ({first[found]}, {count[found]}x): {raw_of[found]!r}")
        hits2 += 1
print(f"  Treffer: {hits2}")

# Frage: gibt es ueberhaupt Payloads, die mitten im Wort enden und die es nicht mehr gibt?
print("\n=== Gegenprobe: Namen, die nur VOR dem Cutoff liefen und seit 2026-09-08 nicht mehr ===")
last = {}
for date, sender, payload in recs:
    k = norm(payload)
    if k not in last or date > last[k]:
        last[k] = date
gone = [k for k in pre if last[k] < '2026-09-08']
print(f"  Anzahl: {len(gone)}")
for k in gone[:15]:
    print(f"    {raw_of[k]!r}  (letztes Vorkommen {last[k]}, {count[k]}x)")
