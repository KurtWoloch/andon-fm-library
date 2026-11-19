# Live365 Titel-Varianten: abgeschnitten vs. vollstaendig

Recherche im Andon-FM-Log: derselbe Track unter alter (abgeschnittener) und neuer (vollstaendiger) Titelanzeige der Live365-Plattform.

| | |
|---|---|
| Log | `C:\Users\kurt_\Betrieb\Radio Fernsehen\Andon FM Station logs.txt.music.txt` |
| Codierung | utf-8-sig |
| Zeilen | 169451 (169451 MUSIC-Zeilen geparst, 0 uebersprungen) |
| Zeitraum | 2026-02-01 bis 2026-09-10 |
| Artists (normalisiert) | 1604 |
| Cutoff | 2026-09-08 |
| Erzeugt | 2026-09-10 |

## Methodik

1. **Einlesen:** Log bytes lesen, Decode-Kette `utf-8-sig` -> `utf-8` -> `cp1252` -> `latin-1`; pro Zeile Regex-Parsing von Datum, Sender, `MUSIC: <Artist> - <Title>`, Start. Split am **ersten** ` - `.
2. **Normalisierung:** Whitespace kollabieren + trimmen + `casefold`. Gruppierung nach normalisiertem Artist; nur Artists mit mehr als einer unterschiedlichen Titel-Schreibweise.
3. **Paarbildung:** innerhalb jedes Artists alle geordneten Paare (A, B) mit `len(A) < len(B)` und `A` ist case-insensitiver Substring von `B`.
4. **Erstes Vorkommen** jeder Variante (Minimum des Datums).
5. **Kriterium:** behalten nur, wenn erstes Vorkommen von B >= `2026-09-08` **und** erstes Vorkommen von A < `2026-09-08`.
6. **Verdachts-Tokens** im laengeren Titel (`(Extended`, `(Remaster`, `(Live`, `(Remix`, `(Mix`, `(Edit`, `(Version`, `(Album`, `(LP`, `(Acoustic`, `(Uncut` ...) fuehren in den Abschnitt *Unsicher / pruefen* statt in die klaren Faelle.
7. **Muster-Hinweis:** echtes Abschneiden erzeugt immer einen *Praefix*. Paare, bei denen die kurze Variante nur irgendwo im laengeren String vorkommt (z.B. `As` in `Master Blaster (Jammin')`), sind Zufalls-Substrings und in der Ausschluss-Tabelle als solches markiert.
8. Zusaetzliche Gegenproben (Ergebnisse in der Abschlussantwort, nicht im Bericht aufgelistet): Praefix-Match mit >= 12 gemeinsamen Zeichen (faengt unsaubere Abschneidungen, die kein exakter Substring sind) und ein artist-uebergreifender Substring-Scan.

## Klare Faelle: 1

| Artist | Alt-Variante (abgeschnitten) | Erstes Vorkommen Alt | Neu-Variante (vollstaendig) | Erstes Vorkommen Neu | Sender | Vorkommen Alt/Neu |
|---|---|---|---|---|---|---|
| Henry Cow | Beautiful as the Moo | 2026-05-17 | Beautiful as the Moon; Terrible as an Army with Banners | 2026-09-09 | Thinking Frequencies | 9 / 2 |

## Unsicher / pruefen: 0

Erfuellen die Suchkriterien, aber die laengere Variante enthaelt Versions-Marker und koennte ein echter anderer Track sein.

_Keine._

## Sanity-Check Henry Cow

**Status: OK** - 1 Treffer, 2 verschiedene Titel-Schreibweisen im Log.

Alle Henry-Cow-Eintraege im Log (Rohdaten, ungefiltert):

| Geschriebener Titel | Normalisiert | Erstes Vorkommen | Letztes Vorkommen | Anzahl | Sender |
|---|---|---|---|---|---|
| Beautiful as the Moo | `beautiful as the moo` | 2026-05-17 | 2026-09-08 | 9 | Thinking Frequencies |
| Beautiful as the Moon; Terrible as an Army with Banners | `beautiful as the moon; terrible as an army with banners` | 2026-09-09 | 2026-09-10 | 2 | Thinking Frequencies |

## Ausgeschlossen durch Datums-Kriterium: 12

Alle uebrigen Substring-Paare desselben Artists. Sie erfuellen (b) nicht: entweder existierte die lange Variante schon vor dem Cutoff, oder die kurze Variante kam erst ab dem Cutoff. Zur Nachvollziehbarkeit gelistet - nichts wurde stillschweigend verworfen.

