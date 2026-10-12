"""Modal approval dialogs in the editorial style."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
)


class ApprovalDialog(QDialog):
    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Approval required")
        self.setModal(True)
        self.setMinimumWidth(520)
        kind = payload.get("kind", "question")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(28, 24, 28, 24)

        eyebrow = QLabel("APPROVAL  —  REVIEW BEFORE SUBMIT" if kind == "question" else "APPROVAL  —  FORWARD NAVIGATION")
        eyebrow.setObjectName("Section")
        layout.addWidget(eyebrow)

        if kind == "nav":
            title = QLabel("Planned forward clicks")
            title.setObjectName("Masthead")
            layout.addWidget(title)
            body = QLabel(str(payload.get("label", "")))
            body.setWordWrap(True)
            layout.addWidget(body)
            hint = QLabel("Only forward actions are ever planned. Previous / Exit are never clicked.")
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        else:
            qid = payload.get("question_id", "")
            title = QLabel(f"Question {qid}" if qid else "Question")
            title.setObjectName("Masthead")
            layout.addWidget(title)
            qtext = QLabel(str(payload.get("text", "")))
            qtext.setWordWrap(True)
            layout.addWidget(qtext)

            opts = QLabel("OPTIONS")
            opts.setObjectName("Section")
            layout.addWidget(opts)
            lst = QListWidget()
            proposed = set(payload.get("proposed_options") or [])
            if payload.get("proposed_option"):
                proposed.add(payload["proposed_option"])
            for o in payload.get("options", []):
                mark = "  ●" if o.get("option_id") in proposed else ""
                item = QListWidgetItem(f"{o.get('option_id')}: {o.get('text')}{mark}")
                if o.get("option_id") in proposed:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                lst.addItem(item)
            lst.setMaximumHeight(160)
            layout.addWidget(lst)

            prop_lines = []
            if payload.get("proposed_option"):
                prop_lines.append(f"choice = {payload['proposed_option']}")
            if payload.get("proposed_options"):
                prop_lines.append(f"choices = {payload['proposed_options']}")
            if payload.get("proposed_text"):
                prop_lines.append(f"typed = {payload['proposed_text']}")
            if payload.get("confidence") is not None:
                prop_lines.append(f"confidence = {payload['confidence']}")
            prop = QLabel(("Proposed: " + "  ·  ".join(prop_lines)) if prop_lines else "Proposed: —")
            prop.setObjectName("Muted")
            prop.setWordWrap(True)
            layout.addWidget(prop)

        row = QHBoxLayout()
        row.addStretch(1)
        reject = QPushButton("Reject")
        reject.setObjectName("Ghost")
        approve = QPushButton("Approve & submit")
        approve.setObjectName("Primary")
        approve.setDefault(True)
        row.addWidget(reject)
        row.addWidget(approve)
        layout.addLayout(row)

        reject.clicked.connect(lambda: self.done(QDialog.Rejected))
        approve.clicked.connect(lambda: self.done(QDialog.Accepted))


PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    # Suggested model + base URL per answer service. The key hint tells a new
    # user exactly where to get their key; mock needs none.
    "mock": {
        "model": "mock-model",
        "base": "https://api.openai.com/v1",
        "key_hint": "Practice mode works offline and needs no key.",
    },
    "gemini": {
        "model": "gemini-3.5-flash-lite",
        "base": "https://generativelanguage.googleapis.com/v1beta",
        "key_hint": "Free key from Google AI Studio: https://aistudio.google.com/apikey",
    },
    "groq": {
        "model": "openai/gpt-oss-120b",
        "base": "https://api.groq.com/openai/v1",
        "key_hint": "Free key from Groq Console: https://console.groq.com/keys",
    },
    "openai": {
        "model": "gpt-4o-mini",
        "base": "https://api.openai.com/v1",
        "key_hint": "Key from https://platform.openai.com/api-keys (or your compatible host).",
    },
}


class SetupWizard(QDialog):
    """First-run setup: AI key + the settings a new user must get right.

    Covers the essentials (answer service, model, key, limits, lesson
    walking); everything else stays editable later in Settings. Testable
    without showing: build with (env_path, initial), read values(), call
    validate() and save().
    """

    def __init__(self, env_path: Path | str, initial: dict | None = None,
                 first_run: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome — first-time setup")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._env_path = Path(env_path)
        initial = dict(initial or {})
        provider = (initial.get("LLM_PROVIDER") or "mock").strip().lower()
        if provider not in PROVIDER_DEFAULTS:
            provider = "mock"
        if first_run and provider == "mock" and not ((initial.get("LLM_API_KEY") or "").strip() or (initial.get("LLM_API_KEYS") or "").strip()):
            # Fresh installs come from the mock-flavoured example file; steer
            # new users at a real answer service instead of silent wrong
            # answers (mock only knows the practice page).
            provider = "gemini"

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(28, 24, 28, 24)

        title = QLabel("First-time setup")
        title.setObjectName("Masthead")
        lay.addWidget(title)
        sub = QLabel("Enter your AI key once. Everything else can be changed later in Settings.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        ai = QLabel("AI ANSWER SERVICE")
        ai.setObjectName("Section")
        lay.addWidget(ai)

        self._provider = QComboBox()
        self._provider.setEditable(False)
        self._provider.addItems(["gemini", "groq", "openai", "mock"])
        self._provider.setCurrentText(provider)
        lay.addWidget(QLabel("Provider"))
        lay.addWidget(self._provider)

        self._model = QLineEdit()
        lay.addWidget(QLabel("Model ID"))
        lay.addWidget(self._model)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._key.setPlaceholderText("paste your key here")
        lay.addWidget(QLabel("API key"))
        lay.addWidget(self._key)

        self._keys_extra = QLineEdit()
        self._keys_extra.setPlaceholderText("optional backup keys, comma-separated (auto-failover)")
        lay.addWidget(QLabel("Backup API keys (failover, optional)"))
        lay.addWidget(self._keys_extra)

        self._key_hint = QLabel("")
        self._key_hint.setObjectName("Muted")
        self._key_hint.setWordWrap(True)
        lay.addWidget(self._key_hint)

        self._base_default = (initial.get("LLM_BASE_URL") or "").strip()

        run = QLabel("RUN")
        run.setObjectName("Section")
        lay.addWidget(run)

        self._max_q = QSpinBox()
        self._max_q.setRange(1, 5000)
        lay.addWidget(QLabel("Max questions"))
        lay.addWidget(self._max_q)

        self._approval = QCheckBox("Require approval before each submit")
        lay.addWidget(self._approval)

        # Seed from the existing file, falling back to provider suggestions.
        # A leftover mock default with a real provider (fresh installs copy the
        # mock-flavoured example file, then steer to gemini) is fixed to that
        # provider's model instead of showing a mismatched pair like
        # provider=gemini + model=mock-model.
        _seed_model = (initial.get("MODEL_ID") or "").strip()
        if not _seed_model or (provider != "mock" and _seed_model == "mock-model"):
            _seed_model = PROVIDER_DEFAULTS[provider]["model"]
        self._model.setText(_seed_model)
        self._key.setText((initial.get("LLM_API_KEY") or "").strip())
        self._keys_extra.setText((initial.get("LLM_API_KEYS") or "").strip())
        try:
            self._max_q.setValue(int(str(initial.get("MAX_QUESTIONS") or "500").strip() or "500"))
        except ValueError:
            self._max_q.setValue(500)
        self._approval.setChecked(_str_to_bool(initial.get("REQUIRE_APPROVAL", "false")))
        self._refresh_provider_hint()
        self._provider.currentTextChanged.connect(self._on_provider_changed)

        row = QHBoxLayout()
        row.addStretch(1)
        skip = QPushButton("Skip for now")
        skip.setObjectName("Ghost")
        save = QPushButton("Save & continue")
        save.setObjectName("Primary")
        save.setDefault(True)
        row.addWidget(skip)
        row.addWidget(save)
        lay.addLayout(row)
        skip.clicked.connect(lambda: self.done(QDialog.Rejected))
        save.clicked.connect(self._on_save)

    # -- logic (UI-free, unit-tested) --
    def _base_url(self) -> str:
        """Kept out of the UI: existing value wins, else the provider default."""
        if self._base_default:
            return self._base_default
        name = self._provider.currentText().strip().lower()
        return PROVIDER_DEFAULTS.get(name, PROVIDER_DEFAULTS["mock"])["base"]

    def values(self) -> dict[str, str]:
        return {
            "LLM_PROVIDER": self._provider.currentText().strip(),
            "MODEL_ID": self._model.text().strip(),
            "LLM_API_KEY": self._key.text().strip(),
            "LLM_API_KEYS": self._keys_extra.text().strip(),
            "LLM_BASE_URL": self._base_url(),
            "MAX_QUESTIONS": str(self._max_q.value()),
            # Auto-advance is always on: the app walks courses by itself.
            "AUTO_ADVANCE_LESSONS": "true",
            "REQUIRE_APPROVAL": "true" if self._approval.isChecked() else "false",
        }

    def validate(self) -> str:
        """Return "" when the values are usable, else the problem to show."""
        v = self.values()
        if not v["MODEL_ID"]:
            return "Model ID is empty."
        if v["LLM_PROVIDER"] in ("gemini", "groq", "openai") and not (v["LLM_API_KEY"] or v["LLM_API_KEYS"]):
            return "missing-key"
        return ""

    def save(self) -> None:
        from app.env_store import save_env
        save_env(self._env_path, self.values())

    # -- UI wiring --
    def _on_provider_changed(self, name: str) -> None:
        # Auto-select the default model for the chosen provider (so a fresh
        # user only pastes the API key), but never clobber a custom model the
        # user typed themselves — only empty or known-default values refresh.
        name = (name or "").strip().lower()
        if name in PROVIDER_DEFAULTS:
            current = self._model.text().strip()
            known = {d["model"] for d in PROVIDER_DEFAULTS.values()} | {
                "mock-model", "gemini-2.0-flash"}
            if not current or current in known:
                self._model.setText(PROVIDER_DEFAULTS[name]["model"])
        self._refresh_provider_hint()

    def _refresh_provider_hint(self) -> None:
        name = self._provider.currentText().strip().lower()
        self._key_hint.setText(PROVIDER_DEFAULTS.get(name, {}).get("key_hint", ""))

    def _on_save(self) -> None:
        problem = self.validate()
        if problem == "missing-key":
            go = QMessageBox.question(
                self, "No API key",
                "You chose a real answer service but left the key empty — "
                "runs will fail until you add one in Settings.\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if go != QMessageBox.Yes:
                return
        elif problem:
            QMessageBox.warning(self, "Setup incomplete", problem)
            return
        try:
            self.save()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self.done(QDialog.Accepted)


def _str_to_bool(v: object) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}
