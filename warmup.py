#!/usr/bin/env python3
"""
SMTP warm-up CLI — gradually sends emails to a list of recipients over multiple
days to build sender reputation.

Usage:
  warmup -c .env -d recipients.xlsx -e body.html --day 1
  warmup --config .env --data recipients.csv --email body.html --auto
"""

import argparse
import csv
import json
import logging
import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

# Optional — xlsx support
try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(env_path):
    """Load .env file and return a config dict."""
    load_dotenv(dotenv_path=env_path, override=True)

    cfg = {
        "smtp_host":      os.getenv("SMTP_HOST"),
        "smtp_port":      int(os.getenv("SMTP_PORT", "25")),
        "smtp_user":      os.getenv("SMTP_USER"),
        "smtp_pass":      os.getenv("SMTP_PASS"),
        "use_tls":        os.getenv("USE_TLS", "false").lower() == "true",
        "from_name":      os.getenv("FROM_NAME"),
        "from_email":     os.getenv("FROM_EMAIL"),
        "email_subject":  os.getenv("EMAIL_SUBJECT"),
        "warmup_days":    int(os.getenv("WARMUP_DAYS", "14")),
        "delay_emails":   int(os.getenv("DELAY_BETWEEN_EMAILS", "10")),
        "delay_days":     int(os.getenv("DELAY_BETWEEN_DAYS", "86400")),
        "state_file":     os.getenv("STATE_FILE", "warmup_state.json"),
    }

    required = ["smtp_host", "smtp_user", "smtp_pass", "from_name", "from_email", "email_subject"]
    missing = [k.upper() for k in required if not cfg[k]]
    if missing:
        raise SystemExit(
            f"Missing required env vars in {env_path}: {', '.join(missing)}\n"
            "See .env.example for a reference."
        )

    return cfg


# ── Recipient loader ──────────────────────────────────────────────────────────

def load_recipients(path):
    """Load email addresses from an XLSX or CSV file (first column)."""
    if not os.path.exists(path):
        raise SystemExit(f"Data file not found: {path}")

    ext = os.path.splitext(path)[1].lower()

    if ext == ".xlsx":
        if load_workbook is None:
            raise SystemExit(
                "openpyxl is required for .xlsx files. Install with: pip install openpyxl"
            )
        wb = load_workbook(path, read_only=True)
        ws = wb.active
        return [str(row[0]).strip() for row in ws.iter_rows(values_only=True) if row[0]]

    elif ext == ".csv":
        recipients = []
        with open(path, newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if row and row[0].strip():
                    recipients.append(row[0].strip())
        return recipients

    else:
        raise SystemExit(f"Unsupported file type: {ext}. Use .xlsx or .csv.")


# ── HTML loader ───────────────────────────────────────────────────────────────

def load_html_body(path):
    """Read and return the HTML email body from a file."""
    if not os.path.exists(path):
        raise SystemExit(f"Email HTML file not found: {path}")
    with open(path) as f:
        return f.read()


# ── Schedule ──────────────────────────────────────────────────────────────────

def build_schedule(total, days):
    """Generate a gradual ramp-up schedule over N days."""
    if days <= 0 or total <= 0:
        return {}

    schedule = {}
    for d in range(1, days + 1):
        if d == days:
            already = sum(schedule.values())
            schedule[d] = total - already
        else:
            ratio = (d / days)
            raw = max(1, round(total * ratio * (2 / (days + 1)) * d))
            already = sum(schedule.values())
            remaining = total - already
            schedule[d] = min(raw, remaining)

    return {d: q for d, q in schedule.items() if q > 0}


# ── State ─────────────────────────────────────────────────────────────────────

def load_state(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"sent_index": 0, "last_day": 0}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


# ── Sender ────────────────────────────────────────────────────────────────────

def build_message(to_email, cfg, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = cfg["email_subject"]
    msg["From"]    = f'{cfg["from_name"]} <{cfg["from_email"]}>'
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html"))
    return msg


def send_batch(recipients, count, state, cfg, html_body, log):
    start = state["sent_index"]
    batch = recipients[start:start + count]

    if not batch:
        log.info("No more recipients to send to.")
        return 0

    log.info("Connecting to %s:%s ...", cfg["smtp_host"], cfg["smtp_port"])
    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as smtp:
            smtp.ehlo()
            if cfg["use_tls"]:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(cfg["smtp_user"], cfg["smtp_pass"])
            log.info("Authenticated OK.")

            sent = 0
            for email in batch:
                try:
                    msg = build_message(email, cfg, html_body)
                    smtp.sendmail(cfg["from_email"], [email], msg.as_string())
                    log.info("  ✓ Sent to %s", email)
                    sent += 1
                    state["sent_index"] += 1
                    save_state(cfg["state_file"], state)
                    if email != batch[-1]:
                        time.sleep(cfg["delay_emails"])
                except smtplib.SMTPException as e:
                    log.warning("  ✗ Failed %s: %s", email, e)

    except Exception as e:
        log.error("SMTP connection error: %s", e)
        return 0

    return sent


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="warmup",
        description="SMTP warm-up — gradually send emails to build sender reputation.",
    )
    p.add_argument("-c", "--config",  default=".env",
                   help="Path to .env config file (default: ./.env)")
    p.add_argument("-d", "--data",    required=True,
                   help="Path to .xlsx or .csv file with recipient email addresses")
    p.add_argument("-e", "--email",   required=True,
                   help="Path to HTML email body file")
    p.add_argument("-s", "--state",
                   help="Path to state JSON file (overrides STATE_FILE in config)")

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--day",  type=int,
                      help="Run a specific day number")
    mode.add_argument("--auto", action="store_true",
                      help="Run all days automatically with delays between them")
    return p


def main():
    args = build_parser().parse_args()

    # Load config
    cfg = load_config(args.config)

    # CLI overrides
    if args.state:
        cfg["state_file"] = args.state

    # Load data
    recipients = load_recipients(args.data)
    log.info("Loaded %d recipients from %s", len(recipients), args.data)

    # Load email HTML
    html_body = load_html_body(args.email)
    log.info("Loaded HTML body from %s (%d bytes)", args.email, len(html_body))

    # Build schedule
    schedule = build_schedule(len(recipients), cfg["warmup_days"])
    log.info("Schedule over %d days: %s", len(schedule), dict(schedule))

    # Load state
    state = load_state(cfg["state_file"])
    log.info("State: sent_index=%d, last_day=%d", state["sent_index"], state["last_day"])

    def run_day(day):
        quota = schedule.get(day)
        if quota is None:
            log.error("Day %d is not in the schedule. Check WARMUP_DAYS.", day)
            return
        log.info("=== Day %d: sending up to %d emails ===", day, quota)
        sent = send_batch(recipients, quota, state, cfg, html_body, log)
        state["last_day"] = day
        save_state(cfg["state_file"], state)
        log.info("=== Day %d done: sent %d, total sent %d ===", day, sent, state["sent_index"])

    if args.day:
        run_day(args.day)
    elif args.auto:
        start_day = state["last_day"] + 1
        for day in range(start_day, max(schedule.keys()) + 1):
            run_day(day)
            if day < max(schedule.keys()) and state["sent_index"] < len(recipients):
                log.info("Sleeping %ds before day %d ...", cfg["delay_days"], day + 1)
                time.sleep(cfg["delay_days"])


# ── Entry point ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("warmup")

if __name__ == "__main__":
    main()
