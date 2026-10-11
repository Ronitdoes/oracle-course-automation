"""Answer checker: compares the page before and after clicking, using several clues."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from solver.schemas import PageSnapshot


class Verdict(str, Enum):
    ADVANCED = "advanced"          # next question detected
    NAVIGATED = "navigated"        # page moved on (lesson/lobby forward click worked)
    COMPLETED = "completed"        # completion screen detected
    FEEDBACK = "feedback"          # feedback shown, question may still be on screen
    NO_CHANGE = "no_change"        # page did not respond
    UNCERTAIN = "uncertain"        # ambiguous outcome


@dataclass
class VerificationResult:
    verdict: Verdict
    detail: str = ""
    confirmed: bool = False


def verify(before: PageSnapshot, after: PageSnapshot) -> VerificationResult:
    # Strongest clue first: the finished page.
    if after.is_completion:
        return VerificationResult(Verdict.COMPLETED, "finished page detected - the quiz looks complete", True)
    # Question changed => moved on (do not rely on a button disappearing alone).
    if before.question_id and after.question_id and before.question_id != after.question_id:
        return VerificationResult(Verdict.ADVANCED,
                                  f"moved from question {before.question_id} to question {after.question_id}", True)
    if before.question_text and after.question_text and before.question_text != after.question_text:
        return VerificationResult(Verdict.ADVANCED, "the next question appeared (text is different)", True)
    # Page address changed with no question handover (lesson/lobby forward
    # click): the walk moved on. Checked after question clues so a real
    # question transition still counts as ADVANCED, not just moved.
    if (before.url or "") != (after.url or ""):
        return VerificationResult(Verdict.NAVIGATED,
                                  f"page address changed to {(after.url or '')[:120]}", True)
    # Before had a question, after has none + a result message => likely submitted, waiting for next.
    if before.question_text and not after.question_text and after.feedback_text:
        return VerificationResult(Verdict.FEEDBACK, f"the page shows a result message: {after.feedback_text[:120]}", False)
    if before.question_text and not after.question_text and not after.feedback_text:
        return VerificationResult(Verdict.UNCERTAIN, "the question disappeared but the page shows no result message yet", False)
    if after.feedback_text and after.question_text:
        return VerificationResult(Verdict.FEEDBACK, f"the page shows a result message: {after.feedback_text[:120]}", False)
    # No meaningful change.
    if (before.question_id == after.question_id and before.question_text == after.question_text):
        if before.visible_text == after.visible_text:
            return VerificationResult(Verdict.NO_CHANGE, "the page looks exactly the same as before the click", False)
        return VerificationResult(Verdict.UNCERTAIN, "some text changed but it is unclear whether a new question appeared", False)
    return VerificationResult(Verdict.UNCERTAIN, "unclear what happened after the click; needs another look", False)
