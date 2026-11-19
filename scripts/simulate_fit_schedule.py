r"""
================================================================================
BACKLINK BROADCAST — MEHRTÄGIGE ROTATIONS- & PLAYLIST-SIMULATION (3-TABELLEN-DB)
================================================================================
Zweck:
  Simuliert den Sendebetrieb über N Stunden (z.B. 72h = 3 Tage) auf Basis der
  in Backlink_Broadcast_Fit.db gespeicherten Titel-Sendungs-Wertungen und des
  aktuellen 24-Stunden-Sendeplans:
    1. Übernimmt den aktuellen Status aller 910 Titel (wann & auf welchem Slot
       jeder Titel zuletzt lief) in eine Arbeitskopie (ohne die echte DB zu ändern).
    2. Berechnet Stunde für Stunde (dem echten 24h-Sendeplan folgend) für jeden
       bewerteten Kandidaten der jeweiligen Sendung:
           Quotient = Stunden_seit_letztem_Play / Cooldown(Fit, Gleicher_Slot)
    3. Wählt die 12 Titel mit dem höchsten Quotienten als Playlist der Stunde,
       verbucht sie im 5-Minuten-Takt in der Arbeitskopie als gespielt und
       schreitet zur nächsten Stunde fort.
    4. Zeigt, wie sich der anfängliche LRP-Rückstau (lange ungespielte Titel mit
       niedrigerer Wertung) abbaut und welche Sendungen an Tag 1, Tag 2 und Tag 3
       gute vs. schwache Matches erzielen.

Aufruf:
  py simulate_fit_schedule.py                  (Standard: 72 Stunden = 3 Tage)
  py simulate_fit_schedule.py --hours 48       (48 Stunden = 2 Tage)
  py simulate_fit_schedule.py --days 4         (96 Stunden = 4 Tage)
  py simulate_fit_schedule.py --start "2026-10-24 10:00"
  py simulate_fit_schedule.py --min-fit 4      (Optional: nur Kandidaten mit Fit >= 4)

Ausgabedateien:
  - C:\Users\kurt_\Betrieb\Radio Fernsehen\Backlink_Broadcast_Simulation.md
  - C:\Users\kurt_\Betrieb\Radio Fernsehen\Backlink_Broadcast_Simulation.csv
  - C:\Users\kurt_\Betrieb\Radio Fernsehen\sim_fit_working_state.json
================================================================================
"""
import os, sys, io, csv, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import bb_fit_db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RF_DIR   = r"C:\Users\kurt_\Betrieb\Radio Fernsehen"
SIM_MD   = os.path.join(RF_DIR, "Backlink_Broadcast_Simulation.md")
SIM_CSV  = os.path.join(RF_DIR, "Backlink_Broadcast_Simulation.csv")
SIM_JSON = os.path.join(RF_DIR, "sim_fit_working_state.json")
MESZ     = timezone(timedelta(hours=2))

