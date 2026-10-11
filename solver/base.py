"""Answer-helper basics and answer checks."""
from __future__ import annotations

from abc import ABC, abstractmethod

from solver.schemas import AnswerCandidate, AnswerStatus, Question, QuestionType


class BaseSolver(ABC):
    @abstractmethod
    async def solve(self, question: Question) -> AnswerCandidate:
        raise NotImplementedError


def validate_candidate(question: Question, candidate: AnswerCandidate) -> tuple[bool, str]:
    """Return (ok, reason why not). Simple helper with no side effects, easy to test."""
    if candidate.status == AnswerStatus.UNRESOLVED:
        return False, "the helper could not find an answer (unresolved)"
    if question.question_type == QuestionType.UNSUPPORTED:
        return False, "this question type needs a person to answer it (unsupported)"
    if question.question_type == QuestionType.TEXT_ENTRY:
        if not candidate.text_answer or not candidate.text_answer.strip():
            return False, "a typing question needs some typed text"
        return True, "ok"
    if question.multi_answer:
        ids = list(candidate.selected_option_ids or [])
        if candidate.selected_option_id and candidate.selected_option_id not in ids:
            ids.append(candidate.selected_option_id)
        valid_ids = {o.option_id for o in question.options}
        bad = [i for i in ids if i not in valid_ids]
        if bad:
            return False, f"unknown choices {bad} are not on the page: {sorted(valid_ids)}"
        if len(ids) < 2:
            return False, "a multi-answer question needs at least two choices picked"
        if len(set(ids)) != len(ids):
            return False, "the same choice was picked twice"
        if question.required_count is not None and len(ids) != question.required_count:
            return False, f"the question asks for {question.required_count} choices (two means 2), but {len(ids)} were picked"
        return True, "ok"
    # Choice questions need one valid picked choice.
    if not candidate.selected_option_id:
        return False, "a choice question needs one choice picked"
    valid_ids = {o.option_id for o in question.options}
    if candidate.selected_option_id not in valid_ids:
        return False, f"picked choice '{candidate.selected_option_id}' is not on the page: {sorted(valid_ids)}"
    return True, "ok"