| Artist | Kurz | Erstes Vorkommen Kurz | Lang | Erstes Vorkommen Lang | Muster | Grund |
|---|---|---|---|---|---|---|
| Creedence Clearwater Revival | Bad Moon Rising | 2026-06-20 | Bad Moon Rising (Remastered 1985) | 2026-07-30 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Ella Fitzgerald | Bewitched, Bothered And Bewildered | 2026-07-12 | Bewitched, Bothered And Bewildered  (Ella Fitzgerald and Her Famous Orchestra Bewitched, Bothered And Bewildered) | 2026-08-03 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Filippo Beck Peccoz | Main Theme | 2026-08-25 | Desperados III Main Theme | 2026-08-25 | kein Praefix -> Zufalls-Substring | lange Variante existierte schon vor Cutoff |
| Gilbert Bécaud | Nathalie | 2026-09-02 | Nathalie  (Version allemande) | 2026-08-17 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Nirvana | Smells Like Teen Spirit | 2026-05-21 | Smells Like Teen Spirit (Album Version) | 2026-06-04 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Noizu | Summer 91 (Looking Back) | 2026-07-30 | Summer 91 (Looking Back) (Acoustic) | 2026-08-01 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Roberta Flack | The First Time Ever I Saw Your Face | 2026-06-15 | The First Time Ever I Saw Your Face (2020 Remaster) | 2026-05-21 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| RÜFÜS DU SOL | Innerbloom | 2026-05-15 | Innerbloom  (Live from Joshua Tree) | 2026-02-01 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Sinéad O'Connor | Nothing Compares 2 U | 2026-08-03 | Nothing Compares 2 U (2009 Remaster) | 2026-07-05 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Stevie Wonder | As | 2026-07-26 | Master Blaster (Jammin') | 2026-07-30 | kein Praefix -> Zufalls-Substring | lange Variante existierte schon vor Cutoff |
| The Dave Brubeck Quartet | Take Five | 2026-02-07 | Take Five (Album Version) | 2026-05-16 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |
| Tim Hecker | In the Fog I | 2026-05-22 | In the Fog II | 2026-05-22 | Praefix (Abschneidung moeglich) | lange Variante existierte schon vor Cutoff |

## Unabhaengige Verifikation (Sidestepper, 2026-09-10)

Zweiter, unabhaengig geschriebener Durchlauf (`verify_title_variants.py`, `check_global_variants.py`, `check_payload_cap.py`), andere Heuristik:

| Test | Ergebnis |
|---|---|
| Exakte Substring-Paare je Artist, Lang-Variante ab 2026-09-08 | **1** (nur Henry Cow) |
| Praefix-Naehe >= 10 Zeichen, Lang-Variante ab 2026-09-08 | **1** (nur Henry Cow) |
| Gegenrichtung (Kurz-Variante erst ab Cutoff) | 0 |
| Artist-unabhaengiger Substring-Scan, Substring >= 15 Zeichen | **1** (nur Henry Cow) |
| Hartes Zeichen-Limit der Anzeige? | **Nein** |

**Kein globaler Zeichen-Cap:** Die Titel-Laengen sind vor dem Cutoff glatt verteilt, kein Spike bei 20/32/40 Zeichen. Der laengste Payload vor dem Cutoff hat 214 Zeichen, der laengste danach 151. Die Anzeige hat also **nicht** generell bei einer festen Breite abgeschnitten; die Kuerzung war offenbar auf einzelne Tracks/Metadaten begrenzt.

**Warum nur 1 Treffer:** Ab 2026-09-09 erschienen ueberhaupt nur 23 neue distinkte Payloads (24 Zeilen). Der Beobachtungszeitraum ist also noch sehr klein. Sobald mehr Tage mit vollstaendiger Anzeige im Log liegen, lohnt ein erneuter Lauf — dann mit `NEW_FROM=2026-09-09` und demselben Skript.

*Hinweis:* Ein Praefix-Scan ab 12 Zeichen liefert zusaetzlich 6 Scheintreffer, die alle nur auf dem gemeinsamen **Artist-Namen** beruhen (z. B. `Billy Joel - ` bei `The River of Dreams` vs. `Vienna`). Diese sind keine Titelvarianten und in der Trefferzahl oben nicht enthalten.

