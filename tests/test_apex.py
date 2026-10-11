"""APEX-shaped pages: no data-* hooks, 'Question N of M' text, plain radios,
persistent instructional banner. Uses tests/fixture/apex.html (local only)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.action_planner import plan
from browser import executor as browser_executor
from browser.executor import Action, ActionType
from browser.observer import observe
from browser.session import BrowserSession
from config import Settings
from perception.page_classifier import classify
from perception.question_extractor import extract, extract_apex_block
from solver.base import validate_candidate
from solver.schemas import (AnswerCandidate, AnswerOption, PageSnapshot, PageState,
                            Question, QuestionType)
from verification.verifier import Verdict, verify

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixture" / "apex.html"


def _settings(tmp_path):
    s = Settings()
    s.target_url = FIXTURE.as_uri()
    s.headless = True
    s.connection_mode = "launch"  # isolate from ambient .env (operator may use cdp)
    s.llm_provider = "mock"
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    return s


def test_apex_block_helper():
    visible = "Take the Assessment\nQuestion 2 of 50\nWhat is 2 + 2?\nChoices - Just one correct!\n3\n4\n"
    qid, text = extract_apex_block(visible)
    assert qid == "q2"
    assert "2 + 2" in text
    assert "Choices" not in text


def test_apex_block_absent():
    assert extract_apex_block("welcome home\nnothing here") == (None, "")


def test_apex_block_stops_at_footer():
    visible = ("Take the Assessment\nQuestion 3 of 10\n"
               "Reserved words can be used as identifiers. True or False?\n"
               "True or False?\nTrue\nFalse\n"
               "\u00a9 2026, Oracle and/or its affiliates.\nContact Us\nTerms of Use\n"
               "Version 2.0.2026318 Built with using Oracle APEX\n")
    qid, text = extract_apex_block(visible)
    assert qid == "q3"
    assert "Reserved words" in text
    assert "Oracle and/or" not in text
    assert "Contact Us" not in text


async def test_apex_observe_extract_classify(tmp_path):
    s = _settings(tmp_path)
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        snap = await observe(page)
        assert snap.question_id == "q2", snap
        assert "PRICE" in snap.question_text
        assert len(snap.options) == 4
        # Entity-encoded aria-label decoded.
        assert any("would fail" in o.text and "&#" not in o.text for o in snap.options)
        # Instructional banner must not count as submission feedback.
        assert snap.feedback_text == "", repr(snap.feedback_text)
        assert classify(snap) == PageState.QUESTION
        q = extract(snap)
        assert q is not None and q.question_type == QuestionType.SINGLE_SELECT
    finally:
        await sess.close()


async def test_apex_select_submit_advance(tmp_path):
    s = _settings(tmp_path)
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        before = await observe(page)
        q = extract(before)
        cand = AnswerCandidate(selected_option_id="opt-1", confidence=0.9)  # correct per fixture
        ok, reason = validate_candidate(q, cand)
        assert ok, reason
        for act in plan(q, cand, s).actions:
            res = await browser_executor.execute(page, act)
            assert res.ok, res.message
        await page.wait_for_timeout(900)
        after = await observe(page)
        result = verify(before, after)
        assert result.verdict == Verdict.ADVANCED, result
        assert after.question_id == "q3"
    finally:
        await sess.close()


async def test_apex_aria_only_radios_to_completion(tmp_path):
    """Q4 uses ARIA-only radios (no native inputs): extract, select, complete."""
    s = _settings(tmp_path)
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        # Answer Q2 (opt-1) and Q3 (opt-0) to reach the ARIA question.
        for want in ("opt-1", "opt-0"):
            snap = await observe(page)
            q = extract(snap)
            cand = AnswerCandidate(selected_option_id=want)
            ok, reason = validate_candidate(q, cand)
            assert ok, reason
            for act in plan(q, cand, s).actions:
                res = await browser_executor.execute(page, act)
                assert res.ok, res.message
            await page.wait_for_timeout(900)
        snap = await observe(page)
        assert snap.question_id == "q4", snap.question_id
        assert len(snap.options) == 4, snap.options
        q = extract(snap)
        cand = AnswerCandidate(selected_option_id="opt-2")
        ok, reason = validate_candidate(q, cand)
        assert ok, reason
        before = snap
        for act in plan(q, cand, s).actions:
            res = await browser_executor.execute(page, act)
            assert res.ok, res.message
        await page.wait_for_timeout(900)
        after = await observe(page)
        assert after.is_completion, after.visible_text[:200]
        assert verify(before, after).verdict == Verdict.COMPLETED
    finally:
        await sess.close()


async def test_apex_wrong_answer_shows_feedback(tmp_path):
    s = _settings(tmp_path)
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        before = await observe(page)
        q = extract(before)
        cand = AnswerCandidate(selected_option_id="opt-0")  # wrong per fixture
        for act in plan(q, cand, s).actions:
            res = await browser_executor.execute(page, act)
            assert res.ok, res.message
        await page.wait_for_timeout(600)
        after = await observe(page)
        assert after.question_id == "q2"  # stayed
        assert "incorrect" in after.feedback_text.lower(), repr(after.feedback_text)
        assert verify(before, after).verdict == Verdict.FEEDBACK
    finally:
        await sess.close()


async def test_apex_finish_button_synonym(tmp_path):
    """Final question has no 'Submit' — planner's Submit must resolve the
    'Complete Assessment' synonym and reach the completion screen."""
    from pathlib import Path as _Path

    s = Settings()
    s.target_url = (_Path(__file__).parent / "fixture" / "apex_finish.html").as_uri()
    s.headless = True
    s.connection_mode = "launch"
    s.llm_provider = "mock"
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        before = await observe(page)
        assert before.question_id == "q50", before.question_id
        q = extract(before)
        cand = AnswerCandidate(selected_option_id="opt-1")  # correct per fixture
        ok, reason = validate_candidate(q, cand)
        assert ok, reason
        clicked = ""
        for act in plan(q, cand, s).actions:
            res = await browser_executor.execute(page, act)
            assert res.ok, res.message
            clicked += res.message + ";"
        assert "Complete Assessment" in clicked, clicked
        await page.wait_for_timeout(600)
        after = await observe(page)
        assert after.is_completion, after.visible_text[:200]
        assert verify(before, after).verdict == Verdict.COMPLETED
    finally:
        await sess.close()


async def test_apex_multi_full_run_to_completion(tmp_path):
    """Two 'Choose Two' checkbox questions, mock solver, full controller run."""
    from pathlib import Path as _Path

    from agent.controller import Controller

    s = Settings()
    s.target_url = (_Path(__file__).parent / "fixture" / "apex_multi.html").as_uri()
    s.headless = True
    s.connection_mode = "launch"
    s.llm_provider = "mock"
    s.mock_mode = "auto"
    s.max_questions = 5
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] == 2, summary


async def test_modal_two_step_submit(tmp_path):
    """APEX-style flow: header 'Complete Assessment' opens a confirm modal
    with a second same-labeled button. One CLICK_BUTTON must do both."""
    from pathlib import Path as _Path

    s = Settings()
    s.target_url = (_Path(__file__).parent / "fixture" / "apex_modal.html").as_uri()
    s.headless = True
    s.connection_mode = "launch"
    s.llm_provider = "mock"
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        before = await observe(page)
        q = extract(before)
        assert q is not None and len(q.options) == 2
        cand = AnswerCandidate(selected_option_id="opt-1")  # correct per fixture
        ok, reason = validate_candidate(q, cand)
        assert ok, reason
        msgs = ""
        for act in plan(q, cand, s).actions:
            res = await browser_executor.execute(page, act)
            assert res.ok, res.message
            msgs += res.message + ";"
        assert "confirmed 'Complete Assessment'" in msgs, msgs
        await page.wait_for_timeout(600)
        after = await observe(page)
        assert after.is_completion, after.visible_text[:200]
    finally:
        await sess.close()


async def test_clear_selections_resets_checkboxes(tmp_path):
    from pathlib import Path as _Path

    s = Settings()
    s.target_url = (_Path(__file__).parent / "fixture" / "apex_multi.html").as_uri()
    s.headless = True
    s.connection_mode = "launch"
    s.llm_provider = "mock"
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        for oid in ("opt-0", "opt-2", "opt-3"):
            res = await browser_executor.execute(
                page, Action(type=ActionType.SELECT_OPTION, option_id=oid, timeout_ms=5000))
            assert res.ok, res.message
        assert await page.locator("input[type=checkbox]:checked").count() == 3
        res = await browser_executor.execute(
            page, Action(type=ActionType.CLEAR_SELECTIONS, timeout_ms=5000))
        assert res.ok, res.message
        assert await page.locator("input[type=checkbox]:checked").count() == 0
    finally:
        await sess.close()
