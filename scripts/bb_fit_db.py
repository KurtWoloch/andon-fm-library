r"""
================================================================================
BACKLINK BROADCAST — 3-TABELLEN-DATENBANK FUER TITEL-SENDUNGS-PASSGENAUIGKEIT
================================================================================
Tabellen in SQLite (Backlink_Broadcast_Fit.db) + automatische CSV-Spiegelung:
  1. shows          (Sendungen)          -> Backlink_Broadcast_DB_Sendungen.csv
  2. tracks         (Archivtitel 910)    -> Backlink_Broadcast_DB_Titel.csv
  3. track_show_fit (Fit-Wertungen N:M)  -> Backlink_Broadcast_DB_Fit_Matrix.csv
================================================================================
"""
import os, sys, io, re, csv, json, sqlite3
from datetime import datetime, timezone, timedelta
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RF_DIR     = r"C:\Users\kurt_\Betrieb\Radio Fernsehen"
DB_PATH    = os.path.join(RF_DIR, "Backlink_Broadcast_Fit.db")
CSV_SHOWS  = os.path.join(RF_DIR, "Backlink_Broadcast_DB_Sendungen.csv")
CSV_TRACKS = os.path.join(RF_DIR, "Backlink_Broadcast_DB_Titel.csv")
CSV_FIT    = os.path.join(RF_DIR, "Backlink_Broadcast_DB_Fit_Matrix.csv")

BB_JSON    = r"C:\Users\kurt_\.openclaw\workspace\andon-fm-library\bb_only.json"
SCH_CSV    = os.path.join(RF_DIR, "andon-fm-schedule-history.csv")
MUSIC_LOG  = os.path.join(RF_DIR, "Andon FM Station logs.txt.music.txt")
TITEL_CSV  = os.path.join(RF_DIR, "Backlink_Broadcast_Titelbewertung.csv")

MESZ = timezone(timedelta(hours=2))

def utc_to_vienna(dt_utc_naive):
    """Converts naive UTC datetime to naive Europe/Vienna local time (MESZ=UTC+2 before 2026-10-25 01:00 UTC, MEZ=UTC+1 from 2026-10-25 01:00 UTC)."""
    if dt_utc_naive < datetime(2026, 10, 25, 1, 0, 0):
        return dt_utc_naive + timedelta(hours=2)
    else:
        return dt_utc_naive + timedelta(hours=1)

def show_start_key_from_utc(dt_utc_naive):
    """Returns unique 'YYYY-MM-DD HH:MM' key in Vienna time; disambiguates the double 02:00 hour on 2026-10-25."""
    dt_loc = utc_to_vienna(dt_utc_naive)
    if dt_utc_naive == datetime(2026, 10, 25, 1, 0, 0):
        return "2026-10-25 02:01"
    return dt_loc.strftime('%Y-%m-%d %H:%M')


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())

