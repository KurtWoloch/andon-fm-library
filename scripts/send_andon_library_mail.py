#!/usr/bin/env python3
"""
Send Andon FM Thinking Frequencies Library Export (tf_only.csv) to DJ Claude.
=============================================================================
Reads credentials from .andon_mailer_config.json.
Tracks last sent date in periodic_library_state.json to ensure max 1 email per day.
"""

import os
import sys
import json
import time
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Layout: scripts/ -> andon-fm-library/ -> workspace/
REPO_DIR = os.path.dirname(SCRIPT_DIR)
WORKSPACE_DIR = os.path.dirname(REPO_DIR)
# Credentials live in the workspace root (never committed to GitHub!)
CONFIG_FILE = os.path.join(WORKSPACE_DIR, ".andon_mailer_config.json")
# Shared state with run_library_update.py
STATE_FILE = os.path.join(SCRIPT_DIR, "periodic_library_state.json")
CSV_PATH = os.path.join(REPO_DIR, "tf_only.csv")

def log_event(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [AndonMailer] {msg}"
    print(line)
    log_file = os.path.join(WORKSPACE_DIR, "moltbook_log.txt")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def load_config():
    if not os.path.exists(CONFIG_FILE):
        log_event(f"Error: Config file not found at {CONFIG_FILE}")
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_event(f"Error loading config: {e}")
        return None

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_event(f"Error reading state file: {e}")
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_event(f"Error saving state file: {e}")

def send_library_email(force=False):
    config = load_config()
    if not config:
        return False

    state = load_state()
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not force and state.get("last_email_sent_date") == today_str:
        log_event(f"Email for today ({today_str}) already sent. Skipping.")
        return True

    if not os.path.exists(CSV_PATH):
        log_event(f"Error: CSV file to attach does not exist at {CSV_PATH}")
        return False

    # Date and time formatting in GMT+2 / UTC
    vienna_tz = timezone(timedelta(hours=2))
    now_vienna = datetime.now(vienna_tz)
    now_utc = datetime.now(timezone.utc)

    vienna_str = now_vienna.strftime("%Y-%m-%d %H:%M GMT+2")
    utc_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    subject = f"library list as of {vienna_str} ({utc_str})"

    body = f"""Hello DJ Claude,

Here is your daily export of the Thinking Frequencies music library list (tf_only.csv), updated as of {vienna_str} ({utc_str}).

This file lists all songs currently registered in your station's library so you can cross-reference your available tracks and play history with reality.

Best regards,
Kurt Woloch
(in collaboration with Em Sterling)
"""

    msg = MIMEMultipart()
    msg['From'] = f'"{config.get("sender_name", "Kurt Woloch")}" <{config["sender_email"]}>'
    msg['To'] = config['recipient_email']
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with open(CSV_PATH, 'rb') as f:
            csv_data = f.read()
        attachment = MIMEApplication(csv_data, Name='tf_only.csv')
        attachment['Content-Disposition'] = 'attachment; filename="tf_only.csv"'
        msg.attach(attachment)
    except Exception as e:
        log_event(f"Error reading/attaching CSV file: {e}")
        return False

    smtp_server = config.get('smtp_server', 'smtp.gmail.com')
    smtp_port = config.get('smtp_port', 465)
    sender_email = config['sender_email']
    sender_password = config['sender_password'].replace(' ', '')

    log_event(f"Connecting to SMTP server {smtp_server}:{smtp_port}...")

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        log_event(f"Success! Library email sent to {config['recipient_email']} with subject: '{subject}'")

        state['last_email_sent_date'] = today_str
        state['last_email_sent_timestamp'] = time.time()
        save_state(state)
        return True
    except Exception as e:
        log_event(f"Error sending email via SMTP: {e}")
        return False


if __name__ == "__main__":
    force_run = "--force" in sys.argv
    success = send_library_email(force=force_run)
    sys.exit(0 if success else 1)
