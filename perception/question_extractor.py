"""Reads a page summary into a standard question. Returns nothing when there is no question, or marks the question as needing a person instead of guessing."""
from __future__ import annotations

import logging
import re

from solver.schemas import PageSnapshot, Question, QuestionSource, QuestionType

log = logging.getLogger(__name__)

# Quiz-style pages expose no question markers: "Question 3 of 50" + "Choices ...".
QUESTION_OF_RE = re.compile(r"question\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
CHOICES_RE = re.compile(r"^choices\b.*", re.IGNORECASE)
BLOCK_STOP_RE = re.compile(r"^(submit|exit|instructions|next|previous|save)\b", re.IGNORECASE)
# Quiz footer text that follows the question when no Choices
# marker exists (e.g. True/False questions). Never part of the question.
FOOTER_RE = re.compile(
    r"^(\u00a9|copyright|contact us|terms of use|privacy|accessibility|"
    r"third party|cookie preferences|about oracle|version\s+\d|built with)",
    re.IGNORECASE)


def extract_apex_block(visible_text: str) -> tuple[str | None, str]:
    """Pure helper: (question_id, question_text) from a 'Question N of M' page.

    Returns (None, "") when the pattern is absent. Testable without a browser.
    """
    lines = (visible_text or "").splitlines()
    start = None
    number = None
    for i, line in enumerate(lines):
        m = QUESTION_OF_RE.search(line.strip())
        if m:
            start = i
            number = m.group(1)
            break
    if start is None:
        return None, ""
    body: list[str] = []
    for line in lines[start + 1:]:
        s = line.strip()
        if not s:
            continue
        if CHOICES_RE.match(s) or BLOCK_STOP_RE.match(s) or FOOTER_RE.match(s):
            break
        body.append(s)
    text = "\n".join(body).strip()[:2000]
    if not text:
        return None, ""
    return f"q{number}", text


def extract(snap: PageSnapshot) -> Question | None:
    """Return a Question, or None when the page holds no processable question."""
    qtext = (snap.question_text or "").strip()
    if not qtext:
        # Try to salvage a question line from visible text ("Q1: ...?").
        qtext = _salvage_question_line(snap.visible_text)
        if not qtext:
            return None
    # Detect text-entry: no options but an input control exists.
    has_text_input = any(c.kind == "text" for c in snap.controls)
    if snap.options:
        qtype = _classify_choice(qtext, len(snap.options))
        multi = is_multi_answer(qtext)
        return Question(question_id=snap.question_id, text=qtext, options=list(snap.options),
                        question_type=qtype, multi_answer=multi,
                        required_count=required_count(qtext) if multi else None,
                        source=QuestionSource.DOM, page_url=snap.url)
    if has_text_input:
        ctx = _code_or_math_context(snap.visible_text)
        return Question(question_id=snap.question_id, text=qtext, options=[],
                        question_type=QuestionType.TEXT_ENTRY, context=ctx,
                        source=QuestionSource.DOM, page_url=snap.url)
    # Question-like text but no choices/typing box: could be a type that needs
    # a person (e.g. drag-and-drop, drawing) - mark it as such, don't invent choices.
    if qtext:
        log.info("The question has no choices or typing box, so it needs a person to answer it (marked as not supported)")
        return Question(question_id=snap.question_id, text=qtext, options=[],
                        question_type=QuestionType.UNSUPPORTED, source=QuestionSource.DOM,
                        page_url=snap.url)
    return None


def _classify_choice(qtext: str, n_options: int) -> QuestionType:
    low = qtext.lower()
    if any(k in low for k in ("select all", "choose all", "multiple answers", "check all")):
        return QuestionType.MULTIPLE_CHOICE
    if n_options >= 2:
        return QuestionType.SINGLE_SELECT
    return QuestionType.MULTIPLE_CHOICE


MULTI_ANSWER_RE = re.compile(
    r"choose\s+(two|three|four|five|\d+)|select\s+(two|three|four|five|\d+)\b"
    r"|check\s+all\s+that\s+apply|mark\s+all\s+that\s+apply|all\s+that\s+apply",
    re.IGNORECASE)

_WORD_COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5}


def is_multi_answer(qtext: str) -> bool:
    """'Choose Three' / 'select two' / 'check all that apply' need more than one choice."""
    return bool(MULTI_ANSWER_RE.search(qtext or ""))


def required_count(qtext: str) -> int | None:
    """Exact number to select ('choose three' -> 3); None when open-ended."""
    m = re.search(r"(?:choose|select)\s+(two|three|four|five|\d+)", qtext or "", re.IGNORECASE)
    if not m:
        return None
    word = m.group(1).lower()
    return _WORD_COUNTS.get(word, int(word) if word.isdigit() else None)


def _salvage_question_line(visible: str) -> str:
    for line in (visible or "").splitlines():
        s = line.strip()
        if len(s) < 10:
            continue
        if s.endswith("?") or re.match(r"^(q\d+[:.)]|question\s*\d+)", s, re.I):
            return s[:1000]
    return ""


def _code_or_math_context(visible: str) -> str | None:
    # Preserve code/math context lines so the solver sees them.
    keep = []
    for line in (visible or "").splitlines():
        s = line.rstrip()
        if any(tok in s for tok in ("def ", "print(", "```", "==", "+=", "∑", "∫", "√", "^2", "f(x)")):
            keep.append(s)
    return "\n".join(keep[:20]) or None
