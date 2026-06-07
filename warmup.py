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

# NOTE: PySide6 imports are deferred into main() so that --cli mode
# works without Qt runtime libraries installed (e.g. in CI).


# ── Settings file (portable, stored next to the binary) ───────────────────────

def _settings_path():
    """Return path to the app settings JSON file."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "warmup_settings.json")


def _save_settings(data):
    path = _settings_path()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _load_settings():
    path = _settings_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


# ── CLI mode (no Qt needed) ──────────────────────────────────────────────────

def cli_main():
    """Run CLI mode when --cli is passed."""
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


# ── GUI (requires PySide6) ────────────────────────────────────────────────────

def gui_main():
    """Launch the Qt GUI application."""
    # Deferred imports so --cli doesn't need Qt
    from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QUrl
    from PySide6.QtGui import QAction, QDesktopServices, QIcon, QTextCursor
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
        QSpinBox, QStatusBar, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
    )

    # ── Log handler that emits Qt signals ─────────────────────────────────

    class LogSignal(QObject):
        message = Signal(str)

    class QtLogHandler(logging.Handler):
        def __init__(self, signal: LogSignal):
            super().__init__()
            self.signal = signal

        def emit(self, record):
            msg = self.format(record)
            self.signal.message.emit(msg)

    # ── Background worker ────────────────────────────────────────────────

    class WarmupWorker(QObject):
        log_signal = Signal(str)
        progress_signal = Signal(int, int)
        day_done = Signal(int, int)
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
            logger = logging.getLogger("warmup.worker")
            logger.setLevel(logging.INFO)
            gui_handler = QtLogHandler(LogSignal())
            gui_handler.signal.message.connect(self._log)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(gui_handler)

            file_handler = logging.FileHandler("warmup.log")
            file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(file_handler)

            def progress_cb(cur, total):
                self._progress(cur, total)

            try:
                if self.day:
                    self._run_day(self.day, logger, progress_cb)
                elif self.auto:
                    start_day = self.state["last_day"] + 1
                    for d in range(start_day, max(self.schedule.keys()) + 1):
                        if self._stop:
                            logger.info("Paused by user.")
                            break
                        self._run_day(d, logger, progress_cb)
                        if d < max(self.schedule.keys()) and self.state["sent_index"] < len(self.recipients):
                            if self._stop:
                                break
                            logger.info("Sleeping %ds before day %d ...", self.cfg["delay_days"], d + 1)
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

    # ── Help Dialog ──────────────────────────────────────────────────────

    def show_help(parent):
        help_text = (
            "<h2>Usage Guide</h2>"
            "<h3>Recipients File (.xlsx / .csv)</h3>"
            "<p>The first column should contain one email address per row. "
            "A header row is allowed but not required.</p>"
            "<pre>email@example.com\nuser2@domain.com\nuser3@domain.com</pre>"
            "<p>Or with a header:</p>"
            "<pre>Email\nemail@example.com\nuser2@domain.com</pre>"
            "<h3>Email Body</h3>"
            "<p>Write or paste your HTML email in the <b>Editor</b> tab under "
            "Email Body. You can also load from an <code>.html</code> file "
            "using the <b>File</b> tab.</p>"
            "<h3>Config</h3>"
            "<p>SMTP settings can be entered directly in the form. "
            "Use <b>Save Config</b> to persist them. "
            "<b>Load Config</b> imports from a <code>.env</code> file.</p>"
            "<h3>Resuming</h3>"
            "<p>Progress is saved after each email. If you close the app "
            "and reopen, you will be prompted to resume from where you left off.</p>"
            "<h3>Version</h3>"
            f"<p>v{__version__} &mdash; "
            f'<a href="https://github.com/mitexleo/mailwarmer">'
            "github.com/mitexleo/mailwarmer</a></p>"
        )
        msg = QMessageBox(parent)
        msg.setWindowTitle(f"Mail Warmer Help")
        msg.setTextFormat(Qt.RichText)
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    # ── Main Window ──────────────────────────────────────────────────────

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.worker = None
            self.worker_thread = None
            self.html_editor_content = ""  # holds editor tab HTML

            self.setWindowTitle(f"Mail Warmer v{__version__}")
            self.setMinimumSize(780, 720)

            self._build_ui()
            self._build_menu()
            self._load_settings_into_ui()
            self._check_for_update()
            self._prompt_resume()

        # ── UI ────────────────────────────────────────────────────────

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setSpacing(10)

            # ─ SMTP ─
            smtp_group = QGroupBox("SMTP Configuration")
            smtp_form = QFormLayout(smtp_group)
            self.smtp_host = QLineEdit()
            smtp_form.addRow("Host:", self.smtp_host)
            self.smtp_port = QSpinBox()
            self.smtp_port.setRange(1, 65535); self.smtp_port.setValue(25)
            smtp_form.addRow("Port:", self.smtp_port)
            self.smtp_user = QLineEdit()
            smtp_form.addRow("User:", self.smtp_user)
            self.smtp_pass = QLineEdit()
            self.smtp_pass.setEchoMode(QLineEdit.Password)
            smtp_form.addRow("Pass:", self.smtp_pass)
            self.use_tls = QCheckBox("Enable STARTTLS")
            smtp_form.addRow("", self.use_tls)
            # Add spacing around groups
            smtp_group.setStyleSheet("QGroupBox{padding-top:12px;margin-top:4px}")
            layout.addWidget(smtp_group)

            # ─ Sender ─
            sender_group = QGroupBox("Sender & Email")
            sender_form = QFormLayout(sender_group)
            self.from_name = QLineEdit()
            sender_form.addRow("From name:", self.from_name)
            self.from_email = QLineEdit()
            sender_form.addRow("From email:", self.from_email)
            self.email_subject = QLineEdit()
            sender_form.addRow("Subject:", self.email_subject)

            # Save / Load config buttons
            btn_row = QHBoxLayout()
            btn_save = QPushButton("Save Config")
            btn_save.clicked.connect(self._save_config)
            btn_load_env = QPushButton("Load from .env")
            btn_load_env.clicked.connect(self._load_config_into_ui)
            btn_row.addWidget(btn_save)
            btn_row.addWidget(btn_load_env)
            btn_row.addStretch()
            sender_form.addRow("", btn_row)
            layout.addWidget(sender_group)

            # ─ Files ─
            files_group = QGroupBox("Recipients")
            files_form = QFormLayout(files_group)
            data_row = QHBoxLayout()
            self.data_path = QLineEdit()
            self.data_path.setPlaceholderText("Path to .xlsx or .csv …")
            data_row.addWidget(self.data_path)
            btn_data = QPushButton("Browse…")
            btn_data.clicked.connect(lambda: self._browse(self.data_path, "Data files (*.xlsx *.csv)"))
            data_row.addWidget(btn_data)
            files_form.addRow("File:", data_row)
            layout.addWidget(files_group)

            # ─ Email Body (tab: File | Editor) ─
            body_group = QGroupBox("Email Body")
            body_layout = QVBoxLayout(body_group)
            body_tabs = QTabWidget()
            self.body_tabs = body_tabs

            # File tab
            file_tab = QWidget()
            file_lo = QHBoxLayout(file_tab)
            self.html_path = QLineEdit()
            self.html_path.setPlaceholderText("Path to .html file …")
            file_lo.addWidget(self.html_path)
            btn_html = QPushButton("Browse…")
            btn_html.clicked.connect(lambda: self._browse(self.html_path, "HTML files (*.html *.htm)"))
            file_lo.addWidget(btn_html)
            btn_load_body = QPushButton("Load into Editor")
            btn_load_body.clicked.connect(self._load_html_file_to_editor)
            file_lo.addWidget(btn_load_body)
            body_tabs.addTab(file_tab, "File")

            # Editor tab
            editor_tab = QWidget()
            editor_lo = QVBoxLayout(editor_tab)
            self.html_editor = QPlainTextEdit()
            self.html_editor.setPlaceholderText(
                "Paste or write your HTML email here…\n\n"
                "<!DOCTYPE html>\n<html>\n<body>\n  <h1>Hello!</h1>\n</body>\n</html>"
            )
            self.html_editor.setStyleSheet("font-family: monospace; font-size: 11px;")
            editor_lo.addWidget(self.html_editor)
            body_tabs.addTab(editor_tab, "Editor")

            body_tabs.currentChanged.connect(self._on_body_tab_changed)
            body_layout.addWidget(body_tabs)
            layout.addWidget(body_group)

            # ─ Schedule & Controls ─
            sched_group = QGroupBox("Schedule & Controls")
            sched_layout = QVBoxLayout(sched_group)

            top_row = QHBoxLayout()
            top_row.addWidget(QLabel("Warmup days:"))
            self.warmup_days = QSpinBox()
            self.warmup_days.setRange(1, 365); self.warmup_days.setValue(14)
            top_row.addWidget(self.warmup_days)
            top_row.addSpacing(20)
            top_row.addWidget(QLabel("Delay between emails (s):"))
            self.delay_email = QSpinBox()
            self.delay_email.setRange(0, 3600); self.delay_email.setValue(10)
            top_row.addWidget(self.delay_email)
            top_row.addSpacing(20)
            top_row.addWidget(QLabel("Delay between days (s):"))
            self.delay_day = QSpinBox()
            self.delay_day.setRange(0, 86400 * 7); self.delay_day.setValue(86400)
            top_row.addWidget(self.delay_day)
            top_row.addStretch()
            sched_layout.addLayout(top_row)

            mid_row = QHBoxLayout()
            self.mode_day = QRadioButton("Specific day")
            self.day_spin = QSpinBox()
            self.day_spin.setRange(1, 365); self.day_spin.setValue(1)
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
            self.btn_pause = QPushButton("⏸ Pause")
            self.btn_pause.setMinimumWidth(120)
            self.btn_pause.setEnabled(False)
            self.btn_pause.clicked.connect(self._pause_warmup)
            btn_row.addWidget(self.btn_start)
            btn_row.addWidget(self.btn_pause)
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
            guide = QAction("Usage Guide", self)
            guide.triggered.connect(lambda: show_help(self))
            help_menu.addAction(guide)

            about = QAction("About", self)
            about.triggered.connect(lambda: QMessageBox.about(self, "About Mail Warmer",
                f"<b>Mail Warmer v{__version__}</b><br><br>"
                "SMTP warm-up tool — gradually send emails to build sender reputation.<br><br>"
                "Author: Mueenul Islam<br>"
                "Email: <a href='mailto:hello@mueen.dev'>hello@mueen.dev</a><br>"
                "Web: <a href='https://mueen.dev'>https://mueen.dev</a><br><br>"
                "<a href='https://github.com/mitexleo/mailwarmer'>github.com/mitexleo/mailwarmer</a>"))
            help_menu.addAction(about)

            check = QAction("Check for Updates", self)
            check.triggered.connect(self._check_for_update)
            help_menu.addAction(check)

        # ── File browser ────────────────────────────────────────────────

        def _browse(self, line_edit, filter_str):
            path, _ = QFileDialog.getOpenFileName(self, "Select file", "", filter_str)
            if path:
                line_edit.setText(path)

        # ── Email body tabs ─────────────────────────────────────────────

        def _on_body_tab_changed(self, idx):
            """Sync content when switching between File and Editor tabs."""
            if idx == 1:  # switched to Editor
                file_path = self.html_path.text()
                if file_path and os.path.exists(file_path) and not self.html_editor.toPlainText():
                    try:
                        self.html_editor.setPlainText(load_html_body(file_path))
                    except Exception:
                        pass

        def _load_html_file_to_editor(self):
            path = self.html_path.text()
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "File not found", f"HTML file not found:\n{path}")
                return
            try:
                content = load_html_body(path)
                self.html_editor.setPlainText(content)
                self.body_tabs.setCurrentIndex(1)
                self._log_msg(f"Loaded HTML body from {path} ({len(content)} bytes)")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load HTML:\n{e}")

        def _get_html_body(self):
            """Return HTML body from whichever tab is active."""
            if self.body_tabs.currentIndex() == 1:
                return self.html_editor.toPlainText()
            path = self.html_path.text()
            if path and os.path.exists(path):
                return load_html_body(path)
            return ""

        # ── Settings persistence ────────────────────────────────────────

        def _save_config(self):
            data = {
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
                "data_path": self.data_path.text(),
                "html_path": self.html_path.text(),
            }
            _save_settings(data)
            self._log_msg("Config saved ✓")
            self.status.showMessage("Config saved ✓")

        def _load_settings_into_ui(self):
            data = _load_settings()
            if not data:
                return
            self.smtp_host.setText(data.get("smtp_host", ""))
            self.smtp_port.setValue(data.get("smtp_port", 25))
            self.smtp_user.setText(data.get("smtp_user", ""))
            self.smtp_pass.setText(data.get("smtp_pass", ""))
            self.use_tls.setChecked(data.get("use_tls", False))
            self.from_name.setText(data.get("from_name", ""))
            self.from_email.setText(data.get("from_email", ""))
            self.email_subject.setText(data.get("email_subject", ""))
            self.warmup_days.setValue(data.get("warmup_days", 14))
            self.delay_email.setValue(data.get("delay_emails", 10))
            self.delay_day.setValue(data.get("delay_days", 86400))
            self.data_path.setText(data.get("data_path", ""))
            self.html_path.setText(data.get("html_path", ""))
            self._log_msg("Settings restored from last session ✓")

        # ── Load .env into UI ──────────────────────────────────────────

        def _load_config_into_ui(self):
            env_path, _ = QFileDialog.getOpenFileName(
                self, "Select .env file", "", "Env files (*.env);;All files (*)"
            )
            if not env_path:
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

            self.status.showMessage("Config loaded from .env ✓")

        # ── Resume prompt ──────────────────────────────────────────────

        def _prompt_resume(self):
            cfg = self._build_cfg_from_ui()
            state = load_state(cfg["state_file"])
            if state["sent_index"] > 0:
                reply = QMessageBox.question(
                    self, "Resume?",
                    f"Previous progress found: {state['sent_index']} emails sent, "
                    f"last day {state['last_day']}.\n\nDo you want to resume?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self._log_msg(
                        f"Resuming from day {state['last_day'] + 1}, "
                        f"sent_index={state['sent_index']}"
                    )
                    self.status.showMessage("Ready to resume")
                else:
                    # Reset
                    save_state(cfg["state_file"], {"sent_index": 0, "last_day": 0})
                    self._log_msg("Previous state reset. Starting fresh.")
                    self.status.showMessage("State reset")

        # ── Start / Pause ──────────────────────────────────────────────

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
            cfg = self._build_cfg_from_ui()
            required = {"SMTP_HOST": cfg["smtp_host"], "SMTP_USER": cfg["smtp_user"],
                         "SMTP_PASS": cfg["smtp_pass"], "FROM_NAME": cfg["from_name"],
                         "FROM_EMAIL": cfg["from_email"], "EMAIL_SUBJECT": cfg["email_subject"]}
            missing = [k for k, v in required.items() if not v]
            if missing:
                QMessageBox.warning(self, "Missing fields", f"Please fill in: {', '.join(missing)}")
                return

            data_path = self.data_path.text()
            if not data_path or not os.path.exists(data_path):
                QMessageBox.warning(self, "File not found", f"Recipients file:\n{data_path}")
                return

            html_body = self._get_html_body()
            if not html_body:
                QMessageBox.warning(self, "Missing body",
                    "Please provide an HTML email body (File tab or Editor tab).")
                return

            try:
                recipients = load_recipients(data_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load recipients:\n{e}")
                return

            schedule = build_schedule(len(recipients), cfg["warmup_days"])
            state = load_state(cfg["state_file"])

            day = self.day_spin.value() if self.mode_day.isChecked() else None
            auto = self.mode_auto.isChecked()

            self._log_msg(f"Starting warm-up — {len(recipients)} recipients, "
                          f"{len(schedule)} days, sent so far: {state['sent_index']}")

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
            self.btn_pause.setEnabled(True)
            self.progress.setVisible(True)
            self.progress.setValue(0)
            self.status.showMessage("Running…")

            self.worker_thread.start()

        def _pause_warmup(self):
            if self.worker:
                self.worker.stop()
            self._log_msg("Pausing… (will finish current email, then stop)")
            self.btn_pause.setEnabled(False)

        def _on_worker_finished(self):
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.progress.setVisible(False)
            self.status.showMessage("Done")
            self._log_msg("Warm-up paused. You can resume later with Start.")

        def _on_worker_error(self, msg):
            self._log_msg(f"ERROR: {msg}")

        def _on_day_done(self, day, total_sent):
            self._log_msg(f"Day {day} complete — total sent: {total_sent}")

        @Slot(str)
        def _log_msg(self, msg):
            self.log_output.appendPlainText(msg)
            cursor = self.log_output.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.log_output.setTextCursor(cursor)

        @Slot(int, int)
        def _update_progress(self, current, total):
            if total > 0:
                pct = int(current / total * 100)
                self.progress.setValue(pct)
                self.status.showMessage(f"Sending… {current}/{total} ({pct}%)")

        # ── Self-update check ──────────────────────────────────────────

        def _check_for_update(self):
            try:
                nam = QNetworkAccessManager(self)
                url = QUrl("https://api.github.com/repos/mitexleo/mailwarmer/releases/latest")
                req = QNetworkRequest(url)
                req.setAttribute(QNetworkRequest.User, b"MailWarmer/" + __version__.encode())
                reply = nam.get(req)
                reply.finished.connect(lambda: self._on_update_response(reply))
            except Exception:
                pass

        def _on_update_response(self, reply):
            try:
                if reply.error() != QNetworkReply.NoError:
                    return
                data = json.loads(bytes(reply.readAll()).decode())
                latest_version = data.get("tag_name", "").lstrip("v")
                if self._is_newer(latest_version, __version__):
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Update Available")
                    msg.setTextFormat(Qt.RichText)
                    msg.setText(
                        f"A new version is available: <b>v{latest_version}</b> "
                        f"(you have v{__version__}).<br><br>"
                        f'<a href="https://github.com/mitexleo/mailwarmer/releases/latest">'
                        f"Download from GitHub Releases →</a>"
                    )
                    msg.setStandardButtons(QMessageBox.Ok)
                    msg.exec()
            except Exception:
                pass

        @staticmethod
        def _is_newer(latest, current):
            try:
                lp = tuple(int(x) for x in latest.split("."))
                cp = tuple(int(x) for x in current.split("."))
                return lp > cp
            except (ValueError, AttributeError):
                return False

    # ── Launch ──────────────────────────────────────────────────────────

    app = QApplication(sys.argv)
    app.setApplicationName("Mail Warmer")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("mailwarmer")

    # Global stylesheet for consistent sizing
    app.setStyleSheet("""
        QMainWindow, QDialog {
            font-size: 13px;
        }
        QGroupBox {
            font-weight: bold;
            font-size: 13px;
            padding-top: 8px;
            margin-top: 4px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 2px 8px;
        }
        QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {
            padding: 6px 8px;
            font-size: 13px;
            min-height: 22px;
        }
        QPushButton {
            padding: 8px 18px;
            font-size: 13px;
            min-height: 24px;
        }
        QComboBox {
            padding: 6px 8px;
            font-size: 13px;
            min-height: 22px;
        }
        QCheckBox, QRadioButton {
            font-size: 13px;
            spacing: 6px;
        }
        QStatusBar {
            font-size: 12px;
        }
        QTabWidget::pane {
            padding: 4px;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        cli_main()
        return

    gui_main()


if __name__ == "__main__":
    main()
