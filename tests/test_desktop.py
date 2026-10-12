"""Desktop .env round-trip + theme/worker import checks (no GUI needed)."""
from pathlib import Path

from app import env_store
from app.theme import stylesheet, pill_style


def test_env_roundtrip_preserves_comments(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("# comment\nTARGET_URL=https://old\nMAX_QUESTIONS=5\n", encoding="utf-8")
    env_store.save_env(p, {"TARGET_URL": "https://new", "DRY_RUN": "true"})
    text = p.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "TARGET_URL=https://new" in text
    assert "DRY_RUN=true" in text
    assert env_store.load_env(p)["MAX_QUESTIONS"] == "5"


def test_bool_helpers():
    assert env_store.str_to_bool("True") is True
    assert env_store.str_to_bool("false") is False
    assert env_store.bool_to_str(True) == "true"


def test_theme_tokens():
    css = stylesheet()
    assert "#FAFAF7" in css and "Georgia" in css
    assert "COMPLETED" not in pill_style("COMPLETED")  # returns css, not state name
    assert "#E4EADF" in pill_style("COMPLETED")


def test_worker_import():
    from app.worker import RunWorker, is_browser_missing_error
    assert RunWorker is not None
    assert is_browser_missing_error("Executable doesn't exist; run playwright install") is True


def test_cdp_open_tab_uses_raw_url_form():
    """Regression: /json/new?url=… is ignored by Chrome -> blank tab.
    Must use /json/new?<raw url>."""
    import json as _json
    from unittest.mock import patch
    from app import main_window as mw

    seen = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"url": mw.ACADEMY_URL}).encode()

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url if hasattr(req, "full_url") else req
        return FakeResp()

    with patch.object(mw.urllib.request, "urlopen", side_effect=fake_urlopen):
        assert mw._open_tab_via_cdp("http://localhost:9222", mw.ACADEMY_URL) is True
    assert seen["url"] == "http://localhost:9222/json/new?" + mw.ACADEMY_URL


def test_log_handler_filters_noisy_libraries():
    """Regression for UI lag: root-attached handler must drop INFO spam from
    third-party loggers, keep app logs and all warnings/errors."""
    import logging
    from app.worker import _SignalLogHandler

    got: list[str] = []
    h = _SignalLogHandler(got.append)
    h.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    def rec(name: str, level: int) -> logging.LogRecord:
        return logging.LogRecord(name, level, __file__, 1, "msg", None, None)

    h.emit(rec("httpx", logging.INFO))
    h.emit(rec("playwright", logging.INFO))
    assert got == []
    h.emit(rec("agent.controller", logging.INFO))
    h.emit(rec("browser.session", logging.INFO))
    assert len(got) == 2
    h.emit(rec("httpx", logging.ERROR))
    assert len(got) == 3 and "httpx" in got[-1]


def test_steps_and_logs_render_batched():
    """Steps/log signals buffer instead of re-laying out widgets per event."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.main_window import MainWindow
    from app.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    w = MainWindow()
    for i in range(3):
        w._on_step({"state": "OBSERVE", "question_id": f"q{i}",
                    "answer": "", "action": "", "verification": "v", "error": ""})
    w._append_log("hello")
    # Buffered: nothing painted yet.
    assert w._steps.rowCount() == 0
    assert len(w._pending_steps) == 3
    w._flush_pending()
    assert w._steps.rowCount() == 3
    assert "hello" in w._logview.toPlainText()
    w._on_progress({"questions_done": 0, "model_calls": 13,
                    "state": "RECOVER", "last_note": "page did not change: x"})
    assert "0 answers" in w._sub.text() and "13 model calls" in w._sub.text()
    assert "page did not change" in w._sub.text()
    w.close()
