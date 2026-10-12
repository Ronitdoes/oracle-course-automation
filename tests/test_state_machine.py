"""State machine / planner / recovery unit tests."""
import pytest

from agent.action_planner import plan
from agent.recovery import RecoveryManager
from agent.state_machine import AgentState, StateMachine
from browser.executor import ActionType
from config import Settings
from solver.schemas import (AnswerCandidate, AnswerOption, AnswerStatus,
                            Question, QuestionType)


def _settings(**kw):
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _q():
    return Question(question_id="q1", text="2+2?",
                    options=[AnswerOption(option_id="a", text="3"),
                             AnswerOption(option_id="b", text="4")],
                    question_type=QuestionType.SINGLE_SELECT)


def test_legal_transitions():
    sm = StateMachine()
    sm.transition(AgentState.OBSERVE, "t")
    sm.transition(AgentState.CLASSIFY, "t")
    sm.transition(AgentState.EXTRACT, "t")
    assert sm.current == AgentState.EXTRACT


def test_illegal_transition_raises():
    sm = StateMachine()
    with pytest.raises(ValueError):
        sm.transition(AgentState.ACT, "skip ahead")


def test_full_fsm_path_to_completed():
    sm = StateMachine()
    for nxt in [AgentState.OBSERVE, AgentState.CLASSIFY, AgentState.EXTRACT]:
        sm.transition(nxt, "t")
    # EXTRACT->SOLVE->VALIDATE->ACT->VERIFY->COMPLETED
    sm.transition(AgentState.SOLVE, "t")
    sm.transition(AgentState.VALIDATE, "t")
    sm.transition(AgentState.ACT, "t")
    sm.transition(AgentState.VERIFY, "t")
    sm.transition(AgentState.COMPLETED, "t")
    assert sm.current == AgentState.COMPLETED


def test_verify_may_stop_directly():
    # A check that clearly failed (e.g. nothing moved after retries) may end
    # the run from VERIFY without going through the retry step again.
    sm = StateMachine()
    sm.transition(AgentState.OBSERVE, "t")
    sm.transition(AgentState.CLASSIFY, "t")
    sm.transition(AgentState.NAVIGATE, "t")
    sm.transition(AgentState.ACT, "t")
    sm.transition(AgentState.VERIFY, "t")
    sm.transition(AgentState.STOPPED, "t")
    assert sm.current == AgentState.STOPPED


def test_returning_path_legal():
    # After a quiz, the helper may go back to the outline for the next section.
    sm = StateMachine()
    for nxt in [AgentState.OBSERVE, AgentState.CLASSIFY, AgentState.EXTRACT,
                AgentState.SOLVE, AgentState.VALIDATE, AgentState.ACT,
                AgentState.VERIFY]:
        sm.transition(nxt, "t")
    sm.transition(AgentState.RETURNING, "t")
    sm.transition(AgentState.OBSERVE, "t")
    assert sm.current == AgentState.OBSERVE
    sm2 = StateMachine()
    sm2.transition(AgentState.OBSERVE, "t")
    sm2.transition(AgentState.CLASSIFY, "t")
    sm2.transition(AgentState.NAVIGATE, "t")
    sm2.transition(AgentState.ACT, "t")
    sm2.transition(AgentState.VERIFY, "t")
    sm2.transition(AgentState.RETURNING, "t")
    sm2.transition(AgentState.COMPLETED, "t")
    assert sm2.current == AgentState.COMPLETED


def test_recovery_retry_limits():
    r = RecoveryManager(max_retries=2)
    assert r.should_retry("k", "e1").retry is True
    assert r.should_retry("k", "e2").retry is True
    dec = r.should_retry("k", "e3")
    assert dec.retry is False
    assert dec.escalate_to_human is True


def test_recovery_budgets_are_per_key():
    # The controller scopes generic recovery per question, so one hard
    # question cannot spend the retry budget of later questions.
    r = RecoveryManager(max_retries=1)
    assert r.should_retry("recover-q3", "e").retry is True
    assert r.should_retry("recover-q3", "e").retry is False
    assert r.should_retry("recover-q4", "e").retry is True


def test_recovery_prior_success_blocks_retry():
    r = RecoveryManager(max_retries=2)
    dec = r.should_retry("submit-q1", "timeout", maybe_already_succeeded=True)
    assert dec.retry is False


def test_dry_run_blocks_submit():
    s = _settings(dry_run=True)
    cand = AnswerCandidate(selected_option_id="a")
    res = plan(_q(), cand, s)
    assert res.blocked
    assert "dry-run" in res.reason
    assert all(a.type != ActionType.CLICK_BUTTON for a in res.actions)


def test_approval_flag_set():
    s = _settings(require_approval=True)
    res = plan(_q(), AnswerCandidate(selected_option_id="a"), s)
    assert res.needs_approval is True
    assert any(a.type == ActionType.CLICK_BUTTON for a in res.actions)


def test_duplicate_submit_prevented():
    s = _settings()
    res = plan(_q(), AnswerCandidate(selected_option_id="a"), s, {"q1"})
    assert res.blocked
    assert "duplicate" in res.reason


def test_unresolved_blocked():
    s = _settings()
    res = plan(_q(), AnswerCandidate(status=AnswerStatus.UNRESOLVED), s)
    assert res.blocked


def test_controller_over_limits_infinite():
    from agent.controller import Controller

    # 0 max_actions and 0 questions mean unlimited / infinite
    s = _settings(max_actions=0, run_max_duration_sec=0, max_questions=0)
    c = Controller(s)
    c.actions_taken = 999999
    c.questions_done = 999999
    assert c._over_limits() == ""

    # Even if run_max_duration_sec were present, no time limit is enforced
    s.run_max_duration_sec = 1
    c._t0 = 0.0
    assert c._over_limits() == ""

    # Positive action limits still enforced if explicitly configured
    s_capped = _settings(max_actions=10)
    c_capped = Controller(s_capped)
    c_capped.actions_taken = 10
    assert "click limit (10)" in c_capped._over_limits()

