"""Sorts the page into kinds (question, loading, finished...) without needing AI."""
from __future__ import annotations

import re

from solver.schemas import PageSnapshot, PageState


def _named_control_names(snap: PageSnapshot) -> list[str]:
    # Buttons AND links: the quiz entry ("Take an Assessment") is a link on
    # the real site, while the Save buttons are real buttons.
    return [(c.name or "").lower() for c in snap.controls if c.kind in ("button", "submit", "link")]


def _has_button(snap: PageSnapshot, needle: str) -> bool:
    return any(needle in name for name in _named_control_names(snap))


def _section_links(snap: PageSnapshot) -> list[str]:
    return [(c.name or "").strip() for c in snap.controls
            if c.kind == "link" and (re.match(r"section\s+\d+", (c.name or "").strip(), re.IGNORECASE)
                                     or "exam" in (c.name or "").lower())]


def _has_take_class(snap: PageSnapshot) -> bool:
    return _has_button(snap, "take class")


def _is_home(snap: PageSnapshot) -> bool:
    low = (snap.visible_text or "").lower()
    if "my student benefits" in low:
        return True
    if "my classes" in low and "student tools" in low and "free resources" in low:
        return True
    # Landing cards link out via "View course materials assigned by a faculty member".
    if "view course materials" in low and _has_button(snap, "view course materials"):
        return True
    return False


def classify(snap: PageSnapshot) -> PageState:
    if snap.is_loading and not snap.question_text and not snap.is_completion:
        return PageState.LOADING
    if snap.is_completion:
        return PageState.COMPLETION
    # Forward-walk buttons beat everything below: a lesson/lobby page can
    # contain question-like words (or sidebar choice controls), but the
    # presence of these buttons is the stronger signal. Question pages never
    # show them. LOBBY first: lobby pages also carry a Save Progress button.
    if _has_button(snap, "take an assessment"):
        return PageState.LOBBY
    if _has_button(snap, "save and continue") or _has_button(snap, "save progress"):
        # My Classes hub has no Save buttons; outline/lesson pages do.
        # Take Class hub check comes next so it cannot be mistaken here.
        return PageState.LESSON
    # My Classes hub: one identical "Take Class" button per course card.
    # No other page kind uses that wording ("Take an Assessment" is the lobby).
    if _has_take_class(snap):
        return PageState.CLASSES
    # Oracle Academy landing after login (Discover banner + My Student Benefits).
    if _is_home(snap):
        return PageState.HOME
    if "course outline" in (snap.visible_text or "").lower() and _section_links(snap):
        return PageState.OUTLINE
    if snap.feedback_text and not snap.question_text:
        return PageState.FEEDBACK
    if snap.question_id or snap.question_text or snap.options:
        return PageState.QUESTION
    # Weak signal: visible text mentions question but extraction failed.
    low = (snap.visible_text or "").lower()
    if "question" in low and len(snap.visible_text) > 20:
        return PageState.AMBIGUOUS
    if snap.feedback_text:
        return PageState.FEEDBACK
    return PageState.AMBIGUOUS
