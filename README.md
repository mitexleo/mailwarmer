# Mail Warmer

A desktop GUI (Qt) tool for SMTP warm-up — gradually sends emails to a list of
recipients over multiple days to build sender reputation.

**Author:** Mueenul Islam — [hello@mueen.dev](mailto:hello@mueen.dev) — [https://mueen.dev](https://mueen.dev)

## Features

- **Qt GUI** — configure everything visually, no CLI needed
- **SMTP config** — host, port, user, pass, TLS toggle — enter directly in the app
- **Save/Load Config** — persist SMTP settings between sessions
- **Email body editor** — write or paste HTML directly, or load from a file
- **Recipients file** — browse for `.xlsx` or `.csv`
- **Auto-generated schedule** — distributes recipients across N days with gradual ramp-up
- **Single day or auto mode** — run one day or chain all days automatically
- **Pause/Resume** — state is saved after every email; close and resume later
- **Live log & progress bar** — see sends in real time
- **Self-update check** — notifies when a new release is available
- **Help guide** — built-in usage documentation
- **CLI fallback** — still works headless with `--cli` flag

## Quick Start

```bash
pip install PySide6 openpyxl python-dotenv

cp .env.example .env
# Edit .env with your SMTP credentials (or enter them directly in the GUI)

python3 warmup.py
```

## CLI Usage

```bash
python3 warmup.py --cli -c .env -d recipients.xlsx -e body.html --day 1
python3 warmup.py --cli -c .env -d recipients.csv -e body.html --auto
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

## Data File Format

The recipients file (`.xlsx` or `.csv`) should have one email address per row in
the first column. A header row is allowed but not required.

```
email@example.com
user2@domain.com
user3@domain.com
```

Or with a header:

```
Email
email@example.com
user2@domain.com
```

## Build from Source

```bash
pip install pyinstaller PySide6 openpyxl python-dotenv
pyinstaller --onefile --name warmup warmup.py warmup_core.py
./dist/warmup
```

## Install from Packages

Download `.deb` or `.rpm` from the [Releases page](https://github.com/mitexleo/mailwarmer/releases).

```bash
# Debian / Ubuntu
sudo dpkg -i warmup_*.deb

# RHEL / Fedora / CentOS
sudo rpm -i warmup_*.rpm
```

Installed to `/usr/local/bin/warmup`.

## AI Usage Disclosure

This project was developed with assistance from AI coding agents (Claude/DeepSeek)
for code generation, refactoring, and debugging. Specific AI-generated contributions
include:

- Initial CLI implementation and subsequent Qt GUI refactor
- SMTP warm-up scheduling algorithm
- GitHub Actions CI/CD pipeline for cross-platform packaging
- Self-update check functionality
- Help system and documentation

All AI-generated code was reviewed, tested, and validated by the author before
inclusion. The author takes full responsibility for the project's functionality
and security.
