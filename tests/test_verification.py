"""Verification engine unit tests."""
from solver.schemas import PageSnapshot
from verification.verifier import Verdict, verify


def _snap(qid="q1", qtext="Q1?", feedback="", completion=False, visible="Q1?"):
    return PageSnapshot(url="u", title="t", visible_text=visible,
                        question_id=qid, question_text=qtext,
                        feedback_text=feedback, is_completion=completion)


def test_question_id_change_means_advanced():
    r = verify(_snap("q1", "Q1?"), _snap("q2", "Q2?"))
    assert r.verdict == Verdict.ADVANCED
    assert r.confirmed


def test_completion_detected():
    r = verify(_snap("q5", "Q5?"), _snap("", "", completion=True, visible="Quiz Complete!"))
    assert r.verdict == Verdict.COMPLETED
    assert r.confirmed


def test_no_change_detected():
    r = verify(_snap(), _snap())
    assert r.verdict == Verdict.NO_CHANGE


def test_feedback_without_transition():
    r = verify(_snap("q1", "Q1?"), _snap("q1", "Q1?", feedback="Correct! Accepted."))
    assert r.verdict == Verdict.FEEDBACK


def test_button_disappearance_alone_is_not_success():
    # Question vanished with no feedback and no new question => UNCERTAIN, not ADVANCED.
    r = verify(_snap("q1", "Q1?"), _snap("", "", visible="..."))
    assert r.verdict == Verdict.UNCERTAIN
    assert not r.confirmed


def test_text_change_confirms_advance():
    r = verify(_snap("q1", "What is 2+2?"), _snap("q1", "Capital of France?"))
    assert r.verdict == Verdict.ADVANCED
