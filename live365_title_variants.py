# -*- coding: utf-8 -*-
"""
live365_title_variants.py
=========================
Sucht im Andon-FM-Log (Live365) nach Faellen, in denen DERSELBE Track unter
einer kurzen (abgeschnittenen, Alt-Variante) und einer langen (vollstaendigen,
Neu-Variante) Schreibweise auftritt.

Kriterien fuer einen Treffer:
  (a) kurze Schreibweise A ist case-insensitiver Substring der langen B, A != B,
      len(A) < len(B)  und beide gehoeren zum selben (normalisierten) Artist
  (b) erste Vorkommen von B >= CUTOFF (Default 2026-09-08)
      UND erste Vorkommen von A <  CUTOFF

Zusatz-Auswertung:
  - Titel mit Verdachts-Tokens ((Extended, (Remaster, (Live, (Remix, (Mix,
    (Edit, (Version, (Album ...) im laengeren Titel => "Unsicher / pruefen",
    weil es ein echter anderer Track (andere Version) sein koennte.
  - Alle Substring-Paare, die am Datums-Kriterium scheitern, werden als
    "Ausgeschlossen" gelistet - nichts wird stillschweigend verworfen.

Nur lokal, kein Netzwerk. Windows: Aufruf via `py live365_title_variants.py`.
"""

import io
import os
import re
import sys
from collections import defaultdict
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOG_PATH = r"C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt"
OUT_DIR = r"C:\Users\kurt_\.openclaw\workspace\andon-fm-library"
REPORT_PATH = os.path.join(OUT_DIR, "live365-title-variants-2026-09-10.md")

CUTOFF = date(2026, 9, 8)
SANITY_ARTIST = "henry cow"
SANITY_FULL = "beautiful as the moon; terrible as an army with banners"

LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2})"
    r" \| (?P<sender>[^|]+?) \| MUSIC: (?P<rest>.+?) \| Start: (?P<start>.+)$"
)

SUSPECT_TOKENS = (
    "(extended", "(radio edit", "(remaster", "(live", "(remix", "(rmx",
    "(mix", "(edit", "(version", "(album", "(single", "(deluxe", "(bonus",
    "(instrumental", "(acoustic", "(demo", "(reprise", "(feat", "(mono",
    "(stereo", "(club", "(dub", "(vocal", "(lp ", "(original", "(ao vivo",
    "(en vivo", "(uncut", "(cover",
)


def norm(s: str) -> str:
    """Normalisierung: Whitespace zusammenfassen, trimmen, casefold."""
    return re.sub(r"\s+", " ", s.strip()).casefold()


def read_lines(path: str):
    """Robustes Einlesen: utf-8-sig -> utf-8 -> cp1252 -> latin-1."""
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc).splitlines(), enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Keine passende Codierung gefunden")


def parse():
    lines, enc = read_lines(LOG_PATH)
    total = len(lines)
    parsed = skipped = 0
    dmin = dmax = None
    # artist_norm -> title_norm -> rec
    data = defaultdict(lambda: defaultdict(
        lambda: {"first": None, "last": None, "count": 0,
                 "senders": set(), "raw": set()}))

    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            skipped += 1
            continue
        try:
            d = date.fromisoformat(m.group("date"))
        except ValueError:
            skipped += 1
            continue
        parsed += 1
        dmin = d if dmin is None or d < dmin else dmin
        dmax = d if dmax is None or d > dmax else dmax

        rest = m.group("rest")
        if " - " not in rest:
            continue
        artist_raw, title_raw = rest.split(" - ", 1)
        a_norm, t_norm = norm(artist_raw), norm(title_raw)
        if not a_norm or not t_norm:
            continue

        rec = data[a_norm][t_norm]
        rec["count"] += 1
        rec["senders"].add(m.group("sender").strip())
        rec["raw"].add(f"{artist_raw.strip()} - {title_raw.strip()}")
        if rec["first"] is None or d < rec["first"]:
            rec["first"] = d
        if rec["last"] is None or d > rec["last"]:
            rec["last"] = d

    return data, enc, total, parsed, skipped, dmin, dmax


