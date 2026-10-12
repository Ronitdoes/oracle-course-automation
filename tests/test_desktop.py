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

def _offscreen_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_setup_wizard_steers_fresh_install_to_real_key(tmp_path):
    """Fresh installs default to gemini (not mock) and demand a key."""
    _offscreen_app()
    from app.dialogs import SetupWizard

    dlg = SetupWizard(tmp_path / ".env",
                      {"LLM_PROVIDER": "mock", "MODEL_ID": "", "LLM_API_KEY": "",
                       "LLM_BASE_URL": "", "MAX_QUESTIONS": "20",
                       "AUTO_ADVANCE_LESSONS": "false", "REQUIRE_APPROVAL": "false"},
                      first_run=True)
    try:
        v = dlg.values()
        assert v["LLM_PROVIDER"] == "gemini"
        assert v["MODEL_ID"] == "gemini-3.5-flash-lite"
        assert "aistudio" in dlg._key_hint.text()
        assert dlg.validate() == "missing-key"
        dlg._key.setText("test-key-123")
        assert dlg.validate() == ""
        dlg.save()
        text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "LLM_PROVIDER=gemini" in text
        assert "LLM_API_KEY=test-key-123" in text
    finally:
        dlg.close()


def test_setup_wizard_mock_needs_no_key(tmp_path):
    _offscreen_app()
    from app.dialogs import SetupWizard

    dlg = SetupWizard(tmp_path / ".env", {"LLM_PROVIDER": "mock"}, first_run=False)
    try:
        assert dlg.values()["LLM_PROVIDER"] == "mock"
        assert dlg.validate() == ""
    finally:
        dlg.close()


def test_setup_wizard_first_run_fixes_mock_model_mismatch(tmp_path):
    """Fresh installs copy the mock-flavoured example (mock-model) then steer
    to gemini: the model field must follow, never provider=gemini + model=mock-model."""
    _offscreen_app()
    from app.dialogs import SetupWizard

    dlg = SetupWizard(tmp_path / ".env",
                      {"LLM_PROVIDER": "mock", "MODEL_ID": "mock-model",
                       "LLM_API_KEY": "", "LLM_API_KEYS": ""},
                      first_run=True)
    try:
        v = dlg.values()
        assert v["LLM_PROVIDER"] == "gemini"
        assert v["MODEL_ID"] == "gemini-3.5-flash-lite"
    finally:
        dlg.close()


def test_setup_wizard_provider_switch_suggests_model():
    _offscreen_app()
    from app.dialogs import SetupWizard
    from pathlib import Path as _P

    dlg = SetupWizard(_P("dummy.env"), {"LLM_PROVIDER": "mock", "MODEL_ID": "x"})
    try:
        dlg._model.clear()
        dlg._provider.setCurrentText("openai")
        assert dlg.values()["MODEL_ID"] == "gpt-4o-mini"
    finally:
        dlg.close()


def test_setup_wizard_provider_switch_auto_selects_model():
    """Switching provider auto-selects its default model (user only pastes the key)."""
    _offscreen_app()
    from app.dialogs import SetupWizard
    from pathlib import Path as _P

    dlg = SetupWizard(_P("dummy.env"), {"LLM_PROVIDER": "mock", "MODEL_ID": "x"})
    try:
        dlg._provider.setCurrentText("groq")
        assert dlg.values()["MODEL_ID"] == "openai/gpt-oss-120b"
        dlg._provider.setCurrentText("gemini")
        assert dlg.values()["MODEL_ID"] == "gemini-3.5-flash-lite"
        dlg._provider.setCurrentText("openai")
        assert dlg.values()["MODEL_ID"] == "gpt-4o-mini"
    finally:
        dlg.close()


def test_main_window_has_setup_button():
    _offscreen_app()
    from app.main_window import MainWindow
    from app.theme import apply_theme
    from PySide6.QtWidgets import QApplication

    apply_theme(QApplication.instance())
    w = MainWindow()
    try:
        assert w._btn_setup is not None
        assert w._btn_setup.text() == "Setup"
    finally:
        w.close()


def test_setup_popup_opens_and_saves_without_crash(tmp_path, monkeypatch):
    """Regression: the setup popup crashed on open (dlg.Accepted AttributeError),
    so first-run users never saw it. Accepting must save .env cleanly."""
    _offscreen_app()
    from PySide6.QtWidgets import QApplication, QDialog
    from app import dialogs as _dlgmod
    from app.main_window import MainWindow
    from app.theme import apply_theme

    apply_theme(QApplication.instance())
    w = MainWindow()
    try:
        monkeypatch.setattr(w, "_env_path", lambda: tmp_path / ".env")
        monkeypatch.setattr(_dlgmod.SetupWizard, "exec", lambda self: int(QDialog.Accepted))
        w._open_setup(first_run=True)  # must not raise
        text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "LLM_PROVIDER=" in text
    finally:
        w.close()


def test_needs_api_key_prompts_only_when_key_missing(monkeypatch):
    """The setup popup appears when a real provider has no key — never for mock."""
    _offscreen_app()
    from PySide6.QtWidgets import QApplication
    from app import main_window as _mw
    from app.main_window import MainWindow
    from app.theme import apply_theme

    apply_theme(QApplication.instance())
    monkeypatch.setattr(_mw, "load_env", lambda *a, **k: {})
    w = MainWindow()
    try:
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.setenv("LLM_API_KEY", "")
        monkeypatch.setenv("LLM_API_KEYS", "")
        assert w._needs_api_key() is True
        monkeypatch.setenv("LLM_API_KEYS", "k1,k2")
        assert w._needs_api_key() is False
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        monkeypatch.setenv("LLM_API_KEYS", "")
        assert w._needs_api_key() is False
    finally:
        w.close()
