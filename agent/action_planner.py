"""Decides which clicks to make for a proposed answer.

Rules: preview mode never submits, asks a person when required,
and never submits the same question twice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from browser.executor import Action, ActionType
from config import Settings
from solver.schemas import AnswerCandidate, AnswerStatus, PageSnapshot, PageState, Question, QuestionType


@dataclass
class PlanResult:
    actions: list[Action]
    blocked: bool = False
    reason: str = ""
    needs_approval: bool = False
    # My Classes hub choice metadata (title of the picked course card).
    course_title: str = ""


# Forward-only buttons the helper may click on lesson/lobby pages, in
# preference order per page kind. Anything else — Previous, Return to Course,
# Exit, Course — is never emitted, so the helper can only move forward.
LOBBY_BUTTONS = ("Take an Assessment",)
# Exam content pages (P15) show Finish Assessment as the forward submit;
# Save Progress only saves and returns without completing, so it stays last.
LESSON_BUTTONS = ("Save and Continue", "Finish Assessment", "Complete Assessment",
                  "Submit Assessment", "Submit", "Finish", "Save Progress")
HOME_BUTTONS = ("View course materials", "My Classes")

NEVER_CLICK = ("previous", "return", "exit", "course")


def _section_percent(hint: str) -> int | None:
    m = re.search(r"(\d+)\s*%", hint or "")
    return int(m.group(1)) if m else None


def _trailing_percent(text: str) -> int | None:
    """Progress number hiding at the end of a link name itself.

    The row lookup usually finds the number beside the link, but live pages
    sometimes bake it into the link's own accessible name instead
    ("Section 8 - ... 90%"). Same shape, other place.
    """
    m = re.search(r"(\d+)\s*%\s*$", text or "")
    return int(m.group(1)) if m else None


def _outline_rows(snap: PageSnapshot) -> list[tuple[str, int | None]]:
    """(name, percent) for each clickable course row, in page order.

    Matches numbered sections ("Section 8 - ...") as well as exam rows
    ("... Final Exam ...", "... Midterm Exam ...", "... Cumulative ... Exam ...")
    so exams can be refused explicitly instead of silently ignored. Percent
    comes from the row itself; None when not shown.
    """
    rows = []
    for c in snap.controls:
        name = (c.name or "").strip()
        if c.kind != "link" or not name:
            continue
        if not (re.match(r"section\s+\d+", name, re.IGNORECASE) or "exam" in name.lower()):
            continue
        pct = _section_percent(c.selector_hint)
        if pct is None:
            pct = _trailing_percent(name)
        rows.append((name, pct))
    return rows


def section_key(name: str) -> str:
    """Identity of an outline entry for redo detection: the name without any
    trailing progress number (which changes as work gets recorded)."""
    return re.sub(r"\s*\d+\s*%\s*$", "", name or "").strip()


def normalize_course_title(title: str) -> str:
    """Stable identity for a My Classes course card across runs.

    Lower-cased, whitespace-collapsed, trailing progress numbers stripped,
    so "Database Programming with SQL - English" matches itself even when
    the hub card or outline header adds spacing or a percent.
    """
    t = re.sub(r"\s*\d+\s*%\s*$", "", (title or "").strip())
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def course_title_key(title: str) -> str:
    return normalize_course_title(title)


def _take_class_rows(snap: PageSnapshot) -> list[tuple[str, int]]:
    """(course_title, occurrence) for each Take Class button, in page order.

    occurrence is the Nth Take Class button (0-based) for the executor to
    click, since every card reuses the identical visible name. Title comes
    from the observer's selector_hint (card heading lookup). When the hint is
    empty (live DOM without a heading), synthesize a stable positional title
    so finished courses are still skipped by order rather than collapsing to
    one identical name.
    """
    rows: list[tuple[str, int]] = []
    occ = 0
    for c in snap.controls:
        name = (c.name or "").strip()
        if c.kind not in ("button", "link", "submit"):
            continue
        if "take class" not in name.lower():
            continue
        raw_hint = (c.selector_hint or "").strip()
        title = raw_hint or ""
        # When the hint holds a whole card dump, keep the first title-like line.
        if "\n" in title:
            for line in [ln.strip() for ln in title.splitlines() if ln.strip()]:
                low = line.lower()
                if "take class" in low or low.startswith("by ") or low.startswith("section-"):
                    continue
                title = line
                break
        if not title or title.lower() == "take class":
            # No card title readable: fall back to positional identity.
            # Order is stable on the hub, so "#1, #2, ..." still walks each
            # card once and skips finished ones by position across runs.
            title = f"Take Class #{occ + 1}"
            if raw_hint and raw_hint.lower() != "take class":
                title = f"{raw_hint[:80]} (#{occ + 1})"
                break
        rows.append((title, occ))
        occ += 1
    return rows


def _classes_seen(snap: PageSnapshot) -> str:
    bits = []
    for title, _ in _take_class_rows(snap):
        bits.append(title[:80])
    return "; ".join(bits[:8])


def outline_course_title(snap: PageSnapshot) -> str:
    """Course title from an outline page (first header-like line).

    Live outline pages head with the course name
    ("Database Programming with SQL - English") before the breadcrumb
    ("Home \\ My Classes \\ Taking a Class"). Fixture pages share the shape.
    """
    lines = [(ln.strip()) for ln in (snap.visible_text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    skip = {"course outline", "taking a class", "home", "my classes",
            "home \\ my classes \\ taking a class", "home / my classes"}
    for ln in lines[:5]:
        if ln.lower() in skip:
            continue
        if len(ln) >= 4:
            return ln[:200]
    return lines[0][:200]


def _outline_seen(snap: PageSnapshot) -> str:
    """Short summary of the outline for stop messages (what was seen)."""
    bits = []
    for name, pct in _outline_rows(snap):
        bits.append(f"{name} ({pct}%)" if pct is not None else f"{name} (no number shown)")
    return "; ".join(bits[:8])


def _match_button(snap: PageSnapshot, wants: tuple[str, ...]) -> str:
    """Return the actual on-page button/link name matching the first wanted label."""
    names = [(c.name or "") for c in snap.controls
             if c.kind in ("button", "submit", "link") and (c.name or "").strip()]
    for want in wants:
        for name in names:
            if want.lower() in name.lower():
                return name
    return ""


def plan_navigation(snap: PageSnapshot, page_state: PageState, settings: Settings,
                    revisit: bool = False, finished: frozenset[str] = frozenset(),
                    finished_courses: frozenset[str] = frozenset()) -> PlanResult:
    """Plan forward clicks for a home/hub/lesson/lobby/outline page. Pure function.

    revisit=True means this lobby was already left once this run (its quiz
    was started from here): plan the way OUT (Save Progress) instead of
    starting the quiz again. finished holds outline entries already finished
    (recorded in earlier runs): they are skipped, never re-entered.
    finished_courses holds normalized My Classes course titles already fully
    completed: their Take Class cards are skipped, never re-entered.
    """
    actions: list[Action] = []
    course_title = ""
    if page_state == PageState.HOME:
        entry = _match_button(snap, HOME_BUTTONS)
        if not entry:
            return PlanResult([], blocked=True,
                              reason="home page has no My Classes entry (View course materials)")
        actions = [Action(type=ActionType.NAVIGATE, button_name=entry,
                          timeout_ms=settings.action_timeout_ms,
                          label="My Classes")]
    elif page_state == PageState.CLASSES:
        rows = _take_class_rows(snap)
        if not rows:
            return PlanResult([], blocked=True, reason="My Classes hub has no Take Class buttons")
        done_keys = {normalize_course_title(c) for c in finished_courses}
        open_rows = [(t, occ) for t, occ in rows
                     if normalize_course_title(t) not in done_keys]
        if not open_rows:
            seen = _classes_seen(snap)
            return PlanResult([], blocked=True,
                              reason=f"no unfinished class found on My Classes hub{(': ' + seen) if seen else ''}")
        title, occ = open_rows[0]
        course_title = section_key(title)
        actions = [Action(type=ActionType.NAVIGATE, button_name="Take Class",
                          timeout_ms=settings.action_timeout_ms,
                          occurrence=occ,
                          label=f"Take Class - {title[:80]}")]
    elif page_state == PageState.LOBBY and revisit:
        leave = _match_button(snap, ("Save Progress",))
        if not leave:
            return PlanResult([], blocked=True,
                              reason="quiz lobby already finished but no Save Progress button to leave with")
        actions = [Action(type=ActionType.NAVIGATE, button_name=leave, timeout_ms=settings.action_timeout_ms)]
    elif page_state == PageState.LOBBY:
        take = _match_button(snap, LOBBY_BUTTONS)
        if not take:
            return PlanResult([], blocked=True, reason="quiz start page has no Take an Assessment button")
        # Always both clicks: Take opens the pop-up box, Start confirms it.
        # A stale box from an earlier click is dismissed by the click step
        # itself before Take is clicked again, so this stays a fresh flow.
        actions = [Action(type=ActionType.NAVIGATE, button_name=take, timeout_ms=settings.action_timeout_ms),
                   Action(type=ActionType.NAVIGATE, button_name="Start", timeout_ms=settings.action_timeout_ms)]
    elif page_state == PageState.LESSON:
        forward = _match_button(snap, LESSON_BUTTONS)
        if not forward:
            return PlanResult([], blocked=True, reason="lesson page has no Save and Continue button")
        actions = [Action(type=ActionType.NAVIGATE, button_name=forward, timeout_ms=settings.action_timeout_ms)]
    elif page_state == PageState.OUTLINE:
        rows = _outline_rows(snap)
        open_rows = [(name, pct) for name, pct in rows
                     if (pct is None or pct < 100) and section_key(name) not in finished]
        if open_rows:
            section = open_rows[0][0]
        elif any(pct is None or pct < 100 for _, pct in rows):
            done = ", ".join(name for name, pct in rows
                             if (pct is None or pct < 100))[:200]
            return PlanResult([], blocked=True,
                              reason=f"already finished {done}; stopping so it does not redo finished work")
        else:
            seen = _outline_seen(snap)
            return PlanResult([], blocked=True,
                              reason=f"no unfinished section found on the course outline{(': ' + seen) if seen else ''}")
        actions = [Action(type=ActionType.NAVIGATE, button_name=section, timeout_ms=settings.action_timeout_ms)]
    else:
        return PlanResult([], blocked=True, reason=f"not a home, hub, lesson, quiz start, or outline page ({page_state.value})")
    for a in actions:
        low = (a.button_name or "").lower()
        # Backward-click guard: Previous / Return / Exit always refused.
        # Bare "Course" refused (the breadcrumb button that walks away),
        # but longer names containing "course" as ordinary words
        # ("View course materials...") are allowed forward clicks.
        if ("previous" in low or "return" in low or "exit" in low
                or low.strip() == "course"):
            return PlanResult([], blocked=True, reason=f"refusing backward click '{a.button_name}'")
    if settings.dry_run:
        return PlanResult(actions, blocked=True, reason="dry-run (preview mode): forward clicks prepared but not clicked",
                          course_title=course_title)
    return PlanResult(actions, blocked=False, reason="forward clicks ready",
                      needs_approval=bool(settings.require_approval),
                      course_title=course_title)


def plan(question: Question, candidate: AnswerCandidate, settings: Settings,
         already_submitted_ids: set[str] | None = None) -> PlanResult:
    already_submitted_ids = already_submitted_ids or set()
    if candidate.status == AnswerStatus.UNRESOLVED:
        return PlanResult([], blocked=True, reason="the helper could not find an answer (unresolved), so there is nothing to click")
    if question.question_id and question.question_id in already_submitted_ids:
        return PlanResult([], blocked=True, reason=f"duplicate submit avoided: {question.question_id} was already submitted, so it will not be submitted again")

    actions: list[Action] = []
    if question.question_type == QuestionType.TEXT_ENTRY:
        if not candidate.text_answer:
            return PlanResult([], blocked=True, reason="typed answer is missing, so there is nothing to type in")
        actions.append(Action(type=ActionType.FILL_TEXT, text=candidate.text_answer,
                              timeout_ms=settings.action_timeout_ms))
    elif question.question_type in (QuestionType.MULTIPLE_CHOICE, QuestionType.SINGLE_SELECT):
        if question.multi_answer:
            ids = list(candidate.selected_option_ids or [])
            if candidate.selected_option_id and candidate.selected_option_id not in ids:
                ids.append(candidate.selected_option_id)
            if len(ids) < 2:
                return PlanResult([], blocked=True, reason="multi-answer question needs at least two choices picked")
            # Clear first: a previous attempt (or re-run) may have left boxes
            # checked; without this the submit could carry extra selections.
            actions.append(Action(type=ActionType.CLEAR_SELECTIONS,
                                  timeout_ms=settings.action_timeout_ms))
            actions.extend(Action(type=ActionType.SELECT_OPTION, option_id=oid,
                                  timeout_ms=settings.action_timeout_ms) for oid in ids)
        elif not candidate.selected_option_id:
            return PlanResult([], blocked=True, reason="no choice was picked, so there is nothing to click")
        else:
            actions.append(Action(type=ActionType.CLEAR_SELECTIONS,
                                  timeout_ms=settings.action_timeout_ms))
            actions.append(Action(type=ActionType.SELECT_OPTION, option_id=candidate.selected_option_id,
                                  timeout_ms=settings.action_timeout_ms))
    else:
        return PlanResult([], blocked=True, reason=f"unsupported question type {question.question_type}; please answer it by hand")

    # Submit step (kept separate so preview mode or a person's approval can stop it).
    if settings.dry_run:
        return PlanResult(actions, blocked=True, reason="dry-run (preview mode): answer was prepared but not submitted")
    needs_approval = bool(settings.require_approval)
    actions.append(Action(type=ActionType.CLICK_BUTTON, button_name="Submit",
                          timeout_ms=settings.action_timeout_ms))
    return PlanResult(actions, blocked=False, reason="answer looks good, ready to click", needs_approval=needs_approval)