def canonical_show_id(show_name):
    return norm(str(show_name).strip())

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            show_id TEXT PRIMARY KEY,
            slot_hm TEXT,
            show_name TEXT,
            show_desc TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            track_id TEXT PRIMARY KEY,
            artist TEXT,
            title TEXT,
            full_name TEXT,
            file_id TEXT,
            play_count_total INTEGER,
            last_played_mesz TEXT,
            last_slot_hm TEXT,
            last_show_name TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS track_show_fit (
            show_id TEXT,
            track_id TEXT,
            show_name TEXT,
            full_name TEXT,
            fit_score_avg REAL,
            fit_score_last INTEGER,
            eval_count INTEGER,
            source TEXT,
            reason TEXT,
            updated_at TEXT,
            PRIMARY KEY (show_id, track_id)
        )
    """)
    conn.commit()
    return conn

def compute_cooldown_hours(fit_score, same_slot=False, pool_size=30):
    f = float(fit_score)
    if not same_slot:
        if f >= 9.5: return 10.0
        elif f >= 8.5: return 15.0
        elif f >= 7.5: return 22.0
        elif f >= 6.5: return 36.0
        elif f >= 5.0: return 48.0
        elif f >= 3.0: return 96.0
        else: return 168.0
    else:
        pool_factor = max(60.0, min(120.0, (pool_size / 12.0) * 24.0))
        if f >= 8.5: return max(60.0, pool_factor * 0.85)
        elif f >= 7.0: return max(72.0, pool_factor)
        elif f >= 5.0: return 120.0
        elif f >= 3.0: return 168.0
        else: return 240.0

def sync_shows_and_tracks(conn=None):
    close_after = False
    if conn is None:
        conn = get_conn()
        close_after = True
    now_str = datetime.now(MESZ).strftime("%Y-%m-%d %H:%M:%S")
    show_by_hour_prefix = {}
    all_seen_shows = {}
    if os.path.exists(SCH_CSV):
        with open(SCH_CSV, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            next(reader, None)
            for r in reader:
                if not r or len(r) < 6 or r[1] != "Backlink Broadcast":
                    continue
                ts_mesz, st, s_name, start_utc, dur, s_desc = r
                try:
                    dt_utc = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).replace(tzinfo=None)
                    dt_start = utc_to_vienna(dt_utc)
                    slot_hm = dt_start.strftime("%H:%M")
                    s_name = s_name.strip()
                    s_desc = s_desc.strip()
                    show_by_hour_prefix[dt_start.strftime("%Y-%m-%d %H")] = s_name
                    if dt_start >= datetime(2026, 10, 15, 0, 0):
                        sid = canonical_show_id(s_name)
                        if sid not in all_seen_shows or len(s_desc) >= len(all_seen_shows[sid][2]):
                            all_seen_shows[sid] = (slot_hm, s_name, s_desc)
                        else:
                            all_seen_shows[sid] = (slot_hm, s_name, all_seen_shows[sid][2])
                except Exception:
                    pass
    cur = conn.cursor()
    for sid, (slot_hm, s_name, s_desc) in all_seen_shows.items():
        cur.execute("""
            INSERT INTO shows (show_id, slot_hm, show_name, show_desc, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(show_id) DO UPDATE SET
                slot_hm = excluded.slot_hm,
                show_name = excluded.show_name,
                show_desc = CASE WHEN length(excluded.show_desc) >= length(shows.show_desc) THEN excluded.show_desc ELSE shows.show_desc END,
                updated_at = excluded.updated_at
        """, (sid, slot_hm, s_name, s_desc, now_str))

    last_log_play = {}
    log_counts = defaultdict(int)
    pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Backlink Broadcast \| MUSIC: (.+?) \| Start:")
    if os.path.exists(MUSIC_LOG):
        with open(MUSIC_LOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Backlink Broadcast" in line:
                    m = pattern.match(line.strip())
                    if m:
                        ts_str, tr = m.group(1), m.group(2).strip()
                        tid = norm(tr)
                        log_counts[tid] += 1
                        slot_hm = ts_str[11:13] + ":00"
                        sh_name = show_by_hour_prefix.get(ts_str[:13], "")
                        last_log_play[tid] = (ts_str, slot_hm, sh_name)

    if os.path.exists(BB_JSON):
        with open(BB_JSON, "r", encoding="utf-8") as f:
            bb_lib = json.load(f)
        for item in bb_lib:
            art = item.get("artist", "").strip()
            tit = item.get("title", "").strip()
            full = art + " - " + tit
            tid = norm(full)
            fid = str(item.get("file_id", ""))
            p_tot = max(int(item.get("play_count_total", 0) or 0), log_counts.get(tid, 0))
            json_lp = (item.get("last_played_vienna") or item.get("last_played") or "")[:19]
            log_info = last_log_play.get(tid)
            if log_info and log_info[0] >= json_lp:
                best_lp, last_slot, last_sh = log_info
            else:
                best_lp = json_lp
                last_slot = (best_lp[11:13] + ":00") if len(best_lp) >= 13 else ""
                last_sh = show_by_hour_prefix.get(best_lp[:13], "") if len(best_lp) >= 13 else ""
            cur.execute("""
                INSERT INTO tracks (track_id, artist, title, full_name, file_id, play_count_total, last_played_mesz, last_slot_hm, last_show_name, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    artist = excluded.artist,
                    title = excluded.title,
                    full_name = excluded.full_name,
                    file_id = excluded.file_id,
                    play_count_total = excluded.play_count_total,
                    last_played_mesz = excluded.last_played_mesz,
                    last_slot_hm = excluded.last_slot_hm,
                    last_show_name = excluded.last_show_name,
                    updated_at = excluded.updated_at
            """, (tid, art, tit, full, fid, p_tot, best_lp, last_slot, last_sh, now_str))
    conn.commit()
    if close_after:
        export_csv_mirrors(conn)
        conn.close()

def is_known_schedule_show(show_name):
    """Returns True if show_name matches an existing show in the 'shows' table (from the real schedule)."""
    sid = canonical_show_id(show_name)
    if not sid:
        return False
    conn = get_conn()
    sync_shows_and_tracks(conn)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM shows WHERE show_id = ?", (sid,))
    found = cur.fetchone() is not None
    conn.close()
    return found

def record_fit_scores(show_name, show_desc, slot_hm, evaluations, source_label="eval"):
    if not evaluations:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    now_str = datetime.now(MESZ).strftime("%Y-%m-%d %H:%M:%S")
    sid = canonical_show_id(show_name)
    cur.execute("""
        INSERT INTO shows (show_id, slot_hm, show_name, show_desc, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(show_id) DO UPDATE SET
            slot_hm = COALESCE(NULLIF(excluded.slot_hm, ""), shows.slot_hm),
            show_name = excluded.show_name,
            show_desc = CASE WHEN length(excluded.show_desc) > length(COALESCE(shows.show_desc, "")) THEN excluded.show_desc ELSE shows.show_desc END,
            updated_at = excluded.updated_at
    """, (sid, slot_hm or "", show_name.strip(), (show_desc or "").strip(), now_str))
    saved = 0
    for ev in evaluations:
        full = str(ev.get("full_name", "")).strip()
        if not full or ev.get("score") is None:
            continue
        sc = int(ev["score"])
        reason = str(ev.get("reason", "")).strip()
        if reason == "Standard-Einstufung":
            continue
        tid = norm(full)
        cur.execute("SELECT fit_score_avg, eval_count, reason FROM track_show_fit WHERE show_id = ? AND track_id = ?", (sid, tid))
        row = cur.fetchone()
        if row:
            old_avg = float(row["fit_score_avg"])
            old_cnt = int(row["eval_count"])
            new_cnt = old_cnt + 1
            new_avg = round((old_avg * old_cnt + sc) / new_cnt, 2)
            best_reason = reason if len(reason) >= len(row["reason"] or "") else row["reason"]
            cur.execute("""
                UPDATE track_show_fit
                SET fit_score_avg = ?, fit_score_last = ?, eval_count = ?, source = ?, reason = ?, updated_at = ?
                WHERE show_id = ? AND track_id = ?
            """, (new_avg, sc, new_cnt, source_label, best_reason, now_str, sid, tid))
        else:
            cur.execute("""
                INSERT INTO track_show_fit (show_id, track_id, show_name, full_name, fit_score_avg, fit_score_last, eval_count, source, reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """, (sid, tid, show_name.strip(), full, float(sc), sc, source_label, reason, now_str))
        saved += 1
    conn.commit()
    export_csv_mirrors(conn)
    conn.close()
    return saved

def import_existing_titelbewertung_csv():
    if not os.path.exists(TITEL_CSV):
        return 0
    conn = get_conn()
    sync_shows_and_tracks(conn)
    cur = conn.cursor()
    cur.execute("DELETE FROM track_show_fit WHERE source = 'evaluate_show_playlist'")
    conn.commit()
    conn.close()
    by_show = defaultdict(list)
    show_meta = {}
    with open(TITEL_CSV, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for r in reader:
            r = {(k.lstrip("\ufeff").strip() if k else ""): v for k, v in r.items()}
            st_show = r.get("Startzeit_Show", "").strip()
            s_name = r.get("Show_Name", "").strip()
            s_desc = r.get("Show_Beschreibung", "").strip()
            full = r.get("Interpret_Titel", "").strip()
            sc_str = r.get("Fit_Score", "").strip()
            reason = r.get("Begruendung", "").strip()
            if s_name and full and sc_str.isdigit():
                slot_hm = st_show.split(" ")[1] if " " in st_show else ""
                show_meta[s_name] = (s_desc, slot_hm)
                by_show[s_name].append({
                    "full_name": full,
                    "score": int(sc_str),
                    "reason": reason
                })
    total_imported = 0
    for s_name, ev_list in by_show.items():
        s_desc, slot_hm = show_meta[s_name]
        total_imported += record_fit_scores(s_name, s_desc, slot_hm, ev_list, source_label="evaluate_show_playlist")
    return total_imported

def export_csv_mirrors(conn=None):
    close_after = False
    if conn is None:
        conn = get_conn()
        close_after = True
    cur = conn.cursor()
    cur.execute("""
        SELECT s.show_id, s.slot_hm, s.show_name, s.show_desc,
               COUNT(f.track_id) AS rated_tracks,
               SUM(CASE WHEN f.fit_score_avg >= 7.0 THEN 1 ELSE 0 END) AS pool_ge_7,
               SUM(CASE WHEN f.fit_score_avg >= 4.0 THEN 1 ELSE 0 END) AS pool_ge_4,
               s.updated_at
        FROM shows s
        LEFT JOIN track_show_fit f ON s.show_id = f.show_id
        GROUP BY s.show_id
        ORDER BY s.slot_hm, s.show_name
    """)
    with open(CSV_SHOWS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Show_ID", "Slot_MESZ", "Show_Name", "Show_Beschreibung", "Bewertete_Titel", "Pool_Fit_ab_7", "Pool_Fit_ab_4", "Aktualisiert"])
        for r in cur.fetchall():
            w.writerow([r["show_id"], r["slot_hm"], r["show_name"], r["show_desc"], r["rated_tracks"], r["pool_ge_7"] or 0, r["pool_ge_4"] or 0, r["updated_at"]])

    cur.execute("SELECT * FROM tracks ORDER BY last_played_mesz ASC, full_name ASC")
    with open(CSV_TRACKS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Track_ID", "Interpret", "Titel", "Interpret_Titel", "Plays_Gesamt", "Zuletzt_Gespielt_MESZ", "Letzter_Slot", "Letzte_Sendung"])
        for r in cur.fetchall():
            w.writerow([r["track_id"], r["artist"], r["title"], r["full_name"], r["play_count_total"], r["last_played_mesz"], r["last_slot_hm"], r["last_show_name"]])

    cur.execute("""
        SELECT f.show_name, s.slot_hm, f.full_name, f.fit_score_avg, f.fit_score_last,
               f.eval_count, f.source, f.reason, t.last_played_mesz, t.last_slot_hm, f.updated_at
        FROM track_show_fit f
        LEFT JOIN shows s ON f.show_id = s.show_id
        LEFT JOIN tracks t ON f.track_id = t.track_id
        ORDER BY s.slot_hm ASC, f.show_name ASC, f.fit_score_avg DESC, t.last_played_mesz ASC
    """)
    with open(CSV_FIT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Slot_MESZ", "Show_Name", "Interpret_Titel", "Fit_Score_Avg", "Fit_Score_Last", "Anzahl_Wertungen", "Quelle", "Begruendung", "Zuletzt_Gespielt_MESZ", "Letzter_Slot", "Aktualisiert"])
        for r in cur.fetchall():
            w.writerow([r["slot_hm"], r["show_name"], r["full_name"], r["fit_score_avg"], r["fit_score_last"], r["eval_count"], r["source"], r["reason"], r["last_played_mesz"], r["last_slot_hm"], r["updated_at"]])
    if close_after:
        conn.close()

def get_last_plays_before(ref_dt):
    """Scans MUSIC_LOG up to ref_dt and returns {track_id: (ts_str, slot_hm)} before ref_dt."""
    ref_str = ref_dt.strftime("%Y-%m-%d %H:%M:%S")
    last_map = {}
    pattern = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| Backlink Broadcast \| MUSIC: (.+?) \| Start:")
    if os.path.exists(MUSIC_LOG):
        with open(MUSIC_LOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Backlink Broadcast" in line:
                    m = pattern.match(line.strip())
                    if m:
                        ts_str, tr = m.group(1), m.group(2).strip()
                        if ts_str < ref_str:
                            last_map[norm(tr)] = (ts_str, ts_str[11:13] + ":00")
                        else:
                            break
    return last_map

def generate_playlist_from_db(query_str, ref_dt=None, top_n=12):
    conn = get_conn()
    sync_shows_and_tracks(conn)
    cur = conn.cursor()
    historical_mode = (ref_dt is not None)
    if ref_dt is None:
        ref_dt = datetime.now(MESZ).replace(tzinfo=None)
    hist_map = get_last_plays_before(ref_dt) if historical_mode else None
    q_clean = query_str.strip()
    cur.execute("""
        SELECT s.show_id, s.slot_hm, s.show_name, s.show_desc,
               (SELECT COUNT(*) FROM track_show_fit f WHERE f.show_id = s.show_id) AS f_cnt
        FROM shows s
        WHERE s.slot_hm = ? OR s.show_id = ? OR lower(s.show_name) LIKE ?
        ORDER BY f_cnt DESC, s.updated_at DESC LIMIT 1
    """, (q_clean, norm(q_clean), "%" + q_clean.lower() + "%"))
    sh = cur.fetchone()
    if not sh:
        print("Keine Sendung gefunden fuer:", query_str)
        conn.close()
        return []
    sid = sh["show_id"]
    target_slot = sh["slot_hm"]
    cur.execute("""
        SELECT f.track_id, f.full_name, f.fit_score_avg, f.eval_count, f.reason,
               t.last_played_mesz, t.last_slot_hm, t.last_show_name
        FROM track_show_fit f
        JOIN tracks t ON f.track_id = t.track_id
        WHERE f.show_id = ?
    """, (sid,))
    rows = cur.fetchall()
    conn.close()
    pool_ge_7 = sum(1 for r in rows if float(r["fit_score_avg"]) >= 7.0)
    candidates = []
    for r in rows:
        fit = float(r["fit_score_avg"])
        if historical_mode and hist_map is not None:
            h_info = hist_map.get(r["track_id"])
            lp_str = h_info[0] if h_info else ""
            last_slot_val = h_info[1] if h_info else ""
        else:
            lp_str = r["last_played_mesz"] or ""
            last_slot_val = r["last_slot_hm"] or ""
        if lp_str:
            try:
                lp_dt = datetime.strptime(lp_str[:19], "%Y-%m-%d %H:%M:%S")
                h_unplayed = max(0.1, (ref_dt - lp_dt).total_seconds() / 3600.0)
            except Exception:
                h_unplayed = 720.0
        else:
            h_unplayed = 720.0
        same_slot = (bool(target_slot) and last_slot_val == target_slot)
        cd_h = compute_cooldown_hours(fit, same_slot=same_slot, pool_size=max(15, pool_ge_7))
        quotient = h_unplayed / cd_h
        candidates.append({
            "full_name": r["full_name"],
            "fit": fit,
            "h_unplayed": h_unplayed,
            "cd_h": cd_h,
            "quotient": quotient,
            "same_slot": same_slot,
            "last_played": lp_str[:16] if lp_str else "Nie",
            "last_slot": last_slot_val or "-",
            "reason": r["reason"] or ""
        })
    candidates.sort(key=lambda x: (-x["quotient"], -x["fit"], -x["h_unplayed"]))
    print("=" * 105)
    print("DATENBANK-PLAYLIST-GENERATOR (KURTS QUOTIENTEN-FORMEL: ZEIT UNGESPIELT / COOLDOWN)")
    print("Sendung : [" + str(target_slot) + " Uhr] " + sh["show_name"])
    print("Pool DB : " + str(len(rows)) + " bewertete Titel (davon " + str(pool_ge_7) + " mit Fit >= 7.0)")
    print("=" * 105)
    for i, c in enumerate(candidates[:top_n], 1):
        sl_flag = "GLEICH" if c["same_slot"] else "anders"
        print(f"{i:2d} | {c['quotient']:7.2f}x | {c['h_unplayed']:5.1f}h ({c['h_unplayed']/24:4.1f}d) | {c['cd_h']:6.0f}h  | Fit {c['fit']:4.1f} | {sl_flag:6s} | {c['full_name'][:40]:40s} | {c['reason'][:38]}")
    print("=" * 105)
    return candidates[:top_n]

def print_db_stats():
    conn = get_conn()
    sync_shows_and_tracks(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tracks")
    n_tracks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM track_show_fit")
    n_fits = cur.fetchone()[0]
    cur.execute("""
        SELECT s.slot_hm, s.show_name, COUNT(f.track_id) AS cnt,
               SUM(CASE WHEN f.fit_score_avg >= 7 THEN 1 ELSE 0 END) AS ge7,
               SUM(CASE WHEN f.fit_score_avg >= 4 THEN 1 ELSE 0 END) AS ge4,
               AVG(f.fit_score_avg) AS avg_fit
        FROM shows s
        JOIN track_show_fit f ON s.show_id = f.show_id
        GROUP BY s.show_id
        ORDER BY s.slot_hm ASC
    """)
    rows = cur.fetchall()
    conn.close()
    print("\n" + "=" * 90)
    print("STATUS DER FIT-DATENBANK (" + DB_PATH + ")")
    print("Gesamt-Archivtitel in Tabelle tracks       : " + str(n_tracks))
    print("Gespeicherte (Titel x Sendung)-Fit-Wertungen: " + str(n_fits))
    print("=" * 90)
    for r in rows:
        sh_slot = r["slot_hm"] or "-"
        sh_name = r["show_name"][:44]
        cnt = r["cnt"]
        ge7 = r["ge7"] or 0
        ge4 = r["ge4"] or 0
        af = r["avg_fit"] or 0.0
        print(f"{sh_slot:5s} | {sh_name:44s} | Bewertet: {cnt:3d} | Fit>=7: {ge7:3d} | Fit>=4: {ge4:3d} | Ø {af:4.1f}/10")
    print("=" * 90 + "\n")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "--sync" in args:
        n_imp = import_existing_titelbewertung_csv()
        print("Synchronisation abgeschlossen (" + str(n_imp) + " Einzelwertungen aus Titelbewertung.csv abgeglichen).")
        print_db_stats()
    elif "--stats" in args:
        print_db_stats()
    elif "--playlist" in args:
        idx = args.index("--playlist")
        q = args[idx + 1] if idx + 1 < len(args) else "18:00"
        ref_dt_arg = None
        if "--at" in args:
            a_idx = args.index("--at")
            if a_idx + 1 < len(args):
                ref_dt_arg = datetime.strptime(args[a_idx + 1].strip()[:16], "%Y-%m-%d %H:%M")
        top_n_arg = 12
        if "--top" in args:
            t_idx = args.index("--top")
            if t_idx + 1 < len(args):
                top_n_arg = int(args[t_idx + 1])
        generate_playlist_from_db(q, ref_dt=ref_dt_arg, top_n=top_n_arg)