def load_24h_schedule_and_db():
    conn = bb_fit_db.get_conn()
    bb_fit_db.sync_shows_and_tracks(conn)
    cur = conn.cursor()

    # For each slot 00:00..23:00, pick the active show (preferring the latest show with rated tracks)
    schedule_by_slot = {}
    for h in range(24):
        slot_hm = f"{h:02d}:00"
        cur.execute("""
            SELECT s.show_id, s.slot_hm, s.show_name, s.show_desc,
                   (SELECT COUNT(*) FROM track_show_fit f WHERE f.show_id = s.show_id) AS f_cnt
            FROM shows s
            WHERE s.slot_hm = ?
            ORDER BY (CASE WHEN f_cnt >= 40 THEN 1 ELSE 0 END) DESC, s.updated_at DESC, f_cnt DESC
            LIMIT 1
        """, (slot_hm,))
        row = cur.fetchone()
        if row:
            schedule_by_slot[slot_hm] = {
                "show_id": row["show_id"],
                "slot_hm": row["slot_hm"],
                "show_name": row["show_name"],
                "show_desc": row["show_desc"],
                "f_cnt": row["f_cnt"]
            }

    # Load all tracks into working copy
    cur.execute("SELECT * FROM tracks")
    working_tracks = {}
    for r in cur.fetchall():
        working_tracks[r["track_id"]] = {
            "track_id": r["track_id"],
            "artist": r["artist"],
            "title": r["title"],
            "full_name": r["full_name"],
            "play_count_total": int(r["play_count_total"] or 0),
            "last_played_mesz": r["last_played_mesz"] or "",
            "last_slot_hm": r["last_slot_hm"] or "",
            "last_show_name": r["last_show_name"] or ""
        }

    # Load all fit ratings grouped by show_id
    cur.execute("SELECT * FROM track_show_fit")
    fits_by_show = defaultdict(list)
    for r in cur.fetchall():
        fits_by_show[r["show_id"]].append({
            "track_id": r["track_id"],
            "full_name": r["full_name"],
            "fit": float(r["fit_score_avg"]),
            "reason": r["reason"] or "",
            "source": r["source"] or ""
        })

    conn.close()
    return schedule_by_slot, working_tracks, fits_by_show

