# -*- coding: utf-8 -*-
"""Unabhaengige Verifikation der Live365-Titelabschneidung."""
import sys, io, re, os
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LOG = r'C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt'
CUTOFF = '2026-09-08'

raw = open(LOG, 'rb').read()
for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
    try:
        text = raw.decode(enc)
        print(f"Encoding: {enc}")
        break
    except UnicodeDecodeError:
        continue

LINE = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \| ([^|]+) \| MUSIC: (.+?) \| Start: (.+)$')

recs = []   # (date, sender, artist, title)
skipped = 0
for line in text.splitlines():
    m = LINE.match(line.strip())
    if not m:
        if line.strip():
            skipped += 1
        continue
    date, tm, sender, payload, start = m.groups()
    if ' - ' in payload:
        artist, title = payload.split(' - ', 1)
    else:
        artist, title = '', payload
    recs.append((date, sender.strip(), artist.strip(), title.strip()))

print(f"MUSIC-Zeilen: {len(recs)}   uebersprungen: {skipped}")
print(f"Zeitraum: {min(r[0] for r in recs)} .. {max(r[0] for r in recs)}")

pre = [r for r in recs if r[0] < CUTOFF]
post = [r for r in recs if r[0] >= CUTOFF]
print(f"vor Cutoff: {len(pre)}   ab Cutoff: {len(post)}")

# ---- 1) Laengenverteilung: gab es ein hartes Limit? ----
def lens(rs):
    d = defaultdict(int)
    for r in rs:
        d[len(r[3])] += 1
    return d

lp, lq = lens(pre), lens(post)
print("\n--- Titel-Laengen (Top 12, VOR Cutoff) ---")
for k in sorted(lp, key=lambda x: -lp[x])[:12]:
    print(f"  {k:3d} Zeichen: {lp[k]}")
print("--- Titel-Laengen (Top 12, AB Cutoff) ---")
for k in sorted(lq, key=lambda x: -lq[x])[:12]:
    print(f"  {k:3d} Zeichen: {lq[k]}")

print(f"\nMax Laenge VOR Cutoff: {max(len(r[3]) for r in pre)}")
print(f"Max Laenge AB  Cutoff: {max(len(r[3]) for r in post)}")

# Wie viele Titel enden VOR dem Cutoff genau auf einer moeglichen Cap-Laenge?
for cap in range(14, 46):
    n_pre = sum(1 for r in pre if len(r[3]) == cap)
    n_post = sum(1 for r in post if len(r[3]) == cap)
    if n_pre >= 40:
        print(f"  Cap-Kandidat {cap:2d}: vor={n_pre:5d}  ab={n_post:5d}")

# ---- 2) Breiter Substring-Scan (artist-normalisiert) ----
def norm(s):
    return re.sub(r'\s+', ' ', s).strip().casefold()

by_artist = defaultdict(lambda: defaultdict(lambda: {'first': '9999', 'last': '', 'n': 0, 'senders': set(), 'raw': ''}))
for date, sender, artist, title in recs:
    e = by_artist[norm(artist)][norm(title)]
    if date < e['first']:
        e['first'] = date
    if date > e['last']:
        e['last'] = date
    e['n'] += 1
    e['senders'].add(sender)
    if not e['raw']:
        e['raw'] = title

print(f"\nArtists: {len(by_artist)}")

exact_sub = []   # (artist, short, s_first, s_n, long, l_first, l_n)
for a, titles in by_artist.items():
    ks = list(titles.keys())
    for i in range(len(ks)):
        for j in range(len(ks)):
            if i == j:
                continue
            A, B = ks[i], ks[j]
            if len(A) >= len(B):
                continue
            if A not in B:
                continue
            ea, eb = titles[A], titles[B]
            if eb['first'] >= CUTOFF and ea['first'] < CUTOFF:
                exact_sub.append((a, ea['raw'], ea['first'], ea['n'], eb['raw'], eb['first'], eb['n']))