def analyse(data):
    """Alle Substring-Paare desselben Artists -> in Kategorien einsortieren."""
    clear, suspect, excluded = [], [], []
    for a_norm, titles in data.items():
        keys = sorted(titles)
        if len(keys) < 2:
            continue
        for i, short_k in enumerate(keys):
            for j, long_k in enumerate(keys):
                if i == j or len(short_k) >= len(long_k):
                    continue
                if short_k not in long_k:
                    continue
                s, l = titles[short_k], titles[long_k]
                if s["first"] is None or l["first"] is None:
                    continue
                row = {
                    "artist": sorted(s["raw"])[0].split(" - ", 1)[0],
                    "short": short_k,
                    "short_title": sorted(s["raw"])[0].split(" - ", 1)[-1],
                    "short_first": s["first"],
                    "short_last": s["last"],
                    "short_count": s["count"],
                    "long": long_k,
                    "long_title": sorted(l["raw"])[0].split(" - ", 1)[-1],
                    "long_first": l["first"],
                    "long_last": l["last"],
                    "long_count": l["count"],
                    "senders": sorted(s["senders"] | l["senders"]),
                    "tokens": [t for t in SUSPECT_TOKENS
                               if t in long_k or t in short_k],
                    # Abschneiden erzeugt immer einen Praefix; ein reiner
                    # Zufalls-Substring (z.B. 'as' in 'master blaster') nicht.
                    "prefix": long_k.startswith(short_k),
                }
                date_ok = l["first"] >= CUTOFF and s["first"] < CUTOFF
                if not date_ok:
                    if l["first"] >= CUTOFF:      # kurze Variante kam zu spaet
                        reason = "kurze Variante erstmals >= Cutoff"
                    else:                          # lange Variante schon vorher
                        reason = "lange Variante existierte schon vor Cutoff"
                    row["reason"] = reason
                    excluded.append(row)
                elif row["tokens"]:
                    suspect.append(row)
                else:
                    clear.append(row)
    key = lambda r: (r["artist"].casefold(), r["long_first"], r["long"])
    return sorted(clear, key=key), sorted(suspect, key=key), sorted(excluded, key=key)