def run_simulation(hours_to_sim=72, start_dt=None, min_fit=1.0, tracks_per_hour=12):
    schedule_by_slot, working_tracks, fits_by_show = load_24h_schedule_and_db()

    if start_dt is None:
        now_naive = datetime.now(MESZ).replace(tzinfo=None)
        start_dt = now_naive.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    sim_hours = []
    all_sim_plays = []
    unique_played_ids = set()

    for step in range(hours_to_sim):
        cur_dt = start_dt + timedelta(hours=step)
        slot_hm = cur_dt.strftime("%H:%M")
        day_num = (step // 24) + 1
        sh = schedule_by_slot.get(slot_hm)
        if not sh:
            continue

        sid = sh["show_id"]
        sh_name = sh["show_name"]
        sh_desc = sh["show_desc"]
        rated_list = fits_by_show.get(sid, [])
        pool_ge_7 = sum(1 for x in rated_list if x["fit"] >= 7.0)
        pool_ge_4 = sum(1 for x in rated_list if x["fit"] >= 4.0)

        candidates = []
        for item in rated_list:
            if item["fit"] < min_fit:
                continue
            tid = item["track_id"]
            t_state = working_tracks.get(tid)
            if not t_state:
                continue

            lp_str = t_state["last_played_mesz"]
            if lp_str:
                try:
                    lp_dt = datetime.strptime(lp_str[:19], "%Y-%m-%d %H:%M:%S")
                    h_unplayed = max(0.1, (cur_dt - lp_dt).total_seconds() / 3600.0)
                except Exception:
                    h_unplayed = 720.0
            else:
                h_unplayed = 720.0

            same_slot = (bool(slot_hm) and t_state["last_slot_hm"] == slot_hm)
            cd_h = bb_fit_db.compute_cooldown_hours(item["fit"], same_slot=same_slot, pool_size=max(15, pool_ge_7))
            quotient = h_unplayed / cd_h

            candidates.append({
                "track_id": tid,
                "full_name": item["full_name"],
                "fit": item["fit"],
                "h_unplayed": h_unplayed,
                "cd_h": cd_h,
                "quotient": quotient,
                "same_slot": same_slot,
                "prev_played": lp_str[:16] if lp_str else "Nie",
                "prev_slot": t_state["last_slot_hm"] or "-",
                "reason": item["reason"]
            })

        # Sort by Kurt's Quotient descending
        candidates.sort(key=lambda x: (-x["quotient"], -x["fit"], -x["h_unplayed"]))
        chosen = candidates[:tracks_per_hour]

        # Book the chosen 12 tracks into the working copy at 5-minute intervals
        hour_plays = []
        for idx, c in enumerate(chosen):
            play_dt = cur_dt + timedelta(minutes=idx * 5)
            play_ts = play_dt.strftime("%Y-%m-%d %H:%M:%S")
            tid = c["track_id"]
            working_tracks[tid]["last_played_mesz"] = play_ts
            working_tracks[tid]["last_slot_hm"] = slot_hm
            working_tracks[tid]["last_show_name"] = sh_name
            working_tracks[tid]["play_count_total"] += 1
            unique_played_ids.add(tid)

            rec = dict(c)
            rec["nr"] = idx + 1
            rec["play_ts"] = play_ts
            rec["show_start"] = cur_dt.strftime("%Y-%m-%d %H:%M")
            rec["slot_hm"] = slot_hm
            rec["day_num"] = day_num
            rec["show_name"] = sh_name
            hour_plays.append(rec)
            all_sim_plays.append(rec)

        avg_fit = sum(x["fit"] for x in hour_plays) / len(hour_plays) if hour_plays else 0.0
        avg_h = sum(x["h_unplayed"] for x in hour_plays) / len(hour_plays) if hour_plays else 0.0
        min_h = min(x["h_unplayed"] for x in hour_plays) if hour_plays else 0.0
        avg_q = sum(x["quotient"] for x in hour_plays) / len(hour_plays) if hour_plays else 0.0
        min_q = min(x["quotient"] for x in hour_plays) if hour_plays else 0.0
        sub1_q_cnt = sum(1 for x in hour_plays if x["quotient"] < 1.0)
        low_fit_cnt = sum(1 for x in hour_plays if x["fit"] < 4.0)
        high_fit_cnt = sum(1 for x in hour_plays if x["fit"] >= 7.0)
        same_slot_cnt = sum(1 for x in hour_plays if x["same_slot"])

        sim_hours.append({
            "step": step + 1,
            "day_num": day_num,
            "show_start": cur_dt.strftime("%Y-%m-%d %H:%M"),
            "slot_hm": slot_hm,
            "show_name": sh_name,
            "show_desc": sh_desc,
            "rated_total": len(rated_list),
            "pool_ge_7": pool_ge_7,
            "pool_ge_4": pool_ge_4,
            "avg_fit": avg_fit,
            "avg_h": avg_h,
            "min_h": min_h,
            "avg_q": avg_q,
            "min_q": min_q,
            "sub1_q_cnt": sub1_q_cnt,
            "low_fit_cnt": low_fit_cnt,
            "high_fit_cnt": high_fit_cnt,
            "same_slot_cnt": same_slot_cnt,
            "plays": hour_plays
        })

    # Save working state JSON
    with open(SIM_JSON, "w", encoding="utf-8") as f:
        json.dump(list(working_tracks.values()), f, ensure_ascii=False, indent=2)

    # Save CSV of all simulated plays
    with open(SIM_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Tag", "Startzeit_Show", "Slot", "Show_Name", "Nr", "Gesendet_Um", "Interpret_Titel", "Fit_Score", "Quotient", "Ungespielt_h", "Cooldown_h", "Gleicher_Slot", "Zuletzt_Gespielt", "Letzter_Slot", "Begruendung"])
        for p in all_sim_plays:
            w.writerow([
                f"Tag {p['day_num']}", p["show_start"], p["slot_hm"], p["show_name"],
                p["nr"], p["play_ts"][11:16], p["full_name"], f"{p['fit']:.1f}",
                f"{p['quotient']:.2f}x", f"{p['h_unplayed']:.1f}h", f"{p['cd_h']:.0f}h",
                "JA" if p["same_slot"] else "NEIN", p["prev_played"], p["prev_slot"], p["reason"]
            ])

    # Save comprehensive Markdown report
    by_slot = defaultdict(dict)
    for sh in sim_hours:
        by_slot[sh["slot_hm"]][sh["day_num"]] = sh

    max_days = max((sh["day_num"] for sh in sim_hours), default=1)

    with open(SIM_MD, "w", encoding="utf-8") as f:
        f.write(f"# Backlink Broadcast – Mehrtägige Rotations-Simulation ({hours_to_sim} Stunden / {max_days} Tage)\n\n")
        f.write(f"* **Startzeit der Simulation:** `{sim_hours[0]['show_start']} Uhr MESZ` bis `{sim_hours[-1]['show_start']} Uhr MESZ`\n")
        f.write(f"* **Gesamt gespielte Tracks:** {len(all_sim_plays)} Plays | **Verschiedene genutzte Titel:** {len(unique_played_ids)} Titel\n")
        f.write(f"* **Auswahl-Regel:** Top {tracks_per_hour} Titel pro Stunde nach Kurts Quotienten-Formel $\\text{{Quotient}} = \\text{{Stunden ungespielt}} / \\text{{Cooldown}}(\\text{{Fit}}, \\text{{Gleicher Slot}})$ (Mindest-Fit: {min_fit:.1f})\n\n")

        # Day-by-Day global summary
        f.write("## 1. Tages-Entwicklung (Abbau des LRP-Rückstaus & Cooldown-Einhaltung von Tag 1 bis Tag " + str(max_days) + ")\n\n")
        f.write("| Simulations-Tag | Stunden | Plays | Ø Fit-Score | Anteil Fit >= 7 | LRP (Fit < 4) | Ø Abstand (h / d) | Ø Quotient | Min-Quotient (Tiefstwert) | Plays mit Quotient < 1.0 |\n")
        f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for d in range(1, max_days + 1):
            d_hours = [x for x in sim_hours if x["day_num"] == d]
            if not d_hours:
                continue
            d_plays = [p for x in d_hours for p in x["plays"]]
            af = sum(p["fit"] for p in d_plays) / len(d_plays)
            ge7 = sum(1 for p in d_plays if p["fit"] >= 7.0)
            lt4 = sum(1 for p in d_plays if p["fit"] < 4.0)
            ah = sum(p["h_unplayed"] for p in d_plays) / len(d_plays)
            aq = sum(p["quotient"] for p in d_plays) / len(d_plays)
            mq = min(p["quotient"] for p in d_plays)
            sub1 = sum(1 for p in d_plays if p["quotient"] < 1.0)
            f.write(f"| **Tag {d}** | {len(d_hours)}h | {len(d_plays)} | **{af:.2f} / 10** | {ge7}/{len(d_plays)} ({ge7/len(d_plays)*100:.0f}%) | {lt4}/{len(d_plays)} ({lt4/len(d_plays)*100:.0f}%) | Ø {ah:.1f}h ({ah/24:.1f}d) | {aq:.2f}x | **{mq:.2f}x** | {sub1}/{len(d_plays)} ({sub1/len(d_plays)*100:.0f}%) |\n")

        f.write("\n## 2. Cooldown-Einhaltung (Min-Quotient) & Fit-Vergleich der 24 Sendungen\n\n")
        f.write("* **Min-Quotient ($Q_{\\min}$):** Niedrigster Quotient des 12. Titels der jeweiligen Sendung. $Q_{\\min} < 1{,}0\\times$ = Cooldown musste unterschritten werden (Pool zu klein $\\rightarrow$ Anpassungs-/Streichungsdruck). $Q_{\\min} \\ge 1{,}0\\times$ = ausreichend versorgt. $Q_{\\min} \\ge 1{,}35\\times$ an Tag 3 = Überschuss (kann Geschwister-Sendung speisen).\n\n")
        f.write("| Slot | Sendung | Pool ($ge 7$/$ge 4$) | Tag 1: $Q_{\min}$ (Ø Fit) | Tag 2: $Q_{\min}$ (Ø Fit) | Tag 3: $Q_{\min}$ (Ø Fit) | Tiefster $Q_{\min}$ (Tag 2–3) | Cooldown- & Pool-Diagnose |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n")

        slot_summary_list = []
        for slot_hm in sorted(by_slot.keys()):
            d_map = by_slot[slot_hm]
            first_sh = next(iter(d_map.values()))
            sh_name = first_sh["show_name"]
            r_tot = first_sh["rated_total"]
            p7 = first_sh["pool_ge_7"]
            p4 = first_sh["pool_ge_4"]

            d_strs = []
            all_f = []
            all_mq = []
            for d in (1, 2, 3):
                if d in d_map:
                    it = d_map[d]
                    d_strs.append(f"**{it['min_q']:.2f}x** (Fit {it['avg_fit']:.1f})")
                    all_f.append(it["avg_fit"])
                    all_mq.append(it["min_q"])
                else:
                    d_strs.append("-")
            tot_avg_f = sum(all_f) / len(all_f) if all_f else 0.0
            d2_d3_f = sum(all_f[1:]) / len(all_f[1:]) if len(all_f) > 1 else tot_avg_f
            min_q_d23 = min(all_mq[1:]) if len(all_mq) > 1 else (all_mq[0] if all_mq else 0.0)
            min_q_d3 = all_mq[2] if len(all_mq) >= 3 else min_q_d23

            if min_q_d23 < 0.85 or (min_q_d23 < 1.0 and d2_d3_f < 7.0):
                diag = "ROT: Cooldown gebrochen / Pool zu klein -> Anpassen oder streichen!"
            elif min_q_d23 < 1.0:
                diag = "GELB: Cooldown knapp unterschritten (< 1.0x) -> Pool leicht vergrößern"
            elif min_q_d3 >= 1.35 and d2_d3_f >= 8.0:
                diag = "TOP-ÜBERSCHUSS (Q_min >= 1.35x): Reichlich Material -> Geschwister-Sendung möglich!"
            else:
                diag = "GRÜN (Q_min >= 1.0x): Ausreichend mit Archivmaterial versorgt"

            f.write(f"| **{slot_hm}** | **{sh_name}** | {r_tot} ({p7}/{p4}) | {d_strs[0]} | {d_strs[1]} | {d_strs[2]} | **{min_q_d23:.2f}x** | {diag} |\n")
            slot_summary_list.append((slot_hm, sh_name, r_tot, p7, p4, d_map, tot_avg_f, d2_d3_f, min_q_d23, min_q_d3, diag))

        f.write("\n---\n\n## 3. Stündliche Playlists der Simulation (Chronologisch)\n\n")
        for sh in sim_hours:
            f.write(f"### [Tag {sh['day_num']} | {sh['show_start']} Uhr] {sh['show_name']} (Ø Fit: {sh['avg_fit']:.1f}/10 | Ø Abstand: {sh['avg_h']:.1f}h / {sh['avg_h']/24:.1f}d | Ø Quotient: {sh['avg_q']:.2f}x)\n\n")
            f.write("| # | Sim-Zeit | Quotient | Ungespielt | Cooldown | Fit | Slot= | Interpret – Titel | Begründung |\n")
            f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |\n")
            for p in sh["plays"]:
                sl_str = "GLEICH" if p["same_slot"] else f"anders ({p['prev_slot']})" 
                clean_r = str(p["reason"]).replace("|", ",").replace("\n", " ")
                f.write(f"| {p['nr']} | {p['play_ts'][11:16]} | **{p['quotient']:.2f}x** | {p['h_unplayed']:.1f}h ({p['h_unplayed']/24:.1f}d) | {p['cd_h']:.0f}h | **{p['fit']:.1f}** | {sl_str} | **{p['full_name']}** | {clean_r} |\n")
            f.write("\n")

    # Print concise summary to console
    print("=" * 105)
    print(f"MEHRTÄGIGE ROTATIONS-SIMULATION ABGESCHLOSSEN ({hours_to_sim} STUNDEN / {max_days} TAGE)")
    print(f"Zeitraum: {sim_hours[0]['show_start']} bis {sim_hours[-1]['show_start']} | Plays: {len(all_sim_plays)} | Genutzte Unikate: {len(unique_played_ids)}")
    print("=" * 105)
    for d in range(1, max_days + 1):
        d_hours = [x for x in sim_hours if x["day_num"] == d]
        if not d_hours: continue
        d_plays = [p for x in d_hours for p in x["plays"]]
        af = sum(p["fit"] for p in d_plays) / len(d_plays)
        ge7 = sum(1 for p in d_plays if p["fit"] >= 7.0)
        lt4 = sum(1 for p in d_plays if p["fit"] < 4.0)
        ah = sum(p["h_unplayed"] for p in d_plays) / len(d_plays)
        aq = sum(p["quotient"] for p in d_plays) / len(d_plays)
        ss = sum(1 for p in d_plays if p["same_slot"])
        print(f"  Tag {d}: {len(d_hours):2d}h ({len(d_plays):3d} Plays) | Ø Fit: {af:4.2f}/10 | Fit>=7: {ge7:3d} ({ge7/len(d_plays)*100:4.0f}%) | Fit<4 (LRP): {lt4:3d} ({lt4/len(d_plays)*100:4.0f}%) | Ø Abstand: {ah:5.1f}h ({ah/24:4.1f}d) | Ø Quot: {aq:4.2f}x | Gleicher Slot: {ss:2d}")
    print("-" * 105)
    print(f"{'Slot':5s} | {'Sendung':34s} | {'Pool(>=7/>=4)':13s} | {'Tag1 Qmin(Fit)':15s} | {'Tag2 Qmin(Fit)':15s} | {'Tag3 Qmin(Fit)':15s} | {'MinQ(T2-3)'}")
    print("-" * 105)
    # Sort console print by min_q_d23 ascending (highest adaptation pressure at the top!)
    for slot_hm, sh_name, r_tot, p7, p4, d_map, tot_avg_f, d2_d3_f, min_q_d23, min_q_d3, diag in sorted(slot_summary_list, key=lambda x: (x[8], x[7])):
        c1 = f"{d_map[1]['min_q']:4.2f}x ({d_map[1]['avg_fit']:3.1f})" if 1 in d_map else "  -       "
        c2 = f"{d_map[2]['min_q']:4.2f}x ({d_map[2]['avg_fit']:3.1f})" if 2 in d_map else "  -       "
        c3 = f"{d_map[3]['min_q']:4.2f}x ({d_map[3]['avg_fit']:3.1f})" if 3 in d_map else "  -       "
        print(f"{slot_hm:5s} | {sh_name[:34]:34s} | {r_tot:2d} ({p7:2d}/{p4:2d})   | {c1:15s} | {c2:15s} | {c3:15s} | {min_q_d23:5.2f}x | {diag[:24]}")
    print("=" * 105)
    print("Markdown-Report :", SIM_MD)
    print("CSV-Protokoll   :", SIM_CSV)
    print("Arbeitskopie    :", SIM_JSON)

def main():
    args = sys.argv[1:]
    hours_to_sim = 72
    start_dt = None
    min_fit = 1.0
    i = 0
    while i < len(args):
        if args[i] == "--hours" and i + 1 < len(args):
            hours_to_sim = int(args[i + 1])
            i += 1
        elif args[i] == "--days" and i + 1 < len(args):
            hours_to_sim = int(args[i + 1]) * 24
            i += 1
        elif args[i] == "--start" and i + 1 < len(args):
            start_dt = datetime.strptime(args[i + 1].strip()[:16], "%Y-%m-%d %H:%M")
            i += 1
        elif args[i] == "--min-fit" and i + 1 < len(args):
            min_fit = float(args[i + 1])
            i += 1
        elif args[i] in ("-h", "--help"):
            print("Verwendung: py simulate_fit_schedule.py [--hours N] [--days D] [--start 'YYYY-MM-DD HH:MM'] [--min-fit F]")
            sys.exit(0)
        i += 1
    run_simulation(hours_to_sim=hours_to_sim, start_dt=start_dt, min_fit=min_fit)

if __name__ == "__main__":
    main()
