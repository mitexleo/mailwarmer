# Mail Warmer

A generic SMTP warm-up script that gradually sends emails to recipients over multiple days to build sender reputation.

## Features

- **Generic** — configure everything via `.env`: SMTP, sender, recipient file, email content, schedule
- **Auto-generated schedule** — distributes recipients across N days with a gradual ramp-up
- **Template-based email body** — customize HTML and plain-text email bodies in separate files
- **Resumable** — tracks sent count per day in a JSON state file, safe to restart
- **Two modes** — run a single day or auto-run all days with configurable delays

## Quick Start

```bash
pip install openpyxl python-dotenv
cp .env.example .env
# Edit .env with your SMTP credentials, sender info, file paths, etc.
```

## Usage

```bash
# Run a specific day
python3 warmup.py --day 1

# Run all remaining days automatically (with delays between days)
python3 warmup.py --auto
```

## Configuration

All configuration is done via `.env`. See `.env.example` for all options.

| Variable | Required | Description |
|---|---|---|
| `SMTP_HOST` | Yes | SMTP server hostname |
| `SMTP_PORT` | No (25) | SMTP server port |
| `SMTP_USER` | Yes | SMTP username |
| `SMTP_PASS` | Yes | SMTP password |
| `USE_TLS` | No (false) | Enable STARTTLS |
| `FROM_NAME` | Yes | Sender display name |
| `FROM_EMAIL` | Yes | Sender email address |
| `XLSX_FILE` | Yes | Path to recipients xlsx file |
| `EMAIL_SUBJECT` | Yes | Email subject line |
| `TEXT_TEMPLATE` | No (email_body.txt.template) | Plain text template (HTML auto-generated from it) |
| `WARMUP_DAYS` | No (14) | Number of days to spread recipients across |
| `DELAY_BETWEEN_EMAILS` | No (10) | Seconds between each email send |
| `DELAY_BETWEEN_DAYS` | No (86400) | Seconds between days in auto mode |

## Email Templates

Edit `email_body.txt` (copy from `email_body.txt.template`) with your plain text content.
The script auto-generates `email_body.html` from it, wrapping paragraphs in HTML.
Use `{{FROM_NAME}}` as a placeholder — it will be replaced with the sender name.

Only HTML is sent (no text/plain part).

**File roles:**
- `email_body.txt.template` — example template (tracked in git)
- `email_body.txt` — your actual content (gitignored, copied from template)
- `email_body.html` — auto-generated from text (gitignored)

## State

Progress is tracked in `warmup_state.json` (configurable via `STATE_FILE`). The script resumes from where it left off if interrupted.
