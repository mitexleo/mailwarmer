#!/usr/bin/env python3
"""
Mail Warmer — SMTP warm-up GUI

Usage:
  python3 warmup.py                  # launch GUI
  python3 warmup.py --cli ...args    # fallback to CLI mode
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
    QSpinBox, QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from warmup_core import (
    __version__,
    load_config,
    load_recipients,
    load_html_body,
    build_schedule,
    load_state,
    save_state,
    send_batch,
)

try:
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
    HAS_NETWORK = True
except ImportError:
    HAS_NETWORK = False


# ── Log handler that emits Qt signals ─────────────────────────────────────────

class LogSignal(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, signal: LogSignal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.message.emit(msg)


# ── Background worker ─────────────────────────────────────────────────────────

class WarmupWorker(QObject):
    log_signal = Signal(str)
    progress_signal = Signal(int, int)   # current, total
    day_done = Signal(int, int)          # day, total_sent
    finished = Signal()
    error = Signal(str)

    def __init__(self, recipients, schedule, state, cfg, html_body, day=None, auto=False):
        super().__init__()
        self.recipients = recipients
        self.schedule = schedule
        self.state = state
        self.cfg = cfg
        self.html_body = html_body
        self.day = day
        self.auto = auto
        self._stop = False

    def stop(self):
        self._stop = True

    def _log(self, msg):
        self.log_signal.emit(msg)

    def _progress(self, current, total):
        self.progress_signal.emit(current, total)

    def run(self):
        # Redirect a logger to our signals so send_batch can use it
        logger = logging.getLogger("warmup.worker")
        logger.setLevel(logging.INFO)
        handler = QtLogHandler(LogSignal())
        handler.signal.message.connect(self._log)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)

        def progress_cb(cur, total):
            self._progress(cur, total)

        try:
            if self.day:
                self._run_day(self.day, logger, progress_cb)
            elif self.auto:
                start_day = self.state["last_day"] + 1
                for d in range(start_day, max(self.schedule.keys()) + 1):
                    if self._stop:
                        logger.info("Stopped by user.")
                        break
                    self._run_day(d, logger, progress_cb)
                    if d < max(self.schedule.keys()) and self.state["sent_index"] < len(self.recipients):
                        if self._stop:
                            break
                        logger.info("Sleeping %ds before day %d ...", self.cfg["delay_days"], d + 1)
                        # Sleep in small increments so we can be interrupted
                        for _ in range(self.cfg["delay_days"]):
                            if self._stop:
                                break
                            time.sleep(1)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def _run_day(self, day, logger, progress_cb):
        quota = self.schedule.get(day)
        if quota is None:
            logger.error("Day %d is not in the schedule.", day)
            return
        logger.info("=== Day %d: sending up to %d emails ===", day, quota)
        sent = send_batch(self.recipients, quota, self.state, self.cfg, self.html_body, logger, progress_cb)
        self.state["last_day"] = day
        save_state(self.cfg["state_file"], self.state)
        logger.info("=== Day %d done: sent %d, total sent %d ===", day, sent, self.state["sent_index"])
        self.day_done.emit(day, self.state["sent_index"])


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.worker_thread = None

        self.setWindowTitle(f"Mail Warmer v{__version__}")
        self.setMinimumSize(720, 680)

        self._build_ui()
        self._build_menu()
        self._check_for_update()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        # ─ SMTP ─
        smtp_group = QGroupBox("SMTP Configuration")
        smtp_form = QFormLayout(smtp_group)
        self.smtp_host = QLineEdit(); smtp_form.addRow("Host:", self.smtp_host)
        self.smtp_port = QSpinBox(); self.smtp_port.setRange(1, 65535); self.smtp_port.setValue(25)
        smtp_form.addRow("Port:", self.smtp_port)
        self.smtp_user = QLineEdit(); smtp_form.addRow("User:", self.smtp_user)
        self.smtp_pass = QLineEdit(); self.smtp_pass.setEchoMode(QLineEdit.Password)
        smtp_form.addRow("Pass:", self.smtp_pass)
        self.use_tls = QCheckBox("Enable STARTTLS"); smtp_form.addRow("", self.use_tls)
        layout.addWidget(smtp_group)

        # ─ Sender ─
        sender_group = QGroupBox("Sender & Email")
        sender_form = QFormLayout(sender_group)
        self.from_name = QLineEdit(); sender_form.addRow("From name:", self.from_name)
        self.from_email = QLineEdit(); sender_form.addRow("From email:", self.from_email)
        self.email_subject = QLineEdit(); sender_form.addRow("Subject:", self.email_subject)
        layout.addWidget(sender_group)

        # ─ Files ─
        files_group = QGroupBox("Files")
        files_form = QFormLayout(files_group)

        data_row = QHBoxLayout()
        self.data_path = QLineEdit(); self.data_path.setPlaceholderText("Path to .xlsx or .csv …")
        data_row.addWidget(self.data_path)
        btn_data = QPushButton("Browse…"); btn_data.clicked.connect(lambda: self._browse(self.data_path, "Data files (*.xlsx *.csv)"))
        data_row.addWidget(btn_data)
        files_form.addRow("Recipients:", data_row)

        html_row = QHBoxLayout()
        self.html_path = QLineEdit(); self.html_path.setPlaceholderText("Path to .html email body …")
        html_row.addWidget(self.html_path)
        btn_html = QPushButton("Browse…"); btn_html.clicked.connect(lambda: self._browse(self.html_path, "HTML files (*.html *.htm)"))
        html_row.addWidget(btn_html)
        files_form.addRow("Email HTML:", html_row)

        cfg_row = QHBoxLayout()
        self.config_path = QLineEdit(".env"); self.config_path.setPlaceholderText("Path to .env …")
        cfg_row.addWidget(self.config_path)
        btn_cfg = QPushButton("Browse…"); btn_cfg.clicked.connect(lambda: self._browse(self.config_path, "Env files (*.env)"))
        cfg_row.addWidget(btn_cfg)
        files_form.addRow("Config:", cfg_row)

        btn_load = QPushButton("Load Config & Preview")
        btn_load.clicked.connect(self._load_config_into_ui)
        files_form.addRow("", btn_load)

        layout.addWidget(files_group)

        # ─ Schedule & Controls ─
        sched_group = QGroupBox("Schedule & Controls")
        sched_layout = QVBoxLayout(sched_group)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Warmup days:"))
        self.warmup_days = QSpinBox(); self.warmup_days.setRange(1, 365); self.warmup_days.setValue(14)
        top_row.addWidget(self.warmup_days)
        top_row.addSpacing(20)
        top_row.addWidget(QLabel("Delay between emails (s):"))
        self.delay_email = QSpinBox(); self.delay_email.setRange(0, 3600); self.delay_email.setValue(10)
        top_row.addWidget(self.delay_email)
        top_row.addSpacing(20)
        top_row.addWidget(QLabel("Delay between days (s):"))
        self.delay_day = QSpinBox(); self.delay_day.setRange(0, 86400 * 7); self.delay_day.setValue(86400)
        top_row.addWidget(self.delay_day)
        top_row.addStretch()
        sched_layout.addLayout(top_row)

        mid_row = QHBoxLayout()
        self.mode_day = QRadioButton("Specific day")
        self.day_spin = QSpinBox(); self.day_spin.setRange(1, 365); self.day_spin.setValue(1)
        mid_row.addWidget(self.mode_day)
        mid_row.addWidget(self.day_spin)
        mid_row.addSpacing(20)
        self.mode_auto = QRadioButton("Auto (all days)")
        self.mode_auto.setChecked(True)
        mid_row.addWidget(self.mode_auto)
        mid_row.addStretch()
        sched_layout.addLayout(mid_row)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setMinimumWidth(120)
        self.btn_start.clicked.connect(self._start_warmup)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.setMinimumWidth(120)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_warmup)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()
        sched_layout.addLayout(btn_row)

        layout.addWidget(sched_group)

        # ─ Log ─
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(5000)
        self.log_output.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(self.log_output, stretch=1)

        # ─ Progress & Status ─
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(f"v{__version__} — ready")

    def _build_menu(self):
        menu = self.menuBar()
        help_menu = menu.addMenu("Help")
        about = QAction("About", self)
        about.triggered.connect(lambda: QMessageBox.about(self, "About Mail Warmer",
            f"<b>Mail Warmer v{__version__}</b><br><br>"
            "SMTP warm-up tool — gradually send emails to build sender reputation.<br><br>"
            "<a href='https://github.com/mitexleo/mailwarmer'>github.com/mitexleo/mailwarmer</a>"))
        help_menu.addAction(about)

        check = QAction("Check for Updates", self)
        check.triggered.connect(self._check_for_update)
        help_menu.addAction(check)

    # ── File browser ───────────────────────────────────────────────────────

    def _browse(self, line_edit, filter_str):
        path, _ = QFileDialog.getOpenFileName(self, "Select file", "", filter_str)
        if path:
            line_edit.setText(path)

    # ── Load .env into UI ──────────────────────────────────────────────────

    def _load_config_into_ui(self):
        env_path = self.config_path.text()
        if not os.path.exists(env_path):
            QMessageBox.warning(self, "File not found", f"Config file not found:\n{env_path}")
            return
        try:
            cfg = load_config(env_path)
        except ValueError as e:
            QMessageBox.warning(self, "Config error", str(e))
            return

        self.smtp_host.setText(cfg.get("smtp_host", ""))
        self.smtp_port.setValue(cfg.get("smtp_port", 25))
        self.smtp_user.setText(cfg.get("smtp_user", ""))
        self.smtp_pass.setText(cfg.get("smtp_pass", ""))
        self.use_tls.setChecked(cfg.get("use_tls", False))
        self.from_name.setText(cfg.get("from_name", ""))
        self.from_email.setText(cfg.get("from_email", ""))
        self.email_subject.setText(cfg.get("email_subject", ""))
        self.warmup_days.setValue(cfg.get("warmup_days", 14))
        self.delay_email.setValue(cfg.get("delay_emails", 10))
        self.delay_day.setValue(cfg.get("delay_days", 86400))

        # Try to load data and HTML preview
        data_path = self.data_path.text()
        html_path = self.html_path.text()
        if data_path and os.path.exists(data_path):
            try:
                recipients = load_recipients(data_path)
                self._log_msg(f"Loaded {len(recipients)} recipients from {data_path}")
            except Exception as e:
                self._log_msg(f"Error loading recipients: {e}")
        if html_path and os.path.exists(html_path):
            try:
                body = load_html_body(html_path)
                self._log_msg(f"Loaded HTML body ({len(body)} bytes)")
            except Exception as e:
                self._log_msg(f"Error loading HTML: {e}")

        # Build and show schedule preview
        if data_path and os.path.exists(data_path):
            try:
                recipients = load_recipients(data_path)
                sched = build_schedule(len(recipients), self.warmup_days.value())
                self._log_msg(f"Schedule ({len(sched)} days): {dict(sched)}")
            except Exception as e:
                self._log_msg(f"Schedule error: {e}")

        self.status.showMessage("Config loaded ✓")

    # ── Start / Stop ───────────────────────────────────────────────────────

    def _build_cfg_from_ui(self):
        return {
            "smtp_host": self.smtp_host.text(),
            "smtp_port": self.smtp_port.value(),
            "smtp_user": self.smtp_user.text(),
            "smtp_pass": self.smtp_pass.text(),
            "use_tls": self.use_tls.isChecked(),
            "from_name": self.from_name.text(),
            "from_email": self.from_email.text(),
            "email_subject": self.email_subject.text(),
            "warmup_days": self.warmup_days.value(),
            "delay_emails": self.delay_email.value(),
            "delay_days": self.delay_day.value(),
            "state_file": "warmup_state.json",
        }

    def _start_warmup(self):
        # Validate
        cfg = self._build_cfg_from_ui()
        required = {"SMTP_HOST": cfg["smtp_host"], "SMTP_USER": cfg["smtp_user"],
                     "SMTP_PASS": cfg["smtp_pass"], "FROM_NAME": cfg["from_name"],
                     "FROM_EMAIL": cfg["from_email"], "EMAIL_SUBJECT": cfg["email_subject"]}
        missing = [k for k, v in required.items() if not v]
        if missing:
            QMessageBox.warning(self, "Missing fields", f"Please fill in: {', '.join(missing)}")
            return

        data_path = self.data_path.text()
        html_path = self.html_path.text()
        if not os.path.exists(data_path):
            QMessageBox.warning(self, "File not found", f"Data file:\n{data_path}")
            return
        if not os.path.exists(html_path):
            QMessageBox.warning(self, "File not found", f"HTML file:\n{html_path}")
            return

        try:
            recipients = load_recipients(data_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load recipients:\n{e}")
            return
        try:
            html_body = load_html_body(html_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load HTML:\n{e}")
            return

        schedule = build_schedule(len(recipients), cfg["warmup_days"])
        state = load_state(cfg["state_file"])

        day = self.day_spin.value() if self.mode_day.isChecked() else None
        auto = self.mode_auto.isChecked()

        self._log_msg(f"Starting warm-up — {len(recipients)} recipients, "
                      f"{len(schedule)} days, sent so far: {state['sent_index']}")

        # Create worker thread
        self.worker_thread = QThread(self)
        self.worker = WarmupWorker(recipients, schedule, state, cfg, html_body, day, auto)
        self.worker.moveToThread(self.worker_thread)

        self.worker.log_signal.connect(self._log_msg)
        self.worker.progress_signal.connect(self._update_progress)
        self.worker.day_done.connect(self._on_day_done)
        self.worker.error.connect(self._on_worker_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.showMessage("Running…")

        self.worker_thread.start()

    def _stop_warmup(self):
        if self.worker:
            self.worker.stop()
        self._log_msg("Stopping… (will finish current email)")

    def _on_worker_finished(self):
        self.worker_thread.quit()
        self.worker_thread.wait()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        self.status.showMessage("Done")

    def _on_worker_error(self, msg):
        self._log_msg(f"ERROR: {msg}")

    def _on_day_done(self, day, total_sent):
        self._log_msg(f"Day {day} complete — total sent: {total_sent}")

    @Slot(str)
    def _log_msg(self, msg):
        self.log_output.appendPlainText(msg)
        # Auto-scroll
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)

    @Slot(int, int)
    def _update_progress(self, current, total):
        if total > 0:
            pct = int(current / total * 100)
            self.progress.setValue(pct)
            self.status.showMessage(f"Sending… {current}/{total} ({pct}%)")

    # ── Self-update check ──────────────────────────────────────────────────

    def _check_for_update(self):
        if not HAS_NETWORK:
            return
        url = QUrl("https://api.github.com/repos/mitexleo/mailwarmer/releases/latest")
        req = QNetworkRequest(url)
        req.setAttribute(QNetworkRequest.User, b"MailWarmer/" + __version__.encode())

        self.nam = QNetworkAccessManager(self)
        reply = self.nam.get(req)
        reply.finished.connect(lambda: self._on_update_response(reply))

    def _on_update_response(self, reply):
        try:
            if reply.error() != QNetworkReply.NoError:
                return
            data = json.loads(bytes(reply.readAll()).decode())
            latest_tag = data.get("tag_name", "")  # e.g. "v1.0.1"
            latest_version = latest_tag.lstrip("v")
            current = __version__

            if self._is_newer(latest_version, current):
                reply_msg = QMessageBox(self)
                reply_msg.setIcon(QMessageBox.Information)
                reply_msg.setWindowTitle("Update Available")
                reply_msg.setTextFormat(Qt.RichText)
                reply_msg.setText(
                    f"A new version is available: <b>v{latest_version}</b> (you have v{current}).<br><br>"
                    f'<a href="https://github.com/mitexleo/mailwarmer/releases/latest">'
                    f"Download from GitHub Releases →</a>"
                )
                reply_msg.setStandardButtons(QMessageBox.Ok)
                reply_msg.exec()
        except Exception:
            pass  # Silently ignore update check failures

    @staticmethod
    def _is_newer(latest, current):
        try:
            lp = tuple(int(x) for x in latest.split("."))
            cp = tuple(int(x) for x in current.split("."))
            return lp > cp
        except (ValueError, AttributeError):
            return False


# ── CLI mode entry (optional fallback) ────────────────────────────────────────

def cli_main():
    """Run the old CLI mode when --cli is passed."""
    from warmup_core import (
        load_config, load_recipients, load_html_body,
        build_schedule, load_state, save_state, send_batch,
    )

    parser = argparse.ArgumentParser(prog="warmup --cli")
    parser.add_argument("-c", "--config", default=".env")
    parser.add_argument("-d", "--data", required=True)
    parser.add_argument("-e", "--email", required=True)
    parser.add_argument("-s", "--state")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--day", type=int)
    mode.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("warmup.cli")

    cfg = load_config(args.config)
    if args.state:
        cfg["state_file"] = args.state

    recipients = load_recipients(args.data)
    html_body = load_html_body(args.email)
    schedule = build_schedule(len(recipients), cfg["warmup_days"])
    state = load_state(cfg["state_file"])

    log.info("Loaded %d recipients, schedule over %d days", len(recipients), len(schedule))

    def run_day(day):
        quota = schedule.get(day)
        if quota is None:
            log.error("Day %d not in schedule.", day)
            return
        log.info("=== Day %d ===", day)
        sent = send_batch(recipients, quota, state, cfg, html_body, log)
        state["last_day"] = day
        save_state(cfg["state_file"], state)
        log.info("=== Day %d done: sent %d ===", day, sent)

    if args.day:
        run_day(args.day)
    elif args.auto:
        start = state["last_day"] + 1
        for d in range(start, max(schedule.keys()) + 1):
            run_day(d)
            if d < max(schedule.keys()) and state["sent_index"] < len(recipients):
                log.info("Sleeping %ds…", cfg["delay_days"])
                time.sleep(cfg["delay_days"])


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        cli_main()
        return

    app = QApplication(sys.argv)
    app.setApplicationName("Mail Warmer")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("mailwarmer")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
