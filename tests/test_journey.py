"""Full course walk: lesson pages -> quiz lobby -> Start pop-up -> questions.

Uses tests/fixture/journey.html (local only). The mock solver knows both
fixture questions, so the happy path runs with no AI key.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.action_planner import plan_navigation
from agent.controller import Controller
from agent.state_machine import AgentState, StateMachine
from browser import executor as browser_executor
from browser.executor import Action, ActionType
from browser.observer import observe
from browser.session import BrowserSession
from config import Settings
from perception.page_classifier import classify
from solver.schemas import ControlInfo, PageSnapshot, PageState
from verification.verifier import Verdict, verify

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixture" / "journey.html"


def _settings(tmp_path, query: str = "", **over):
    s = Settings()
    s.target_url = FIXTURE.as_uri() + query
    s.headless = True
    s.connection_mode = "launch"  # isolate from ambient .env (operator may use cdp)
    s.llm_provider = "mock"
    s.mock_mode = "auto"
    s.auto_advance_lessons = True
    s.action_timeout_ms = 2000
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _snap_with_buttons(*names: str, url: str = "http://course/lesson") -> PageSnapshot:
    return PageSnapshot(url=url, title="Lesson", visible_text="reading material here",
                        controls=[ControlInfo(kind="button", name=n) for n in names])


def test_classify_lesson():
    snap = _snap_with_buttons("Course", "Previous", "Save and Continue ➜")
    assert classify(snap) == PageState.LESSON


def test_classify_lesson_save_progress():
    snap = _snap_with_buttons("Save Progress")
    assert classify(snap) == PageState.LESSON


def test_classify_lobby_prefers_take_over_save():
    # The lobby carries both buttons: Take an Assessment must win.
    snap = _snap_with_buttons("Course", "Previous", "Save Progress", "Take an Assessment")
    assert classify(snap) == PageState.LOBBY


def test_classify_lobby_take_as_link():
    # On the real site Take an Assessment is a link, not a button.
    snap = _snap_with_buttons("Course", "Previous", "Save Progress")
    snap.controls.append(ControlInfo(kind="link", name="Take an Assessment"))
    assert classify(snap) == PageState.LOBBY


def test_classify_question_page_not_lesson():
    from solver.schemas import AnswerOption

    snap = _snap_with_buttons("Exit", "Submit Answer", url="http://course/quiz")
    snap.question_id = "q1"
    snap.question_text = "What is 2 + 2?"
    snap.options = [AnswerOption(option_id="opt-0", text="3"),
                    AnswerOption(option_id="opt-1", text="4")]
    assert classify(snap) == PageState.QUESTION


def test_plan_lesson_picks_save_and_continue():
    settings = Settings()
    res = plan_navigation(_snap_with_buttons("Course", "Previous", "Save and Continue ➜"),
                          PageState.LESSON, settings)
    assert not res.blocked, res.reason
    assert len(res.actions) == 1
    assert res.actions[0].type == ActionType.NAVIGATE
    assert "Save and Continue" in res.actions[0].button_name


def test_plan_lobby_takes_assessment_then_start():
    settings = Settings()
    res = plan_navigation(_snap_with_buttons("Save Progress", "Take an Assessment"),
                          PageState.LOBBY, settings)
    assert not res.blocked, res.reason
    assert [a.type for a in res.actions] == [ActionType.NAVIGATE, ActionType.NAVIGATE]
    assert "Take an Assessment" in res.actions[0].button_name
    assert res.actions[1].button_name == "Start"


def test_plan_lobby_take_as_link():
    settings = Settings()
    snap = _snap_with_buttons("Save Progress")
    snap.controls.append(ControlInfo(kind="link", name="Take an Assessment"))
    res = plan_navigation(snap, PageState.LOBBY, settings)
    assert not res.blocked, res.reason
    assert "Take an Assessment" in res.actions[0].button_name


def test_plan_lobby_modal_already_open_still_takes_first():
    # Pop-up box already showing: the plan stays Take then Start, because the
    # click step dismisses a stale box before Take rebuilds it fresh.
    settings = Settings()
    snap = _snap_with_buttons("Save Progress")
    snap.controls.append(ControlInfo(kind="link", name="Take an Assessment"))
    snap.controls.append(ControlInfo(kind="button", name="Start"))
    snap.controls.append(ControlInfo(kind="button", name="Return to Course"))
    res = plan_navigation(snap, PageState.LOBBY, settings)
    assert not res.blocked, res.reason
    assert [a.type for a in res.actions] == [ActionType.NAVIGATE, ActionType.NAVIGATE]
    assert "Take an Assessment" in res.actions[0].button_name
    assert res.actions[1].button_name == "Start"


async def test_navigate_take_dismisses_stale_modal(tmp_path):
    # A hanging-open box is dismissed and rebuilt: Take click must still work
    # and leave the box open afterwards.
    s = _settings(tmp_path, "#lobby")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#lobby")
        await page.locator("#takeBtn").click()
        assert await page.locator("#startModal").is_visible() is True
        res = await browser_executor.execute(
            page, Action(type=ActionType.NAVIGATE, button_name="Take an Assessment",
                         timeout_ms=2000))
        assert res.ok, res.message
        assert await page.locator("#startModal").is_visible() is True
    finally:
        await sess.close()


def test_plan_never_emits_backward_buttons():
    settings = Settings()
    for snap in (_snap_with_buttons("Previous", "Course"),
                 _snap_with_buttons("Return to Course", "Exit")):
        res = plan_navigation(snap, PageState.LESSON, settings)
        assert res.blocked
        for a in res.actions:
            low = (a.button_name or "").lower()
            assert "previous" not in low and "return" not in low and "exit" not in low


def test_plan_nav_dry_run_blocked():
    settings = Settings()
    settings.dry_run = True
    res = plan_navigation(_snap_with_buttons("Save and Continue"), PageState.LESSON, settings)
    assert res.blocked
    assert "dry-run" in res.reason
    assert res.actions  # proposed, not clicked


def test_plan_nav_wrong_state_blocked():
    settings = Settings()
    res = plan_navigation(_snap_with_buttons("Save and Continue"), PageState.QUESTION, settings)
    assert res.blocked


async def test_navigate_click_exact_only(tmp_path):
    # A missing button must fail WITHOUT touching any other button.
    s = _settings(tmp_path, "#lobby")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#lobby")
        res = await browser_executor.execute(
            page, Action(type=ActionType.NAVIGATE, button_name="No Such Button", timeout_ms=1500))
        assert not res.ok
        # Modal never opened, page never moved.
        assert await page.locator("#startModal").is_visible() is False
        assert page.url.endswith("#lobby")
    finally:
        await sess.close()


def test_verdict_navigated_on_url_change():
    before = PageSnapshot(url="http://course/#lesson1", title="t", visible_text="slides")
    after = PageSnapshot(url="http://course/#lesson2", title="t", visible_text="practice")
    r = verify(before, after)
    assert r.verdict == Verdict.NAVIGATED
    assert r.confirmed


def test_question_change_still_beats_url_change():
    before = PageSnapshot(url="http://course/#a", question_id="q1", question_text="Q1?")
    after = PageSnapshot(url="http://course/#b", question_id="q2", question_text="Q2?")
    assert verify(before, after).verdict == Verdict.ADVANCED


def test_fsm_journey_path_legal():
    sm = StateMachine()
    for nxt in [AgentState.OBSERVE, AgentState.CLASSIFY, AgentState.NAVIGATE,
                AgentState.ACT, AgentState.VERIFY, AgentState.OBSERVE,
                AgentState.CLASSIFY, AgentState.EXTRACT]:
        sm.transition(nxt, "t")
    assert sm.current == AgentState.EXTRACT


async def test_full_journey_to_completion(tmp_path):
    s = _settings(tmp_path)
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] == 2, summary
    # lesson1 -> lesson2 -> lobby -> q1 : three forward walks, then questions.
    assert summary["navigations_done"] == 3, summary
    states = [st["state"] for st in summary["steps"]]
    assert "NAVIGATE" in states
    assert "ACT" in states


async def test_auto_advance_off_stops_on_lesson(tmp_path):
    s = _settings(tmp_path, auto_advance_lessons=False)
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "STOPPED", summary
    assert summary["questions_done"] == 0
    states = [st["state"] for st in summary["steps"]]
    assert "ACT" not in states  # nothing was ever clicked
    assert any("AUTO_ADVANCE_LESSONS" in (st["error"] or "") for st in summary["steps"])


async def test_broken_lobby_stops_bounded(tmp_path):
    s = _settings(tmp_path, "?broken=1#lobby")
    ctl = Controller(s)
    summary = await ctl.run()
    # Take click works but the Start pop-up never opens: must stop, not loop.
    assert summary["final_state"] == "STOPPED", summary


async def test_nav_approval_denied_stops(tmp_path):
    s = _settings(tmp_path, require_approval=True)
    ctl = Controller(s, approval_callback=lambda q, c: True,
                     nav_approval_callback=lambda label: False)
    summary = await ctl.run()
    assert summary["final_state"] == "STOPPED", summary
    assert any(st["state"] == "AWAIT_APPROVAL" for st in summary["steps"])


async def test_nav_approval_allowed_completes(tmp_path):
    s = _settings(tmp_path, require_approval=True)
    ctl = Controller(s, approval_callback=lambda q, c: True,
                     nav_approval_callback=lambda label: True)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary


def _outline_snap(pcts=("100%", "100%", "40%")) -> PageSnapshot:
    names = ["Section 0 - Course Resources", "Section 1 - Fundamentals",
             "Section 2 - Defining Variables and Datatypes"]
    lines = ["Database Programming with PLSQL", "Course Outline"]
    links = []
    for n, p in zip(names, pcts):
        lines += [n, p]
        links.append(ControlInfo(kind="link", name=n, selector_hint=p))
    return PageSnapshot(url="http://course/outline", title="Course",
                        visible_text="\n".join(lines),
                        controls=[ControlInfo(kind="button", name="Return")] + links)


def test_classify_outline():
    assert classify(_outline_snap()) == PageState.OUTLINE


def test_classify_outline_needs_section_links():
    snap = PageSnapshot(url="u", title="t", visible_text="Course Outline\nnothing else here")
    assert classify(snap) != PageState.OUTLINE


def test_plan_outline_picks_first_incomplete():
    from agent.action_planner import plan_navigation

    res = plan_navigation(_outline_snap(), PageState.OUTLINE, Settings())
    assert not res.blocked, res.reason
    assert len(res.actions) == 1
    assert res.actions[0].type == ActionType.NAVIGATE
    assert res.actions[0].button_name == "Section 2 - Defining Variables and Datatypes"


def test_plan_outline_click_name_drops_embedded_percent():
    # Row progress numbers can hide inside the recorded link name
    # ("Section 8 - ...\n\n90%"). The planner keeps the full name for
    # identity (redo detection); the click step strips it for matching.
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(
        url="http://course/outline", title="Course", visible_text="Course Outline",
        controls=[ControlInfo(kind="link", name="Section 8 - Using and Managing Procedures\n\n90%",
                              selector_hint="90%")])
    res = plan_navigation(snap, PageState.OUTLINE, Settings())
    assert not res.blocked, res.reason
    assert "Section 8 - Using and Managing Procedures" in res.actions[0].button_name


def test_plan_outline_all_complete_blocked():
    from agent.action_planner import plan_navigation

    res = plan_navigation(_outline_snap(("100%", "100%", "100%")), PageState.OUTLINE, Settings())
    assert res.blocked
    assert "no unfinished section" in res.reason
    assert res.actions == []


def test_plan_outline_ignores_stray_percent_text():
    # Progress numbers only count when read from a section's own row (stored
    # on the control). Bare numbers elsewhere on the page must not pair up.
    from agent.action_planner import plan_navigation

    snap = _outline_snap(("100%", "100%", "100%"))
    snap.visible_text += "\n40% off sale\n60% humidity"
    res = plan_navigation(snap, PageState.OUTLINE, Settings())
    assert res.blocked
    assert "no unfinished section" in res.reason


def _exam_snap() -> PageSnapshot:
    return PageSnapshot(
        url="http://course/outline", title="Course",
        visible_text="Course Outline",
        controls=[
            ControlInfo(kind="link", name="Section 7 - Exception Handling", selector_hint="100%"),
            ControlInfo(kind="link", name="Database Programming with PL/SQL Semester 1 Final Exam (S5-S9)",
                        selector_hint="0%"),
            ControlInfo(kind="link", name="Section 8 - Using and Managing Procedures", selector_hint=""),
        ])


def test_plan_outline_blank_counts_as_unfinished():
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(
        url="http://course/outline", title="Course", visible_text="Course Outline",
        controls=[ControlInfo(kind="link", name="Section 8 - Using and Managing Procedures",
                              selector_hint="")])
    res = plan_navigation(snap, PageState.OUTLINE, Settings())
    assert not res.blocked, res.reason
    assert res.actions[0].button_name == "Section 8 - Using and Managing Procedures"


def test_plan_outline_opens_final_exam_like_any_section():
    from agent.action_planner import plan_navigation

    res = plan_navigation(_exam_snap(), PageState.OUTLINE, Settings())
    # Section 7 is done; the next unfinished row is the final exam: open it.
    assert not res.blocked, res.reason
    assert len(res.actions) == 1
    assert "Final Exam" in res.actions[0].button_name


def test_plan_outline_skips_done_exam_for_open_section():
    from agent.action_planner import plan_navigation

    snap = _exam_snap()
    # Section 8 now shows progress: it comes after the exam row but is a
    # normal section, so it must still be picked... except the exam row is
    # FIRST unfinished. Reorder: exam done, section open.
    snap.controls[1] = ControlInfo(
        kind="link", name="Database Programming with PL/SQL Semester 1 Final Exam (S5-S9)",
        selector_hint="100%")
    res = plan_navigation(snap, PageState.OUTLINE, Settings())
    assert not res.blocked, res.reason
    assert res.actions[0].button_name == "Section 8 - Using and Managing Procedures"


def test_plan_outline_skips_finished_sections():
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(
        url="http://course/outline", title="Course", visible_text="Course Outline",
        controls=[
            ControlInfo(kind="link", name="Section 7 - Exception Handling", selector_hint="100%"),
            ControlInfo(kind="link", name="Section 8 - Using and Managing Procedures", selector_hint=""),
        ])
    finished = frozenset({"Section 8 - Using and Managing Procedures"})
    res = plan_navigation(snap, PageState.OUTLINE, Settings(), finished=finished)
    assert res.blocked
    assert "already finished" in res.reason
    assert "Section 8" in res.reason


def test_plan_outline_skips_finished_exam_picks_section():
    # A finished final exam is skipped like anything finished; the open
    # section after it is still picked.
    from agent.action_planner import plan_navigation

    snap = _exam_snap()
    finished = frozenset({"Database Programming with PL/SQL Semester 1 Final Exam (S5-S9)"})
    res = plan_navigation(snap, PageState.OUTLINE, Settings(), finished=finished)
    assert not res.blocked, res.reason
    assert res.actions[0].button_name == "Section 8 - Using and Managing Procedures"


def test_plan_outline_percent_inside_link_name_counts():
    # The number can hide at the end of the link name itself (live pages do
    # this): such a row still counts as finished, not as "no number shown".
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(
        url="http://course/outline", title="Course", visible_text="Course Outline",
        controls=[
            ControlInfo(kind="link", name="Section 9 - Advanced Topics 100%", selector_hint=""),
            ControlInfo(kind="link", name="Section 8 - Using and Managing Procedures", selector_hint="40%"),
        ])
    res = plan_navigation(snap, PageState.OUTLINE, Settings())
    assert not res.blocked, res.reason
    assert res.actions[0].button_name == "Section 8 - Using and Managing Procedures"


def test_plan_outline_name_only_percent_means_finished():
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(
        url="http://course/outline", title="Course", visible_text="Course Outline",
        controls=[ControlInfo(kind="link", name="Section 9 - Advanced Topics 100%", selector_hint="")])
    res = plan_navigation(snap, PageState.OUTLINE, Settings())
    assert res.blocked
    assert "no unfinished section found" in res.reason


async def test_navigate_clicks_section_link(tmp_path):
    s = _settings(tmp_path, "#outline")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#outline")
        res = await browser_executor.execute(
            page, Action(type=ActionType.NAVIGATE,
                         button_name="Section 2 - Defining Variables and Datatypes",
                         timeout_ms=2000))
        assert res.ok, res.message
        assert page.url.endswith("#lesson1")
    finally:
        await sess.close()


async def test_observe_sees_name_embedded_percent_and_planner_skips_it(tmp_path):
    # End to end on the live bug shape: the "100%" lives only inside the
    # link's accessible name, yet the planner must treat the row as finished.
    from agent.action_planner import plan_navigation

    s = _settings(tmp_path, "#outline")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#outline")
        snap = await observe(page)
        nine = [c for c in snap.controls
                if c.kind == "link" and "Section 9" in (c.name or "")]
        assert nine, "Section 9 link missing from snapshot"
        assert "100%" in nine[0].name, nine[0].name
        res = plan_navigation(snap, PageState.OUTLINE, Settings())
        assert not res.blocked, res.reason
        assert "Section 2" in res.actions[0].button_name
        assert "Section 9" not in res.actions[0].button_name
    finally:
        await sess.close()


async def test_navigate_strips_embedded_percent(tmp_path):
    # Live outline links can carry their row's "90%" inside the recorded
    # name; the click step must still find the link.
    s = _settings(tmp_path, "#outline")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#outline")
        res = await browser_executor.execute(
            page, Action(type=ActionType.NAVIGATE,
                         button_name="Section 2 - Defining Variables and Datatypes\n\n40%",
                         timeout_ms=2000))
        assert res.ok, res.message
        assert page.url.endswith("#lesson1")
    finally:
        await sess.close()


async def test_full_journey_from_outline(tmp_path):
    s = _settings(tmp_path, "#outline")
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] == 2, summary
    assert summary["quizzes_done"] == 1, summary
    # outline -> lesson1 -> lesson2 -> lobby -> q1 : four forward walks.
    assert summary["navigations_done"] == 4, summary


async def test_redo_guard_stops_second_pass(tmp_path):
    # ?staticpct=1 freezes progress numbers: after one full section+quiz,
    # the outline still offers the same section -> must stop, never redo.
    s = _settings(tmp_path, "?staticpct=1#outline")
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "STOPPED", summary
    assert summary["questions_done"] == 2, summary
    assert summary["quizzes_done"] == 1, summary
    assert any("already finished" in (st["error"] or "") for st in summary["steps"]), summary


async def test_outline_all_complete_finishes(tmp_path):
    # Outline shows everything finished: nothing to do -> course complete.
    s = _settings(tmp_path, "?alldone=1#outline")
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] == 0
    assert "ACT" not in [st["state"] for st in summary["steps"]]


def _shared_db_settings(tmp_path, query="", **over):
    # Two runs sharing one history file, like two real `python main.py` runs.
    s = _settings(tmp_path, query, **over)
    s.database_path = str(tmp_path / "shared.sqlite")
    return s


async def test_finished_section_skipped_across_runs(tmp_path):
    # Run 1 finishes the section+quiz (progress numbers frozen). Run 2, a
    # fresh process with the same history file, must NOT walk in again:
    # no clicks at all, stopped on the recorded finish.
    s1 = _shared_db_settings(tmp_path, "?staticpct=1#outline")
    summary1 = await Controller(s1).run()
    assert summary1["final_state"] == "STOPPED", summary1
    assert summary1["questions_done"] == 2, summary1

    s2 = _shared_db_settings(tmp_path, "?staticpct=1#outline")
    summary2 = await Controller(s2).run()
    assert summary2["final_state"] == "STOPPED", summary2
    assert summary2["questions_done"] == 0, summary2
    assert "ACT" not in [st["state"] for st in summary2["steps"]], summary2["steps"]
    assert any("already finished" in (st["error"] or "") for st in summary2["steps"])


async def test_redo_flag_allows_reentry(tmp_path, monkeypatch):
    # REDO_FINISHED_SECTIONS=true: the recorded finish is ignored and the
    # section is walked into again (one click proves entry, budget stops it).
    s1 = _shared_db_settings(tmp_path, "?staticpct=1#outline")
    summary1 = await Controller(s1).run()
    assert summary1["final_state"] == "STOPPED", summary1

    monkeypatch.setenv("REDO_FINISHED_SECTIONS", "true")
    s2 = _shared_db_settings(tmp_path, "?staticpct=1#outline", max_actions=1)
    summary2 = await Controller(s2).run()
    assert any(st["state"] == "ACT" and "Section 2" in (st["action"] or "")
               for st in summary2["steps"]), summary2["steps"]


LOOP_FIXTURE = Path(__file__).parent / "fixture" / "journey_loop.html"


def _loop_settings(tmp_path, query="", **over):
    s = Settings()
    # Start ON the lobby hash: the quiz returns to this exact address after
    # finishing, and the revisit is detected by address equality.
    s.target_url = LOOP_FIXTURE.as_uri() + query + "#lobby"
    s.headless = True
    s.connection_mode = "launch"
    s.llm_provider = "mock"
    s.mock_mode = "auto"
    s.auto_advance_lessons = True
    s.action_timeout_ms = 2000
    s.screenshot_dir = str(tmp_path / "shots")
    s.database_path = str(tmp_path / "runs.sqlite")
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_plan_lobby_revisit_exits_via_save_progress():
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(url="http://course/quiz", title="Quiz",
                        visible_text="Quiz: PL/SQL - Section 7",
                        controls=[ControlInfo(kind="button", name="Save Progress"),
                                  ControlInfo(kind="link", name="Take an Assessment")])
    fresh = plan_navigation(snap, PageState.LOBBY, Settings())
    assert not fresh.blocked, fresh.reason
    assert "Take an Assessment" in fresh.actions[0].button_name
    again = plan_navigation(snap, PageState.LOBBY, Settings(), revisit=True)
    assert not again.blocked, again.reason
    assert len(again.actions) == 1
    assert again.actions[0].type == ActionType.NAVIGATE
    assert again.actions[0].button_name == "Save Progress"


def test_plan_lobby_revisit_without_save_blocked():
    from agent.action_planner import plan_navigation

    snap = PageSnapshot(url="http://course/quiz", title="Quiz",
                        visible_text="Quiz: PL/SQL - Section 7",
                        controls=[ControlInfo(kind="link", name="Take an Assessment")])
    res = plan_navigation(snap, PageState.LOBBY, Settings(), revisit=True)
    assert res.blocked
    assert "Save Progress" in res.reason


async def test_full_loop_lobby_exit_to_outline(tmp_path):
    s = _loop_settings(tmp_path)
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] == 1, summary
    takes = [st for st in summary["steps"]
             if st["state"] == "ACT" and (st["action"] or "").startswith("navigate:Take an Assessment")]
    assert len(takes) == 1, summary["steps"]
    saves = [st for st in summary["steps"]
             if st["state"] == "ACT" and "Save Progress" in (st["action"] or "")]
    assert len(saves) == 1, summary["steps"]
    submits = [st for st in summary["steps"]
               if st["state"] == "ACT" and (st["action"] or "").startswith("click_button:Submit")]
    assert len(submits) == 1, summary["steps"]


async def test_slow_initial_lobby_recovers(tmp_path):
    # Lobby buttons render 2.5s after first paint: early looks find nothing,
    # the safe-retry wait covers the gap, and the run still completes.
    s = _loop_settings(tmp_path, query="?slow=1")
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    assert summary["questions_done"] == 1, summary
    assert any(st["state"] == "CLASSIFY" for st in summary["steps"]), summary["steps"]
