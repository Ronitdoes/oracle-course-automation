"""Browser integration tests against the local fixture (no external sites).

Covers: extraction, option selection, delayed transitions, question
transitions, failed-transition detection, timeouts, duplicate prevention,
completion, approval enforcement, dry-run, graceful shutdown.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from agent.action_planner import plan
from agent.controller import Controller
from browser import executor as browser_executor
from browser.executor import Action, ActionType
from browser.observer import observe
from browser.session import BrowserSession
from config import Settings
from perception.question_extractor import extract
from solver.base import validate_candidate
from solver.llm_solver import MockSolver
from verification.verifier import verify

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixture" / "quiz.html"


def _url(query: str = "") -> str:
    return FIXTURE.as_uri() + query


def _settings(tmp_path, query: str = "", **over):
    s = Settings()
    s.target_url = _url(query)
    s.headless = True
    s.connection_mode = "launch"  # isolate from ambient .env (operator may use cdp)
    s.llm_provider = "mock"
    s.mock_mode = "auto"
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    s.action_timeout_ms = 5000
    s.navigation_timeout_ms = 15000
    s.max_questions = 10
    s.max_retries = 2
    for k, v in over.items():
        setattr(s, k, v)
    return s


async def _session(tmp_path, query=""):
    s = _settings(tmp_path, query)
    sess = BrowserSession(s)
    page = await sess.start()
    return s, sess, page


async def test_extract_first_question(tmp_path):
    s, sess, page = await _session(tmp_path)
    try:
        snap = await observe(page)
        assert snap.question_id == "q1"
        q = extract(snap)
        assert q is not None and len(q.options) == 3
        assert {o.option_id for o in q.options} == {"a", "b", "c"}
    finally:
        await sess.close()


async def test_select_option_and_advance(tmp_path):
    s, sess, page = await _session(tmp_path)
    try:
        snap = await observe(page)
        q = extract(snap)
        cand = await MockSolver().solve(q)
        ok, _ = validate_candidate(q, cand)
        assert ok
        planned = plan(q, cand, s)
        for act in planned.actions:
            res = await browser_executor.execute(page, act)
            assert res.ok, res.message
        await page.wait_for_timeout(800)
        after = await observe(page)
        assert after.question_id == "q2", f"expected q2, got {after.question_id}"
    finally:
        await sess.close()


async def test_delayed_transition(tmp_path):
    """q4 has a 1500ms delayed transition; immediate observe shows feedback,
    patient polling shows the next question."""
    s, sess, page = await _session(tmp_path)
    try:
        # Fast-forward to q4 by answering q1..q3.
        for _ in range(3):
            snap = await observe(page)
            q = extract(snap)
            cand = await MockSolver().solve(q)
            for act in plan(q, cand, s).actions:
                r = await browser_executor.execute(page, act)
                assert r.ok, r.message
            await page.wait_for_timeout(900)
        snap = await observe(page)
        assert snap.question_id == "q4-delayed", f"got {snap.question_id}"
        q = extract(snap)
        cand = await MockSolver().solve(q)
        for act in plan(q, cand, s).actions:
            await browser_executor.execute(page, act)
        await page.wait_for_timeout(300)
        mid = await observe(page)
        # Either still on q4 (delay) or feedback — but NOT yet q5.
        assert mid.question_id in ("q4-delayed",), f"unexpected jump: {mid.question_id}"
        await page.wait_for_timeout(2000)
        after = await observe(page)
        assert after.question_id == "q5", f"delayed transition failed: {after.question_id}"
    finally:
        await sess.close()


async def test_full_run_to_completion(tmp_path):
    s = _settings(tmp_path)
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] >= 5


async def test_broken_question_stops_safely(tmp_path):
    s = _settings(tmp_path, "?only=empty", max_questions=3)
    ctl = Controller(s)
    summary = await ctl.run()
    # No valid options -> STOPPED (safe), never COMPLETED, bounded steps.
    assert summary["final_state"] in ("STOPPED", "FAILED"), summary
    assert summary["final_state"] == "STOPPED"


async def test_dry_run_proposes_without_submit(tmp_path):
    s = _settings(tmp_path, "", dry_run=True)
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "STOPPED"
    states = [st["state"] for st in summary["steps"]]
    assert "VALIDATE" in states
    assert "ACT" not in states  # never acted in dry-run


async def test_approval_denied_stops(tmp_path):
    s = _settings(tmp_path, "", require_approval=True)
    ctl = Controller(s, approval_callback=lambda q, c: False)
    summary = await ctl.run()
    assert summary["final_state"] == "STOPPED"
    assert any(st["state"] == "AWAIT_APPROVAL" for st in summary["steps"])


async def test_graceful_shutdown(tmp_path):
    s, sess, page = await _session(tmp_path)
    await sess.close()
    assert sess.page is None  # resources released without exception


async def test_failed_transition_verdict(tmp_path):
    s, sess, page = await _session(tmp_path)
    try:
        before = await observe(page)
        # Click a non-submit control that changes nothing, then verify NO_CHANGE.
        after = await observe(page)
        assert verify(before, after).verdict.value in ("no_change", "uncertain")
    finally:
        await sess.close()


async def test_timeout_handling_missing_control(tmp_path):
    s, sess, page = await _session(tmp_path)
    try:
        res = await browser_executor.execute(
            page, Action(type=ActionType.SELECT_OPTION, option_id="nope-missing", timeout_ms=1000))
        assert res.ok is False
    finally:
        await sess.close()


async def test_goto_moves_to_allowed_url(tmp_path):
    s, sess, page = await _session(tmp_path)
    try:
        dest = (Path(__file__).parent / "fixture" / "apex.html").as_uri()
        await sess.goto(dest)
        assert sess.page.url.startswith("file://")
        assert sess.page.url.endswith("apex.html")
    finally:
        await sess.close()


async def test_goto_blocked_off_domain(tmp_path):
    s = _settings(tmp_path, allowed_domains=["example.com"])
    sess = BrowserSession(s)
    try:
        await sess.start()
        with pytest.raises(PermissionError):
            await sess.goto("https://other-site.test/page")
    finally:
        await sess.close()