def build_report(data, enc, total, parsed, skipped, dmin, dmax,
                 clear, suspect, excluded):
    os.makedirs(OUT_DIR, exist_ok=True)

    henry = []
    for key_ in data:
        if SANITY_ARTIST in key_:
            for t, rec in data[key_].items():
                henry.append((t, rec))
    henry.sort(key=lambda x: x[1]["first"] or date.max)
    henry_hits = [r for r in clear + suspect if SANITY_ARTIST in r["artist"].casefold()]
    sanity_ok = bool(henry_hits) and any(SANITY_FULL in r["long"] for r in henry_hits)

    o = []
    o.append("# Live365 Titel-Varianten: abgeschnitten vs. vollstaendig")
    o.append("")
    o.append("Recherche im Andon-FM-Log: derselbe Track unter alter (abgeschnittener) "
             "und neuer (vollstaendiger) Titelanzeige der Live365-Plattform.")
    o.append("")
    o.append("| | |")
    o.append("|---|---|")
    o.append(f"| Log | `{LOG_PATH}` |")
    o.append(f"| Codierung | {enc} |")
    o.append(f"| Zeilen | {total} ({parsed} MUSIC-Zeilen geparst, {skipped} uebersprungen) |")
    o.append(f"| Zeitraum | {dmin} bis {dmax} |")
    o.append(f"| Artists (normalisiert) | {len(data)} |")
    o.append(f"| Cutoff | {CUTOFF.isoformat()} |")
    o.append("| Erzeugt | 2026-09-10 |")
    o.append("")

    o.append("## Methodik")
    o.append("")
    o.append("1. **Einlesen:** Log bytes lesen, Decode-Kette `utf-8-sig` -> `utf-8` -> "
             "`cp1252` -> `latin-1`; pro Zeile Regex-Parsing von Datum, Sender, "
             "`MUSIC: <Artist> - <Title>`, Start. Split am **ersten** ` - `.")
    o.append("2. **Normalisierung:** Whitespace kollabieren + trimmen + `casefold`. "
             "Gruppierung nach normalisiertem Artist; nur Artists mit mehr als einer "
             "unterschiedlichen Titel-Schreibweise.")
    o.append("3. **Paarbildung:** innerhalb jedes Artists alle geordneten Paare (A, B) "
             "mit `len(A) < len(B)` und `A` ist case-insensitiver Substring von `B`.")
    o.append("4. **Erstes Vorkommen** jeder Variante (Minimum des Datums).")
    o.append(f"5. **Kriterium:** behalten nur, wenn erstes Vorkommen von B >= "
             f"`{CUTOFF}` **und** erstes Vorkommen von A < `{CUTOFF}`.")
    o.append("6. **Verdachts-Tokens** im laengeren Titel (`(Extended`, `(Remaster`, "
             "`(Live`, `(Remix`, `(Mix`, `(Edit`, `(Version`, `(Album`, `(LP`, "
             "`(Acoustic`, `(Uncut` ...) fuehren in den Abschnitt *Unsicher / pruefen* "
             "statt in die klaren Faelle.")
    o.append("7. **Muster-Hinweis:** echtes Abschneiden erzeugt immer einen *Praefix*. "
             "Paare, bei denen die kurze Variante nur irgendwo im laengeren String "
             "vorkommt (z.B. `As` in `Master Blaster (Jammin')`), sind Zufalls-Substrings "
             "und in der Ausschluss-Tabelle als solches markiert.")
    o.append("8. Zusaetzliche Gegenproben (Ergebnisse in der Abschlussantwort, nicht "
             "im Bericht aufgelistet): Praefix-Match mit >= 12 gemeinsamen Zeichen "
             "(faengt unsaubere Abschneidungen, die kein exakter Substring sind) und "
             "ein artist-uebergreifender Substring-Scan.")
    o.append("")

    o.append(f"## Klare Faelle: {len(clear)}")
    o.append("")
    if clear:
        o.append("| Artist | Alt-Variante (abgeschnitten) | Erstes Vorkommen Alt | "
                 "Neu-Variante (vollstaendig) | Erstes Vorkommen Neu | Sender | "
                 "Vorkommen Alt/Neu |")
        o.append("|---|---|---|---|---|---|---|")
        for r in clear:
            o.append("| {artist} | {st} | {sf} | {lt} | {lf} | {se} | {sc} / {lc} |".format(
                artist=r["artist"].replace("|", "/"),
                st=r["short_title"].replace("|", "/"),
                sf=r["short_first"].isoformat(),
                lt=r["long_title"].replace("|", "/"),
                lf=r["long_first"].isoformat(),
                se=", ".join(r["senders"]),
                sc=r["short_count"], lc=r["long_count"]))
    else:
        o.append("_Keine Treffer._")
    o.append("")

    o.append(f"## Unsicher / pruefen: {len(suspect)}")
    o.append("")
    o.append("Erfuellen die Suchkriterien, aber die laengere Variante enthaelt "
             "Versions-Marker und koennte ein echter anderer Track sein.")
    o.append("")
    if suspect:
        o.append("| Artist | Alt-Variante | Erstes Vorkommen Alt | Neu-Variante | "
                 "Erstes Vorkommen Neu | Sender | Vorkommen Alt/Neu | Verdacht |")
        o.append("|---|---|---|---|---|---|---|---|")
        for r in suspect:
            o.append("| {artist} | {st} | {sf} | {lt} | {lf} | {se} | {sc} / {lc} | {tk} |".format(
                artist=r["artist"].replace("|", "/"),
                st=r["short_title"].replace("|", "/"),
                sf=r["short_first"].isoformat(),
                lt=r["long_title"].replace("|", "/"),
                lf=r["long_first"].isoformat(),
                se=", ".join(r["senders"]),
                sc=r["short_count"], lc=r["long_count"],
                tk=", ".join(r["tokens"])))
    else:
        o.append("_Keine._")
    o.append("")

    o.append("## Sanity-Check Henry Cow")
    o.append("")
    o.append(f"**Status: {'OK' if sanity_ok else 'FEHLGESCHLAGEN'}** - "
             f"{len(henry_hits)} Treffer, {len(henry)} verschiedene Titel-Schreibweisen "
             f"im Log.")
    o.append("")
    if henry:
        o.append("Alle Henry-Cow-Eintraege im Log (Rohdaten, ungefiltert):")
        o.append("")
        o.append("| Geschriebener Titel | Normalisiert | Erstes Vorkommen | Letztes Vorkommen | Anzahl | Sender |")
        o.append("|---|---|---|---|---|---|")
        for t, rec in henry:
            raw = sorted(rec["raw"])[0].split(" - ", 1)[-1]
            o.append(f"| {raw.replace('|', '/')} | `{t}` | {rec['first']} | {rec['last']} | "
                     f"{rec['count']} | {', '.join(sorted(rec['senders']))} |")
    else:
        o.append("_Keine Henry-Cow-Eintraege gefunden - Logik pruefen!_")
    o.append("")

    o.append(f"## Ausgeschlossen durch Datums-Kriterium: {len(excluded)}")
    o.append("")
    o.append("Alle uebrigen Substring-Paare desselben Artists. Sie erfuellen (b) nicht: "
             "entweder existierte die lange Variante schon vor dem Cutoff, oder die "
             "kurze Variante kam erst ab dem Cutoff. Zur Nachvollziehbarkeit gelistet - "
             "nichts wurde stillschweigend verworfen.")
    o.append("")
    if excluded:
        o.append("| Artist | Kurz | Erstes Vorkommen Kurz | Lang | Erstes Vorkommen Lang | "
                 "Muster | Grund |")
        o.append("|---|---|---|---|---|---|---|")
        for r in excluded:
            o.append("| {artist} | {st} | {sf} | {lt} | {lf} | {mu} | {rs} |".format(
                artist=r["artist"].replace("|", "/"),
                st=r["short_title"].replace("|", "/"),
                sf=r["short_first"].isoformat(),
                lt=r["long_title"].replace("|", "/"),
                lf=r["long_first"].isoformat(),
                mu="Praefix (Abschneidung moeglich)" if r["prefix"]
                   else "kein Praefix -> Zufalls-Substring",
                rs=r["reason"]))
    else:
        o.append("_Keine._")
    o.append("")

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(o) + "\n")
    return sanity_ok, henry


def main():
    data, enc, total, parsed, skipped, dmin, dmax = parse()
    clear, suspect, excluded = analyse(data)
    sanity_ok, henry = build_report(data, enc, total, parsed, skipped, dmin, dmax,
                                    clear, suspect, excluded)

    print(f"encoding={enc} lines={total} parsed={parsed} skipped={skipped}")
    print(f"range={dmin}..{dmax} artists={len(data)}")
    print(f"clear={len(clear)} suspect={len(suspect)} excluded={len(excluded)} "
          f"henry_sanity={'OK' if sanity_ok else 'FAIL'}")
    print("-" * 72)
    for r in clear:
        print(f"CLEAR  {r['artist']}: {r['short_title']!r} ({r['short_first']}, n={r['short_count']})"
              f" -> {r['long_title']!r} ({r['long_first']}, n={r['long_count']}) "
              f"[{', '.join(r['senders'])}]")
    for r in suspect:
        print(f"SUSP   {r['artist']}: {r['short_title']!r} -> {r['long_title']!r} {r['tokens']}")
    print("-" * 72)
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
