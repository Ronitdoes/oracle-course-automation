"""Main window: nav rail + Run / History / Settings pages, editorial theme."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QStatusBar, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.dialogs import ApprovalDialog, SetupWizard
from app.env_store import FIELD_SPECS, GROUPS, bool_to_str, bundled_path, load_env, save_env, str_to_bool
from app.logo import build_icon, logo_pixmap
from app.theme import pill_style
from app.worker import RunWorker

log = logging.getLogger(__name__)


def _project_root() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


ACADEMY_URL = "https://academy.oracle.com/"


def _cdp_endpoint() -> str:
    vals = load_env(_project_root() / ".env") | load_env(".env")
    return os.environ.get("CDP_ENDPOINT") or vals.get("CDP_ENDPOINT", "http://localhost:9222")


def _cdp_port(endpoint: str) -> int:
    try:
        return urllib.parse.urlparse(endpoint).port or 9222
    except Exception:
        return 9222


def _cdp_alive(endpoint: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _open_tab_via_cdp(endpoint: str, url: str, timeout: float = 5.0) -> bool:
    """Open url as a new tab in the debuggable browser. Returns True on success.

    Chrome's endpoint takes the raw URL in the query string
    (PUT /json/new?https://example.com) — a `url=` parameter is ignored
    and yields a blank tab.
    """
    import json as _json

    base = endpoint.rstrip("/")
    for target in (f"{base}/json/new?{url}",
                   base + "/json/new?" + urllib.parse.urlencode({"url": url})):
        try:
            req = urllib.request.Request(target, method="PUT")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    continue
                try:
                    body = _json.loads(r.read().decode("utf-8", "replace"))
                    opened = str(body.get("url", ""))
                    if opened and opened != "about:blank" and "academy.oracle.com" not in opened and url not in opened:
                        continue
                except Exception:
                    pass
                return True
        except Exception as e:  # noqa: BLE001
            log.debug("CDP open-tab failed (%s): %s", target[:80], e)
            continue
    return False


def _list_cdp_tabs(endpoint: str, timeout: float = 5.0) -> list:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/json/list", timeout=timeout) as r:
            import json as _json
            data = _json.loads(r.read().decode("utf-8", "replace"))
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _ensure_academy_tab(endpoint: str) -> bool:
    """Make sure at least one tab points at Academy (fixes launches that
    swallowed the startup URL, e.g. first-run flow with a fresh profile)."""
    for t in _list_cdp_tabs(endpoint):
        if not isinstance(t, dict) or t.get("type") != "page":
            continue
        if "academy.oracle.com" in (t.get("url") or ""):
            return True
    return _open_tab_via_cdp(endpoint, ACADEMY_URL)


def _find_chrome() -> str:
    for cand in (shutil.which("chrome"), shutil.which("chrome.exe"),
                 shutil.which("google-chrome"), shutil.which("chromium")):
        if cand:
            return cand
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def _debug_profile_dir() -> Path:
    base = _project_root() / "artifacts" / "chrome-debug-profile"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _default_db_path() -> str:
    env = load_env(_project_root() / ".env") | load_env(".env")
    return env.get("DATABASE_PATH", "./artifacts/runs.sqlite")


class MainWindow(QMainWindow):
    extralog = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Browser Agent")
        self.setWindowIcon(build_icon())
        self.resize(1060, 720)
        self._root = _project_root()
        self._worker: RunWorker | None = None
        self._run_active = False
        self._max_q = 500

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- nav rail ---
        rail = QWidget()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(200)
        raill = QVBoxLayout(rail)
        raill.setContentsMargins(16, 20, 16, 20)
        raill.setSpacing(4)
        brandrow = QHBoxLayout()
        brandrow.setSpacing(10)
        brandrow.setContentsMargins(0, 0, 0, 0)
        mark = QLabel()
        mark.setPixmap(logo_pixmap(30))
        mark.setFixedSize(30, 30)
        mark.setScaledContents(True)
        brandrow.addWidget(mark)
        brandtxt = QVBoxLayout()
        brandtxt.setSpacing(0)
        brandtxt.setContentsMargins(0, 0, 0, 0)
        brand = QLabel("Browser Agent")
        brand.setObjectName("Brand")
        sub = QLabel("QUIZ HELPER")
        sub.setObjectName("BrandSub")
        brandtxt.addWidget(brand)
        brandtxt.addWidget(sub)
        brandrow.addLayout(brandtxt)
        brandrow.addStretch(1)
        raill.addLayout(brandrow)
        raill.addSpacing(12)
        self._nav_btns: dict[str, QPushButton] = {}
        for key in ("Run", "History", "Settings"):
            b = QPushButton(key)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._goto(k))
            raill.addWidget(b)
            self._nav_btns[key] = b
        raill.addStretch(1)
        hint = QLabel("Minimal editorial build.\nCore logic untouched.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        raill.addWidget(hint)
        outer.addWidget(rail)

        # --- pages ---
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)
        self._run_page = self._build_run_page()
        self._history_page = self._build_history_page()
        self._settings_page = self._build_settings_page()
        self._stack.addWidget(self._run_page)
        self._stack.addWidget(self._history_page)
        self._stack.addWidget(self._settings_page)

        self._goto("Run")
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready. Open Oracle Academy (My Classes / any course), then press Start.")
        self.extralog.connect(self._append_log)
        # Batched rendering: worker signals arrive fast; flushing every 200ms
        # in one layout pass keeps the UI smooth instead of re-laying out the
        # tables on every single step/log line.
        self._pending_steps: list[dict] = []
        self._pending_logs: list[str] = []
        self._flush = QTimer(self)
        self._flush.setInterval(200)
        self._flush.timeout.connect(self._flush_pending)
        self._load_env_into_run_bar()
        first_run = os.environ.pop("BROWSER_AGENT_FIRST_RUN", "") == "1"
        if first_run or self._needs_api_key():
            # Fresh install (or a real provider with no key yet): ask for the
            # AI key + basic setup once the window is up instead of failing
            # later with a missing key.
            QTimer.singleShot(400, lambda: self._open_setup(first_run=True))

    # ============ navigation ============
    def _goto(self, key: str):
        idx = {"Run": 0, "History": 1, "Settings": 2}[key]
        self._stack.setCurrentIndex(idx)
        for k, b in self._nav_btns.items():
            b.setChecked(k == key)
            b.setProperty("active", k == key)
            b.style().unpolish(b)
            b.style().polish(b)
        if key == "History":
            self._refresh_history()
        if key == "Settings":
            self._reload_settings_form()

    # ============ RUN page ============
    def _build_run_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        # topbar — single slim row: title + status, actions right
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Run")
        title.setObjectName("PageTitle")
        top.addWidget(title)
        self._pill = QLabel("IDLE")
        self._pill.setObjectName("Pill")
        self._pill.setStyleSheet(pill_style("IDLE"))
        top.addWidget(self._pill)
        top.addStretch(1)
        self._btn_start = QPushButton("Start")
        self._btn_start.setObjectName("Primary")
        self._btn_start.clicked.connect(self.start_run)
        self._btn_setup = QPushButton("Setup")
        self._btn_setup.setObjectName("Ghost")
        self._btn_setup.clicked.connect(lambda: self._open_setup())
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setObjectName("Ghost")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self.stop_run)
        top.addWidget(self._btn_start)
        top.addWidget(self._btn_setup)
        top.addWidget(self._btn_stop)
        lay.addLayout(top)

        url_lab = QLabel("START  —  NO LINK NEEDED")
        url_lab.setObjectName("Section")
        lay.addWidget(url_lab)
        urlrow = QHBoxLayout()
        self._btn_academy = QPushButton("Open Oracle Academy")
        self._btn_academy.setObjectName("Ghost")
        self._btn_academy.clicked.connect(self._open_academy)
        urlrow.addWidget(self._btn_academy)
        academy_hint = QLabel("Log in, open My Classes / any course outline / quiz, keep that tab in front — then press Start. Auto-advance walks Take Class → sections/exams → Finish Assessment across courses.")
        academy_hint.setObjectName("Muted")
        academy_hint.setWordWrap(True)
        urlrow.addWidget(academy_hint, 1)
        lay.addLayout(urlrow)

        opts = QHBoxLayout()
        self._ck_dry = QCheckBox("Dry run")
        self._ck_headed = QCheckBox("Show browser")
        self._ck_approval = QCheckBox("Require approval")
        self._spin_max = QSpinBox()
        self._spin_max.setRange(1, 5000)
        self._spin_max.setValue(500)
        self._spin_max.setPrefix("Max ")
        for c in (self._ck_dry, self._ck_headed, self._ck_approval):
            opts.addWidget(c)
        opts.addWidget(self._spin_max)
        opts.addStretch(1)
        lay.addLayout(opts)

        # progress — thin rule + stats only
        prow = QVBoxLayout()
        prow.setSpacing(6)
        prow.setContentsMargins(0, 0, 0, 0)
        self._rule = QProgressBar()
        self._rule.setObjectName("Rule")
        self._rule.setTextVisible(False)
        self._rule.setRange(0, 500)
        self._rule.setValue(0)
        prow.addWidget(self._rule)
        self._sub = QLabel("0 answers  ·  0 model calls")
        self._sub.setObjectName("Muted")
        prow.addWidget(self._sub)
        lay.addLayout(prow)

        steps_lab = QLabel("STEPS")
        steps_lab.setObjectName("Section")
        lay.addWidget(steps_lab)
        self._steps = QTableWidget(0, 5)
        self._steps.setHorizontalHeaderLabels(["State", "Question", "Action", "Check", "Problem"])
        self._steps.setAlternatingRowColors(True)
        self._steps.setSelectionBehavior(QTableWidget.SelectRows)
        self._steps.setEditTriggers(QTableWidget.NoEditTriggers)
        self._steps.horizontalHeader().setStretchLastSection(True)
        self._steps.setColumnWidth(0, 130)
        self._steps.setColumnWidth(1, 110)
        self._steps.verticalHeader().setVisible(False)
        lay.addWidget(self._steps, 2)

        log_lab = QLabel("LOG")
        log_lab.setObjectName("Section")
        lay.addWidget(log_lab)
        self._logview = QPlainTextEdit()
        self._logview.setObjectName("LogView")
        self._logview.setReadOnly(True)
        self._logview.setMaximumBlockCount(800)
        lay.addWidget(self._logview, 1)
        return w

    def _load_env_into_run_bar(self):
        vals = load_env(self._root / ".env") | load_env(".env")
        self._ck_dry.setChecked(str_to_bool(vals.get("DRY_RUN", "false")))
        self._ck_headed.setChecked(not str_to_bool(vals.get("HEADLESS", "true")))
        self._ck_approval.setChecked(str_to_bool(vals.get("REQUIRE_APPROVAL", "false")))
        try:
            self._spin_max.setValue(int(vals.get("MAX_QUESTIONS", "500")))
        except ValueError:
            pass
        self._max_q = self._spin_max.value()
        self._rule.setRange(0, max(1, self._max_q))
        self._rule.setValue(0)

    def _set_pill(self, state: str):
        self._pill.setText(state.upper() or "—")
        self._pill.setStyleSheet(pill_style(state))

    def _needs_api_key(self) -> bool:
        """True when a real provider is selected but no key is configured."""
        vals = load_env(self._root / ".env") | load_env(".env")
        provider = (os.environ.get("LLM_PROVIDER") or vals.get("LLM_PROVIDER", "mock")).strip().lower()
        if provider not in ("gemini", "groq", "openai"):
            return False
        key = (os.environ.get("LLM_API_KEY") or vals.get("LLM_API_KEY", "")).strip()
        extra = (os.environ.get("LLM_API_KEYS") or vals.get("LLM_API_KEYS", "")).strip()
        return not (key or extra)

    # -- run control --
    def _open_academy(self):
        endpoint = _cdp_endpoint()
        # Case 1: debuggable browser already running -> open Academy as a new
        # tab inside THAT browser (not the system default browser).
        if _cdp_alive(endpoint):
            if _open_tab_via_cdp(endpoint, ACADEMY_URL):
                self._append_log("— opened Oracle Academy in your debuggable browser tab. "
                                 "Log in, open your quiz, then press Start.")
                self.statusBar().showMessage("Oracle Academy opened in the debug browser — press Start.")
            else:
                QDesktopServices.openUrl(QUrl(ACADEMY_URL))
                self._append_log("— debug browser is running but tab-open failed; "
                                 "opened Academy in the default browser instead.")
            return
        # Case 2: nothing on the debug port -> launch Chrome WITH the port.
        chrome = _find_chrome()
        if not chrome:
            QDesktopServices.openUrl(QUrl(ACADEMY_URL))
            self._append_log("— Chrome not found; opened Academy in the default browser. "
                             "Install Chrome or set CDP_ENDPOINT, then press Start.")
            self.statusBar().showMessage("Chrome not found — opened default browser instead.")
            return
        port = _cdp_port(endpoint)
        profile = _debug_profile_dir()
        try:
            subprocess.Popen(
                [chrome, f"--remote-debugging-port={port}",
                 "--remote-allow-origins=*",
                 "--no-first-run", "--no-default-browser-check",
                 f"--user-data-dir={profile}", ACADEMY_URL],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except Exception as e:  # noqa: BLE001
            QDesktopServices.openUrl(QUrl(ACADEMY_URL))
            self._append_log(f"— could not launch debug browser ({e}); opened default browser instead.")
            return
        t = threading.Thread(target=self._wait_for_debug_browser,
                             args=(endpoint,), daemon=True)
        t.start()
        self._append_log("— launching debug browser with Oracle Academy…")
        self.statusBar().showMessage("Launching debug browser…")

    def _wait_for_debug_browser(self, endpoint: str, timeout: float = 20.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if _cdp_alive(endpoint):
                # Fresh profiles can swallow the startup URL (first-run flow),
                # leaving a blank tab — guarantee an Academy tab exists.
                if _ensure_academy_tab(endpoint):
                    self.extralog.emit("— debug browser ready with Oracle Academy. "
                                       "Log in, open your quiz tab, then press Start.")
                else:
                    self.extralog.emit("— debug browser ready. Log in, open your quiz tab, then press Start.")
                return
            time.sleep(0.5)
        self.extralog.emit("— debug browser did not answer on "
                           f"{endpoint}. If Chrome is already open, close it and try again.")

    def start_run(self):
        if self._run_active:
            return
        # Always attach to the user's open Oracle Academy tab — no URLs.
        os.environ["TARGET_URL"] = ""
        os.environ["BROWSER_CONNECTION_MODE"] = "cdp"
        self._max_q = self._spin_max.value()
        os.environ["DRY_RUN"] = bool_to_str(self._ck_dry.isChecked())
        os.environ["HEADLESS"] = bool_to_str(not self._ck_headed.isChecked())
        os.environ["REQUIRE_APPROVAL"] = bool_to_str(self._ck_approval.isChecked())
        # Auto-advance is always on in the app: it walks Take Class →
        # sections/exams → Finish Assessment across courses by itself.
        os.environ["AUTO_ADVANCE_LESSONS"] = "true"
        os.environ["MAX_QUESTIONS"] = str(self._max_q)

        self._steps.setRowCount(0)
        self._pending_steps.clear()
        self._pending_logs.clear()
        self._append_log("— starting run: attached to your open browser tab")
        self._set_pill("OBSERVE")
        self._rule.setRange(0, max(1, self._max_q))
        self._rule.setValue(0)

        self._worker = RunWorker(self)
        self._worker.step.connect(self._on_step)
        self._worker.progress.connect(self._on_progress)
        self._worker.logline.connect(self._append_log)
        self._worker.approval_needed.connect(self._on_approval)
        self._worker.finished.connect(self._on_finished)
        self._run_active = True
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self.statusBar().showMessage("Running…")
        self._worker.start()

    def stop_run(self):
        if self._worker is not None:
            self.statusBar().showMessage("Stopping…")
            self._worker.request_stop()

    def _kick_flush(self) -> None:
        if not self._flush.isActive():
            self._flush.start()

    def _on_step(self, s: dict):
        self._pending_steps.append(s)
        self._kick_flush()

    def _on_progress(self, p: dict):
        q = int(p.get("questions_done", 0) or 0)
        mc = int(p.get("model_calls", 0) or 0)
        quizzes = int(p.get("quizzes_done", 0) or 0)
        courses = int(p.get("courses_done", 0) or 0)
        self._rule.setValue(min(q, self._max_q))
        note = str(p.get("last_note", "") or "").strip()
        text = f"{q} answers  ·  {mc} model calls  ·  {quizzes} quizzes  ·  {courses} courses"
        if note and p.get("state") not in ("COMPLETED",):
            text += f"  ·  {note[:90]}"
        self._sub.setText(text)
        self._set_pill(str(p.get("state", "")))

    def _append_log(self, line: str):
        self._pending_logs.append(line)
        self._kick_flush()

    def _flush_pending(self) -> None:
        steps, self._pending_steps = self._pending_steps, []
        logs, self._pending_logs = self._pending_logs, []
        if not steps and not logs:
            self._flush.stop()
            return
        if steps:
            bar = self._steps.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 4
            self._steps.setUpdatesEnabled(False)
            try:
                for s in steps:
                    r = self._steps.rowCount()
                    self._steps.insertRow(r)
                    for c, k in enumerate(["state", "question_id", "action", "verification", "error"]):
                        self._steps.setItem(r, c, QTableWidgetItem(str(s.get(k, ""))))
                for _ in range(max(0, self._steps.rowCount() - 600)):
                    self._steps.removeRow(0)
            finally:
                self._steps.setUpdatesEnabled(True)
            if at_bottom:
                self._steps.scrollToBottom()
        if logs:
            try:
                self._logview.appendPlainText("\n".join(logs))
            except Exception:
                pass

    def _on_approval(self, payload: dict):
        if not self._run_active or self._worker is None:
            return
        dlg = ApprovalDialog(payload, self)
        ok = dlg.exec() == QDialog.Accepted
        self._append_log(f"approval ({payload.get('kind')}): {'approved' if ok else 'rejected'}")
        self._worker.resolve_approval(ok)

    def _open_setup(self, first_run: bool = False):
        """First-time (or re-run) setup: AI key + basic settings into .env."""
        dlg = SetupWizard(self._env_path(), load_env(self._env_path()),
                          first_run=first_run, parent=self)
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.values()
            for k, v in vals.items():
                os.environ[k] = v
            try:
                save_env(self._env_path(), vals)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Save failed", str(e))
                return
            self._load_env_into_run_bar()
            self._append_log("— setup saved to .env")
            self.statusBar().showMessage("Setup saved.")

    def _on_finished(self, summary: dict):
        self._run_active = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        final = str(summary.get("final_state", "STOPPED"))
        self._set_pill(final)
        q = summary.get("questions_done", 0)
        mc = summary.get("model_calls", 0)
        quizzes = summary.get("quizzes_done", 0)
        courses = summary.get("courses_done", 0)
        self._sub.setText(f"{q} answers  ·  {mc} model calls  ·  {quizzes} quizzes  ·  {courses} courses")
        self.statusBar().showMessage(f"Ended: {final} — {q} questions, {quizzes} quizzes, {courses} courses, {mc} model calls.")
        self._append_log(f"— ended: {final} ({q} questions, {quizzes} quizzes, {courses} courses, {mc} model calls)")
        err = str(summary.get("error", "") or "")
        if final == "FAILED" and "Executable doesn't exist" in err:
            self._offer_browser_install(err)
        elif final == "FAILED" and ("ECONNREFUSED" in err and "9222" in err):
            self._offer_cdp_help()
        self._worker = None

    def _offer_cdp_help(self):
        self._append_log("— could not attach: the debug browser isn't running. "
                         "Press 'Open Oracle Academy' to relaunch it, open your quiz, then Start again.")
        box = QMessageBox(self)
        box.setWindowTitle("Couldn't reach your browser")
        box.setText("Start couldn't find the debug browser (it may have been closed).")
        box.setInformativeText(
            "Press 'Open Oracle Academy' to relaunch it, open your quiz there, "
            "and press Start again.")
        box.exec()

    def _offer_browser_install(self, err: str):
        box = QMessageBox(self)
        box.setWindowTitle("Browser not installed")
        box.setText("Playwright's Chromium is missing. Install it once (~170 MB), then press Start again.")
        box.setInformativeText("Command:  playwright install chromium")
        install_btn = box.addButton("Install now", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is install_btn:
            self._append_log("— installing Chromium (playwright install chromium)…")
            t = threading.Thread(target=self._install_browser, daemon=True)
            t.start()

    def _install_browser(self):
        # Runs in a worker thread; reports back via extralog.
        # Frozen (installed/portable exe) has no Python interpreter, so the
        # usual `python -m playwright install` cannot work: drive the bundled
        # Playwright node + CLI directly instead.
        import sys
        try:
            from app.env_store import default_browsers_path
            browsers_dir = str(default_browsers_path())
        except Exception:
            browsers_dir = ""
        try:
            env = dict(os.environ)
            if browsers_dir:
                env.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers_dir)
            no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if getattr(sys, "frozen", False):
                roots = []
                try:
                    roots.append(Path(sys._MEIPASS))  # type: ignore[attr-defined]
                except Exception:
                    pass
                roots.append(Path(sys.executable).resolve().parent)
                node = cli = None
                for root in roots:
                    cand_node = root / "playwright" / "driver" / ("node.exe" if os.name == "nt" else "node")
                    cand_cli = root / "playwright" / "driver" / "package" / "cli.js"
                    if cand_node.exists() and cand_cli.exists():
                        node, cli = cand_node, cand_cli
                        break
                if node is None or cli is None:
                    self.extralog.emit("— browser files missing from this install; reinstall the app, "
                                        "or keep using your own Chrome (no download needed for that).")
                    return
                cmd = [str(node), str(cli), "install", "chromium"]
            else:
                cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=600, cwd=str(self._root),
                env=env, creationflags=no_window,
            )
            tail = (proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]
            self.extralog.emit("— install output:\n" + tail if tail else "— install finished.")
            self.extralog.emit("— Chromium install done. Press Start." if proc.returncode == 0 else "— install failed; check your connection and try Install now again.")
        except Exception as e:  # noqa: BLE001
            self.extralog.emit(f"— install failed: {e}")

    # ============ HISTORY page ============
    def _build_history_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)
        t = QLabel("History")
        t.setObjectName("PageTitle")
        top.addWidget(t)
        top.addStretch(1)
        rb = QPushButton("Refresh")
        rb.setObjectName("Ghost")
        rb.clicked.connect(self._refresh_history)
        sb = QPushButton("Open screenshots")
        sb.setObjectName("Ghost")
        sb.clicked.connect(self._open_screenshots)
        top.addWidget(rb)
        top.addWidget(sb)
        lay.addLayout(top)

        rl = QLabel("RUNS  —  LATEST 100")
        rl.setObjectName("Section")
        lay.addWidget(rl)
        self._runs = QTableWidget(0, 6)
        self._runs.setHorizontalHeaderLabels(["Run", "Started", "State", "Qs", "Calls", "Target"])
        self._runs.setAlternatingRowColors(True)
        self._runs.setSelectionBehavior(QTableWidget.SelectRows)
        self._runs.setEditTriggers(QTableWidget.NoEditTriggers)
        self._runs.horizontalHeader().setStretchLastSection(True)
        self._runs.verticalHeader().setVisible(False)
        self._runs.itemSelectionChanged.connect(self._show_run_detail)
        lay.addWidget(self._runs, 2)

        dl = QLabel("STEPS  —  SELECTED RUN")
        dl.setObjectName("Section")
        lay.addWidget(dl)
        self._hsteps = QTableWidget(0, 5)
        self._hsteps.setHorizontalHeaderLabels(["State", "Question", "Action", "Check", "Problem"])
        self._hsteps.setAlternatingRowColors(True)
        self._hsteps.setSelectionBehavior(QTableWidget.SelectRows)
        self._hsteps.setEditTriggers(QTableWidget.NoEditTriggers)
        self._hsteps.horizontalHeader().setStretchLastSection(True)
        self._hsteps.verticalHeader().setVisible(False)
        lay.addWidget(self._hsteps, 2)
        return w

    def _db_path(self) -> Path:
        vals = load_env(self._root / ".env") | load_env(".env")
        raw = vals.get("DATABASE_PATH", "./artifacts/runs.sqlite") or "./artifacts/runs.sqlite"
        p = Path(raw)
        if not p.is_absolute():
            # prefer exe-adjacent artifacts, fall back to cwd
            cand = self._root / raw
            p = cand if cand.exists() else (Path.cwd() / raw)
        return p

    def _refresh_history(self):
        self._runs.setRowCount(0)
        self._hsteps.setRowCount(0)
        p = self._db_path()
        if not p.exists():
            self.statusBar().showMessage(f"No history yet ({p}). Run once to create it.")
            return
        try:
            con = sqlite3.connect(str(p))
            rows = con.execute(
                "SELECT run_id, started_at, state, questions_done, model_calls, target_url"
                " FROM runs ORDER BY started_at DESC LIMIT 100").fetchall()
            con.close()
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"Could not read history: {e}")
            return
        for r in rows:
            i = self._runs.rowCount()
            self._runs.insertRow(i)
            started = time.strftime("%m-%d %H:%M", time.localtime(r[1])) if r[1] else "—"
            for c, v in enumerate([r[0], started, r[2], str(r[3]), str(r[4]), (r[5] or "")[:80]]):
                self._runs.setItem(i, c, QTableWidgetItem(v))
        if rows:
            self._runs.selectRow(0)
        self.statusBar().showMessage(f"{len(rows)} runs from {p.name}.")

    def _show_run_detail(self):
        sel = self._runs.selectedItems()
        if not sel:
            return
        run_id = sel[0].text()
        self._hsteps.setRowCount(0)
        try:
            con = sqlite3.connect(str(self._db_path()))
            steps = con.execute(
                "SELECT state, question_id, action, verification, error FROM steps"
                " WHERE run_id=? ORDER BY id LIMIT 500", (run_id,)).fetchall()
            con.close()
        except Exception:
            return
        for s in steps:
            i = self._hsteps.rowCount()
            self._hsteps.insertRow(i)
            for c, v in enumerate(s):
                self._hsteps.setItem(i, c, QTableWidgetItem(str(v or "")))

    def _open_screenshots(self):
        vals = load_env(self._root / ".env") | load_env(".env")
        raw = vals.get("SCREENSHOT_DIR", "./artifacts/screenshots")
        p = Path(raw)
        if not p.is_absolute():
            p = self._root / raw
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    # ============ SETTINGS page ============
    def _build_settings_page(self) -> QWidget:
        outer = QWidget()
        lay = QVBoxLayout(outer)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Settings")
        t.setObjectName("PageTitle")
        top.addWidget(t)
        top.addStretch(1)
        self._btn_saver = QPushButton("Save")
        self._btn_saver.setObjectName("Primary")
        self._btn_saver.clicked.connect(self._save_settings_form)
        self._btn_reload = QPushButton("Reload")
        self._btn_reload.setObjectName("Ghost")
        self._btn_reload.clicked.connect(self._reload_settings_form)
        top.addWidget(self._btn_reload)
        top.addWidget(self._btn_saver)
        lay.addLayout(top)
        self._env_path_label = QLabel("")
        self._env_path_label.setObjectName("Muted")
        lay.addWidget(self._env_path_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form_lay = QVBoxLayout(inner)
        self._fields: dict[str, QWidget] = {}
        spec_by_key = {s[0]: s for s in FIELD_SPECS}
        for group, keys in GROUPS:
            gb = QGroupBox(group)
            fl = QFormLayout(gb)
            for k in keys:
                spec = spec_by_key.get(k)
                if not spec:
                    continue
                _, label, kind, choices = spec
                if kind == "bool":
                    wdg = QCheckBox(label)
                elif kind == "int":
                    wdg = QSpinBox()
                    wdg.setRange(0, 1000000)
                    lbl = QLabel(label)
                    fl.addRow(lbl, wdg)
                    self._fields[k] = wdg
                    continue
                elif kind == "combo":
                    wdg = QComboBox()
                    wdg.setEditable(True)
                    wdg.addItems(choices or [])
                else:
                    wdg = QLineEdit()
                    if kind == "password":
                        wdg.setEchoMode(QLineEdit.Password)
                if kind == "bool":
                    fl.addRow(wdg)
                else:
                    fl.addRow(QLabel(label), wdg)
                self._fields[k] = wdg
            form_lay.addWidget(gb)
        form_lay.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        return outer

    def _env_path(self) -> Path:
        cand = self._root / ".env"
        return cand

    def _reload_settings_form(self):
        from dotenv import dotenv_values
        path = self._env_path()
        self._env_path_label.setText(f"Editing {path}  —  API keys stay local, never logged.")
        example = {}
        ex = bundled_path(self._root, ".env.example")
        if ex.exists():
            example = dotenv_values(str(ex))
        vals = load_env(path)
        spec_by_key = {s[0]: s for s in FIELD_SPECS}
        for k, wdg in self._fields.items():
            kind = spec_by_key[k][2]
            raw = vals.get(k, example.get(k, "") or "")
            if kind == "bool":
                wdg.setChecked(str_to_bool(raw))
            elif kind == "int":
                try:
                    wdg.setValue(int(str(raw).strip() or "0"))
                except ValueError:
                    wdg.setValue(0)
            elif isinstance(wdg, QComboBox):
                wdg.setCurrentText(str(raw))
            else:
                wdg.setText(str(raw))

    def _save_settings_form(self):
        updates: dict[str, str] = {}
        spec_by_key = {s[0]: s for s in FIELD_SPECS}
        for k, wdg in self._fields.items():
            kind = spec_by_key[k][2]
            if kind == "bool":
                updates[k] = bool_to_str(wdg.isChecked())
            elif kind == "int":
                updates[k] = str(wdg.value())
            elif isinstance(wdg, QComboBox):
                updates[k] = wdg.currentText().strip()
            else:
                updates[k] = wdg.text()
            os.environ[k] = updates[k]
        try:
            save_env(self._env_path(), updates)
            self.statusBar().showMessage(f"Saved {len(updates)} keys to .env.")
            self._load_env_into_run_bar()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(e))

    # ============ lifecycle ============
    def closeEvent(self, event):
        try:
            if self._worker is not None and self._run_active:
                self._worker.request_stop()
                self._worker.wait(3000)
        except Exception:
            pass
        super().closeEvent(event)
