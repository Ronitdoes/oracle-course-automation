"""Background runner: executes Controller.run() off the GUI thread."""
from __future__ import annotations

import asyncio
import logging
import threading

from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)

# Logger roots whose INFO lines are worth showing live. Anything else only
# reaches the log view at WARNING+ (kills httpx/playwright/asyncio spam that
# was saturating the GUI thread).
_APP_LOGGER_ROOTS = frozenset({
    "agent", "browser", "browser-agent", "perception",
    "solver", "verification", "storage", "app",
})

BROWSER_MISSING_HINTS = ("Executable doesn't exist", "Executable doesnt exist", "playwright install")


def is_browser_missing_error(msg: str) -> bool:
    m = msg or ""
    return any(h.lower() in m.lower() for h in ("executable doesn't exist", "executable doesnt exist", "has been closed")) and "playwright" in m.lower() or "Executable doesn't exist" in m


class _SignalLogHandler(logging.Handler):
    def __init__(self, emit):
        super().__init__()
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING:
                if record.name.split(".")[0] not in _APP_LOGGER_ROOTS:
                    return
            self._emit(self.format(record))
        except Exception:
            pass


class RunWorker(QThread):
    step = Signal(dict)        # {state, question_id, answer, action, verification, error}
    progress = Signal(dict)    # {state, questions_done, model_calls, actions_taken}
    logline = Signal(str)
    approval_needed = Signal(dict)  # {kind: question|nav, ...}
    finished = Signal(dict)    # controller summary

    def __init__(self, parent=None):
        super().__init__(parent)
        self._controller = None
        self._approval_event = threading.Event()
        self._approval_result = False
        self._stop_requested = False

    # -- approval bridge (called in worker thread, resolved from GUI thread) --
    def _ask_gui(self, payload: dict) -> bool:
        if self._stop_requested:
            return False
        self._approval_event.clear()
        self._approval_result = False
        self.approval_needed.emit(payload)
        # Wait until the dialog resolves (or stop requested).
        while not self._approval_event.wait(timeout=0.2):
            if self._stop_requested:
                return False
        return self._approval_result

    def resolve_approval(self, approved: bool) -> None:
        self._approval_result = bool(approved)
        self._approval_event.set()

    def request_stop(self) -> None:
        self._stop_requested = True
        try:
            if self._controller is not None:
                self._controller.request_stop()
        except Exception:
            pass
        self._approval_result = False
        self._approval_event.set()

    # -- main --
    def run(self) -> None:
        try:
            summary = asyncio.run(self._arun())
        except Exception as e:  # noqa: BLE001
            log.exception("Run worker failed: %s", e)
            summary = {"final_state": "FAILED", "error": str(e), "steps": [],
                       "questions_done": 0, "model_calls": 0}
        self.finished.emit(summary)

    async def _arun(self) -> dict:
        from config import get_settings
        from agent.controller import Controller

        settings = get_settings()
        handler = _SignalLogHandler(self.logline.emit)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self._controller = Controller(
                settings,
                approval_callback=self._approve_question,
                nav_approval_callback=self._approve_nav,
            )
            orig_log = self._controller._log_step

            async def _wrapped(state, qid="", qtext="", answer="", action="",
                              verification="", retries=0, error=""):
                await orig_log(state, qid, qtext, answer, action, verification, retries, error)
                try:
                    self.step.emit({
                        "state": state, "question_id": qid, "answer": answer,
                        "action": action, "verification": verification, "error": error,
                    })
                    sm = getattr(self._controller.sm, "current", None)
                    self.progress.emit({
                        "state": getattr(sm, "value", str(sm)) if sm else state,
                        "questions_done": self._controller.questions_done,
                        "model_calls": self._controller.model_calls,
                        "actions_taken": self._controller.actions_taken,
                        # Last check result, so the UI can show WHY a run is
                        # stuck (e.g. "page did not change") instead of just
                        # a flat answers count.
                        "last_note": verification or error or "",
                    })
                except Exception:
                    pass

            self._controller._log_step = _wrapped  # type: ignore[method-assign]
            self.progress.emit({"state": "INITIALIZE", "questions_done": 0,
                                "model_calls": 0, "actions_taken": 0, "last_note": ""})
            return await self._controller.run()
        finally:
            try:
                root.removeHandler(handler)
            except Exception:
                pass
            self._controller = None

    # -- callbacks wired into Controller (sync, called from its async loop) --
    def _approve_question(self, question, candidate) -> bool:
        try:
            options = [{"option_id": o.option_id, "text": o.text} for o in (question.options or [])]
        except Exception:
            options = []
        payload = {
            "kind": "question",
            "question_id": getattr(question, "question_id", "") or "",
            "text": getattr(question, "text", "") or "",
            "options": options,
            "proposed_option": getattr(candidate, "selected_option_id", None),
            "proposed_options": list(getattr(candidate, "selected_option_ids", None) or []),
            "proposed_text": getattr(candidate, "text_answer", None),
            "confidence": getattr(candidate, "confidence", None),
        }
        return self._ask_gui(payload)

    def _approve_nav(self, label) -> bool:
        return self._ask_gui({"kind": "nav", "label": str(label)})
