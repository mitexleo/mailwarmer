# Mail Warmer

A desktop GUI (Qt6 / PySide6) tool for SMTP warm-up — gradually sends emails
to a list of recipients over multiple days to build sender reputation.

## Features

- **Qt6 GUI** — configure everything visually, no CLI required  
- **Dark theme** — consistent Fusion style across all platforms  
- **SMTP config** — host, port, user, password, TLS toggle — enter directly in the app  
- **Save / Load config** — settings persist to `~/.config/mailwarmer/` across sessions  
- **HTML email editor** — write or paste HTML directly in the Editor tab, or load from a file  
- **Recipients file** — browse for `.xlsx` or `.csv` (first column, one email per row)  
- **Auto-generated schedule** — distributes recipients across N days with gradual ramp-up  
- **Single day or auto mode** — run one day or chain all days automatically  
- **Pause / Resume** — state is saved after every email; close and resume later  
- **Live log & progress bar** — see sends in real time  
- **Self-update check** — notifies when a new release is available (with Download button)  
- **Flatpak support** — install, run, and update via Flatpak  
- **CLI fallback** — headless mode with `--cli` flag  

## Quick Start (from source)

```bash
pip install PySide6 openpyxl python-dotenv

cp .env.example .env
# Edit .env with your SMTP credentials (or enter them directly in the GUI)

python3 warmup.py
```

## Install via Flatpak

Download the latest `.flatpak` from the [Releases page](https://github.com/mitexleo/mailwarmer/releases).

```bash
flatpak install --user mailwarmer.flatpak
flatpak run io.github.mitexleo.mailwarmer
```

To update:
```bash
flatpak update io.github.mitexleo.mailwarmer
```

## Install via .deb / .rpm

Download from the [Releases page](https://github.com/mitexleo/mailwarmer/releases).

```bash
# Debian / Ubuntu
sudo dpkg -i warmup_1.4.4_amd64.deb

# RHEL / Fedora / CentOS
sudo rpm -i warmup-1.4.4-1.x86_64.rpm
```

Installed to `/usr/local/bin/warmup`.

## Direct Download

| File | Platform | Installation |
|------|----------|--------------|
| `warmup.exe` | Windows | Download and run the executable |
| `MailWarmer-1.5.6.dmg` | macOS | Download, open DMG, drag `MailWarmer.app` to Applications |

### macOS Notes

- **First launch:** Right-click `MailWarmer.app` → Open (instead of double-click) to bypass Gatekeeper for unsigned apps.
- **Apple Silicon (M1/M2/M3):** The app is built as a universal binary (`x86_64` + `arm64`) and runs natively.
- **Code signing:** For distribution without the security warning, an Apple Developer ID ($99/year) is required for full notarization. Until then, the app is ad-hoc signed for testing.

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

## Project Structure

```
warmup.py          — Qt GUI application (+ CLI fallback with --cli)
warmup_core.py     — shared SMTP logic (config, send, schedule, state)
flatpak/           — Flatpak packaging files
.github/workflows/ — CI pipeline (.deb, .rpm, .flatpak)
```

## AI Usage Disclosure

This project was developed with assistance from AI coding agents (Claude/DeepSeek)
for code generation, refactoring, and debugging. Specific AI-generated contributions
include:

- Initial CLI implementation and subsequent Qt GUI refactor
- SMTP warm-up scheduling algorithm
- GitHub Actions CI/CD pipeline for cross-platform packaging
- Self-update check functionality
- Help system and documentation
- Flatpak packaging support

All AI-generated code was reviewed, tested, and validated by the author before
inclusion. The author takes full responsibility for the project's functionality
and security.
