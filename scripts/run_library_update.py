import os
import subprocess
import json
import time
import sys
import shutil
from datetime import datetime

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GEN_ANDON_SCRIPT = os.path.join(SCRIPT_DIR, "generate_andon_library.py")
GEN_STATIONS_SCRIPT = os.path.join(SCRIPT_DIR, "generate_station_libraries.py")
REPO_DIR = os.path.dirname(SCRIPT_DIR)
STATE_FILE = os.path.join(SCRIPT_DIR, "periodic_library_state.json")

# Update interval for library (in seconds). 4 hours = 14400 seconds.
LIBRARY_UPDATE_INTERVAL = 14400

def log_event(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [AndonAuto] {msg}"
    print(line)
    # Log to moltbook_log.txt to keep all periodic output centralized
    log_file = os.path.join(os.path.dirname(REPO_DIR), "moltbook_log.txt")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log_event(f"Error reading state: {e}")
    return {"last_library_update": 0}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_event(f"Error saving state: {e}")

def run_cmd(args, cwd=None):
    try:
        res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            log_event(f"Command failed ({' '.join(args)}): {res.stderr.strip()}")
            return False
        return True
    except Exception as e:
        log_event(f"Failed to execute command {' '.join(args)}: {e}")
        return False

def check_and_update():
    state = load_state()
    now_ts = time.time()
    time_since_update = now_ts - state.get("last_library_update", 0)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    log_event(f"Checking library update schedule. Time since last update: {time_since_update/60:.1f} mins (Interval: {LIBRARY_UPDATE_INTERVAL/60:.1f} mins)")
    
    updated_now = False

    if time_since_update >= LIBRARY_UPDATE_INTERVAL:
        log_event("Interval reached. Starting Andon FM Library auto-update...")
        
        # Use currently running python interpreter
        python_exe = sys.executable
        
        # 1. Generate Andon Library HTML
        log_event("Generating HTML library...")
        ok_html = run_cmd([python_exe, GEN_ANDON_SCRIPT])
        if not ok_html:
            log_event("Error: Andon HTML library generation failed. Aborting Git push.")
            return
            
        # 2. Copy Andon Library HTML to repo index.html
        src_html = os.path.join(REPO_DIR, "andon-fm-library.html")
        dst_html = os.path.join(REPO_DIR, "index.html")
        log_event(f"Copying {src_html} to {dst_html}...")
        try:
            shutil.copy2(src_html, dst_html)
        except Exception as e:
            log_event(f"Error: HTML copy failed: {e}. Aborting Git push.")
            return

        # 3. Generate Station-specific JSON/CSV files directly in repo
        log_event("Generating Station-specific JSON/CSV exports...")
        ok_stations = run_cmd([python_exe, GEN_STATIONS_SCRIPT])
        if not ok_stations:
            log_event("Error: Station export generation failed. Aborting Git push.")
            return

        updated_now = True

        # 4. Git Add, Commit, Push
        log_event("Staging files in Git repository...")
        files_to_add = [
            "index.html",
            "bb_only.json", "bb_only.csv", "bb_only.html", "bb_longest_unplayed_top50.json", "bb_least_played_top50.json", "bb_missing.csv",
            "oa_only.json", "oa_only.csv", "oa_only.html", "oa_longest_unplayed_top50.json", "oa_least_played_top50.json", "oa_missing.csv",
            "tf_only.json", "tf_only.csv", "tf_only.html", "tf_longest_unplayed_top50.json", "tf_least_played_top50.json", "tf_missing.csv",
            "gnr_only.json", "gnr_only.csv", "gnr_only.html", "gnr_longest_unplayed_top50.json", "gnr_least_played_top50.json", "gnr_missing.csv"
        ]
        
        if run_cmd(["git", "add"] + files_to_add, cwd=REPO_DIR):
            commit_msg = f"Automated Library Update {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            # Note: We don't check return value of commit because if there are no changes,
            # git commit exits with code 1. We just run it.
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_DIR, capture_output=True)
            
            log_event("Pushing to GitHub remote...")
            if run_cmd(["git", "push"], cwd=REPO_DIR):
                log_event("Success! Library updated and pushed to GitHub.")
                state["last_library_update"] = now_ts
                save_state(state)
            else:
                log_event("Error: Git push to origin failed.")
        else:
            log_event("Error: Git add staged files failed.")
    else:
        log_event("Library update skipped (interval not reached).")

    # 5. Daily email delivery to DJ Claude
    # Only deliver if the library files were freshly regenerated in THIS run AND email hasn't been sent today
    if updated_now:
        if state.get("last_email_sent_date") != today_str:
            log_event("Library was freshly updated in this run. Triggering daily email delivery to DJ Claude...")
            try:
                from send_andon_library_mail import send_library_email
                send_library_email()
            except Exception as e:
                log_event(f"Error triggering library email: {e}")
        else:
            log_event(f"Library freshly updated, but daily email for today ({today_str}) was already sent earlier.")
    else:
        log_event("Skipping daily email check (library was not updated in this run).")

if __name__ == "__main__":
    check_and_update()
