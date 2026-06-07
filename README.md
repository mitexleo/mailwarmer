# Mail Warmer

A generic SMTP warm-up CLI tool. Gradually sends emails to a list of recipients
over multiple days to build sender reputation.

## Quick Start

```bash
# Install dependencies (for running via Python directly)
pip install openpyxl python-dotenv

# Create config from the example
cp .env.example .env
# Edit .env with your SMTP credentials, sender info, and subject

# Run day 1
python3 warmup.py -c .env -d recipients.xlsx -e body.html --day 1

# Or auto-run all days
python3 warmup.py -c .env -d recipients.csv -e body.html --auto
```

## CLI Usage

```
usage: warmup [-h] [-c CONFIG] -d DATA -e EMAIL [-s STATE] --day DAY | --auto

SMTP warm-up — gradually send emails to build sender reputation.

arguments:
  -c, --config CONFIG   Path to .env config file (default: ./.env)
  -d, --data DATA       Path to .xlsx or .csv file with recipient emails
  -e, --email EMAIL     Path to HTML email body file
  -s, --state STATE     Path to state JSON file (overrides STATE_FILE in config)

  --day DAY             Run a specific day number
  --auto                Run all days automatically with delays between them
```

## Configuration (.env)

| Variable | Required | Default | Description |
|---|---|---|---|
| `SMTP_HOST` | Yes | — | SMTP server hostname |
| `SMTP_PORT` | No | 25 | SMTP server port |
| `SMTP_USER` | Yes | — | SMTP username |
| `SMTP_PASS` | Yes | — | SMTP password |
| `USE_TLS` | No | false | Enable STARTTLS |
| `FROM_NAME` | Yes | — | Sender display name |
| `FROM_EMAIL` | Yes | — | Sender email address |
| `EMAIL_SUBJECT` | Yes | — | Email subject line |
| `WARMUP_DAYS` | No | 14 | Number of days to spread recipients across |
| `DELAY_BETWEEN_EMAILS` | No | 10 | Seconds between each email send |
| `DELAY_BETWEEN_DAYS` | No | 86400 | Seconds between days in auto mode |
| `STATE_FILE` | No | warmup_state.json | State tracking file |

## Data File

The `-d` flag accepts **.xlsx** or **.csv** files. The first column should contain
the recipient email addresses.

## Build from Source

```bash
pip install pyinstaller openpyxl python-dotenv
pyinstaller --onefile --name warmup warmup.py
./dist/warmup --help
```

## Install from Packages

Download the `.deb` (Debian/Ubuntu) or `.rpm` (RHEL/Fedora/CentOS) package from
the [Releases](https://github.com/mitexleo/mailwarmer/releases) page.

```bash
# Debian / Ubuntu
sudo dpkg -i warmup_*.deb

# RHEL / Fedora / CentOS
sudo rpm -i warmup_*.rpm
```

The binary will be installed at `/usr/local/bin/warmup`.
