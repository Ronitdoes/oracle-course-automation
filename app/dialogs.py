"""Modal approval dialogs in the editorial style."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton,
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
