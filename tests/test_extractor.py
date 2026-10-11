"""Extractor + classifier unit tests (no browser needed)."""
from perception.page_classifier import classify
from perception.question_extractor import extract
from solver.schemas import AnswerOption, ControlInfo, PageSnapshot, PageState, QuestionType


def _snap(**kw):
    base = dict(url="http://test/", title="t", visible_text="Q1: What is 2 + 2?",
                question_id="q1", question_text="Q1: What is 2 + 2?",
                options=[AnswerOption(option_id="a", text="3"),
                         AnswerOption(option_id="b", text="4")],
                controls=[ControlInfo(kind="button", name="Submit")])
    base.update(kw)
    return PageSnapshot(**base)


def test_extract_choice_question():
    q = extract(_snap())
    assert q is not None
    assert q.question_id == "q1"
    assert "2 + 2" in q.text
    assert len(q.options) == 2
    assert q.question_type in (QuestionType.MULTIPLE_CHOICE, QuestionType.SINGLE_SELECT)


def test_extract_option_text_preserved():
    q = extract(_snap())
    texts = {o.option_id: o.text for o in q.options}
    assert texts == {"a": "3", "b": "4"}


def test_extract_text_entry():
    s = _snap(question_id="q3", question_text="Type the word python", options=[],
              controls=[ControlInfo(kind="text", name="Your answer"),
                        ControlInfo(kind="button", name="Submit")])
    q = extract(s)
    assert q is not None
    assert q.question_type == QuestionType.TEXT_ENTRY


def test_multi_answer_detected():
    from perception.question_extractor import is_multi_answer

    assert is_multi_answer("In which three ways...? (Choose Three)")
    assert is_multi_answer("Select all that apply:")
    assert is_multi_answer("Check all that apply")
    assert not is_multi_answer("What is 2 + 2?")
    s = _snap(question_text="Which two statements are true? (Choose Two)")
    q = extract(s)
    assert q is not None and q.multi_answer is True


def test_multi_answer_blocked_from_submit():
    from agent.action_planner import plan
    from config import Settings
    from solver.schemas import AnswerCandidate

    s = _snap(question_text="Which two statements are true? (Choose Two)")
    q = extract(s)
    # A single id is not enough for a multi-answer question.
    res = plan(q, AnswerCandidate(selected_option_id="a"), Settings())
    assert res.blocked
    assert "multi-answer" in res.reason
    # Two valid ids plan two selections + one submit.
    from browser.executor import ActionType

    res2 = plan(q, AnswerCandidate(selected_option_ids=["a", "b"]), Settings())
    assert not res2.blocked, res2.reason
    selects = [a for a in res2.actions if a.type == ActionType.SELECT_OPTION]
    clicks = [a for a in res2.actions if a.type == ActionType.CLICK_BUTTON]
    assert [a.option_id for a in selects] == ["a", "b"]
    assert len(clicks) == 1


def test_multi_validation_counts():
    from solver.base import validate_candidate
    from solver.schemas import AnswerCandidate, AnswerOption, Question, QuestionType

    q = Question(question_id="q", text="Choose Two", options=[
        AnswerOption(option_id="a", text="1"),
        AnswerOption(option_id="b", text="2"),
        AnswerOption(option_id="c", text="3"),
    ], question_type=QuestionType.SINGLE_SELECT, multi_answer=True, required_count=2)
    ok, _ = validate_candidate(q, AnswerCandidate(selected_option_ids=["a", "b"]))
    assert ok
    bad, reason = validate_candidate(q, AnswerCandidate(selected_option_ids=["a", "zzz"]))
    assert not bad and "zzz" in reason
    short, reason2 = validate_candidate(q, AnswerCandidate(selected_option_ids=["a"]))
    assert not short and "two" in reason2
    wrong_n, reason3 = validate_candidate(q, AnswerCandidate(selected_option_ids=["a", "b", "c"]))
    assert not wrong_n and "2" in reason3


def test_required_count_parsing():
    from perception.question_extractor import required_count

    assert required_count("Choose Three please") == 3
    assert required_count("select 2 options") == 2
    assert required_count("Select all that apply") is None
    assert required_count("What is 2+2?") is None


def test_extract_no_question_returns_none():
    s = PageSnapshot(url="http://t", title="t", visible_text="welcome home")
    assert extract(s) is None


def test_extract_unsupported_when_no_controls():
    s = _snap(options=[], controls=[])
    q = extract(s)
    assert q is not None
    assert q.question_type == QuestionType.UNSUPPORTED


def test_classify_question():
    assert classify(_snap()) == PageState.QUESTION


def test_classify_completion():
    s = _snap(question_text="", options=[], is_completion=True,
              visible_text="Quiz Complete! Final score: 5/5")
    assert classify(s) == PageState.COMPLETION


def test_option_text_containing_completion_is_not_completion():
    """Regression: the PL/SQL identifier 'completion_%' as an answer option
    must not flag a mid-exam page as completed."""
    from browser.observer import COMPLETION_PHRASES

    low_text = ("question 10 of 50\nwhich of the following are valid identifiers? (choose two)\n"
                "v_code\ncompletion_%\n_abc\n#x\n"
                "take the assessment\nchoices - select all that apply.\n").lower()
    assert "completion" in low_text  # the trap is really present
    assert not any(k in low_text for k in COMPLETION_PHRASES)
    # ...while genuine completion pages still match.
    assert any(k in "assessment submitted successfully. final score: 9/9" for k in COMPLETION_PHRASES)


def test_classify_ambiguous():
    s = PageSnapshot(url="u", title="t", visible_text="mystery page with no hooks")
    assert classify(s) == PageState.AMBIGUOUS