print(f"\n=== (A) Exakte Substring-Paare mit Lang-Variante ab {CUTOFF} und Kurz-Variante davor: {len(exact_sub)} ===")
for row in sorted(exact_sub, key=lambda r: r[5]):
    print(f"  {row[0]!r}: {row[1]!r} (ab {row[2]}, {row[3]}x)  ->  {row[4]!r} (ab {row[5]}, {row[6]}x)")

# ---- 3) Praefix-Naehe ohne exakten Substring (>=10 gemeinsame Zeichen) ----
o = __import__('os').path.commonprefix if False else None
def common_prefix_len(x, y):
    n = min(len(x), len(y))
    k = 0
    while k < n and x[k] == y[k]:
        k += 1
    return k

prefix_near = []
for a, titles in by_artist.items():
    ks = list(titles.keys())
    for i in range(len(ks)):
        for j in range(len(ks)):
            if i == j:
                continue
            A, B = ks[i], ks[j]
            if len(A) >= len(B):
                continue
            cpl = common_prefix_len(A, B)
            if cpl >= 10:
                ea, eb = titles[A], titles[B]
                if eb['first'] >= CUTOFF and ea['first'] < CUTOFF:
                    prefix_near.append((a, ea['raw'], ea['first'], ea['n'], eb['raw'], eb['first'], eb['n'], cpl))

print(f"\n=== (B) Praefix-Naehe (>=10 Zeichen) mit Lang-Variante ab {CUTOFF}: {len(prefix_near)} ===")
for row in sorted(prefix_near, key=lambda r: -r[7]):
    print(f"  cpl={row[7]:2d} {row[0]!r}: {row[1]!r} (ab {row[2]}, {row[3]}x) -> {row[4]!r} (ab {row[5]}, {row[6]}x)")

# ---- 4) Gegenrichtung: Kurz-Variante erst ab Cutoff ----
rev = []
for a, titles in by_artist.items():
    ks = list(titles.keys())
    for i in range(len(ks)):
        for j in range(len(ks)):
            if i == j:
                continue
            A, B = ks[i], ks[j]
            if len(A) >= len(B):
                continue
            if A not in B:
                continue
            ea, eb = titles[A], titles[B]
            if ea['first'] >= CUTOFF and eb['first'] < CUTOFF:
                rev.append((a, ea['raw'], ea['first'], ea['n'], eb['raw'], eb['first'], eb['n']))
print(f"\n=== (C) Gegenrichtung (Kurz-Variante erst ab {CUTOFF}): {len(rev)} ===")
for row in rev[:25]:
    print(f"  {row[0]!r}: {row[1]!r} (ab {row[2]}, {row[3]}x) -> {row[4]!r} (ab {row[5]}, {row[6]}x)")

# ---- 5) Titel, die NUR ab Cutoff existieren, und deren Praefix vorher existierte (artist-frei) ----
print("\n=== (D) Titel ab Cutoff, deren Kurzform (Praefix) in anderem Artist-Kontext vorher lief ===")
pre_titles = set()
for date, sender, artist, title in pre:
    pre_titles.add(norm(title))
cnt = 0
for a, titles in by_artist.items():
    for t, e in titles.items():
        if e['first'] >= CUTOFF and len(t) >= 14:
            # suche laengeren Titel, dessen Praefix kuerzerer Titel in pre_titles liegt
            for cut in range(8, len(t)):
                if t[:cut] in pre_titles:
                    print(f"  {a!r}: neu {e['raw']!r} (ab {e['first']}) -- Praefix {t[:cut]!r} lief vorher")
                    cnt += 1
                    break
print(f"  Treffer: {cnt}")

# ---- 6) Henry-Cow-Rohdaten ----
print("\n=== Henry Cow Rohdaten ===")
for date, sender, artist, title in recs:
    if 'henry cow' in norm(artist):
        print(f"  {date} | {sender} | {title!r}")
