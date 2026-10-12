"""My Classes multi-course walk: Home -> hub -> each Take Class -> outlines.

Uses tests/fixture/journey_multicourse.html (local only).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.action_planner import (
    normalize_course_title,
    outline_course_title,
    plan_navigation,
)
from agent.controller import Controller
from browser import executor as browser_executor
from browser.executor import Action, ActionType
from browser.observer import observe
from browser.session import BrowserSession
from config import Settings
from perception.page_classifier import classify
from solver.schemas import ControlInfo, PageSnapshot, PageState

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixture" / "journey_multicourse.html"


def _settings(tmp_path, query: str = "", **over):
    s = Settings()
    s.target_url = FIXTURE.as_uri() + query
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


def _home_snap() -> PageSnapshot:
    return PageSnapshot(
        url="http://academy/home", title="Oracle Academy",
        visible_text="Discover NEW Education Bytes!\nMy Student Benefits\nMy Classes\nStudent Tools\nFree Resources Library\nView course materials assigned by a faculty member",
        controls=[
            ControlInfo(kind="link", name="View course materials assigned by a faculty member"),
            ControlInfo(kind="link", name="Explore a library of tools to empower your learning"),
        ])


def _hub_snap() -> PageSnapshot:
    return PageSnapshot(
        url="http://academy/classes", title="My Classes",
        visible_text="Classes\nHome \\ My Classes\nDatabase Programming with SQL - English\nby Vineeta Soni on Database\nSection-I3\nDatabase Programming with PLSQL - English\nby Vineeta Soni on Database\nSection-I3",
        controls=[
            ControlInfo(kind="button", name="Take Class", selector_hint="Database Programming with SQL - English"),
            ControlInfo(kind="button", name="Take Class", selector_hint="Database Programming with PLSQL - English"),
        ])


def test_classify_home():
    assert classify(_home_snap()) == PageState.HOME


def test_classify_classes_hub():
    assert classify(_hub_snap()) == PageState.CLASSES


def test_classify_classes_beats_outline_text():
    # Hub breadcrumb mentions My Classes but has Take Class buttons: hub wins.
    snap = _hub_snap()
    snap.visible_text += "\nCourse Outline"
    assert classify(snap) == PageState.CLASSES


def test_plan_home_picks_my_classes_entry():
    res = plan_navigation(_home_snap(), PageState.HOME, Settings())
    assert not res.blocked, res.reason
    assert len(res.actions) == 1
    assert "course materials" in res.actions[0].button_name.lower() or "my classes" in res.actions[0].button_name.lower()


def test_plan_classes_picks_first_take_class_with_occurrence_zero():
    res = plan_navigation(_hub_snap(), PageState.CLASSES, Settings())
    assert not res.blocked, res.reason
    assert res.actions[0].button_name == "Take Class"
    assert res.actions[0].occurrence == 0
    assert "SQL" in (res.actions[0].label + res.course_title)


def test_plan_classes_skips_finished_course_by_title():
    from agent.action_planner import normalize_course_title as norm
    done = frozenset({norm("Database Programming with SQL - English")})
    res = plan_navigation(_hub_snap(), PageState.CLASSES, Settings(), finished_courses=done)
    assert not res.blocked, res.reason
    assert res.actions[0].occurrence == 1
    assert "PLSQL" in (res.actions[0].label + res.course_title)


def test_plan_classes_all_done_blocked():
    from agent.action_planner import normalize_course_title as norm
    done = frozenset({norm("Database Programming with SQL - English"),
                      norm("Database Programming with PLSQL - English")})
    res = plan_navigation(_hub_snap(), PageState.CLASSES, Settings(), finished_courses=done)
    assert res.blocked
    assert "no unfinished class" in res.reason


def test_normalize_course_title_stable():
    assert normalize_course_title("  Database Programming with SQL - English  ") == "database programming with sql - english"
    assert normalize_course_title("Section 8 - Foo 90%") == "section 8 - foo"


def test_outline_course_title_first_line():
    snap = PageSnapshot(url="u", title="t",
                        visible_text="Database Programming with SQL - English\nHome \\ My Classes \\ Taking a Class\nSections in Course\n24\nCourse Outline")
    assert outline_course_title(snap) == "Database Programming with SQL - English"


def test_finished_courses_persist(tmp_path):
    from storage.run_store import RunStore
    db = str(tmp_path / "c.sqlite")
    st = RunStore(db)
    st.record_finished_course("database programming with sql - english")
    assert "database programming with sql - english" in st.finished_courses()
    st.close()
    st2 = RunStore(db)
    assert "database programming with sql - english" in st2.finished_courses()
    st2.close()


async def test_observe_hub_sees_two_take_class_buttons(tmp_path):
    s = _settings(tmp_path, "#classes")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#classes")
        snap = await observe(page)
        assert classify(snap) == PageState.CLASSES
        takes = [c for c in snap.controls if "take class" in (c.name or "").lower()]
        assert len(takes) == 2, [c.name for c in snap.controls]
        # At least one carries its card title for skipping.
        assert any("SQL" in (c.selector_hint or "") for c in takes), [(c.name, c.selector_hint) for c in takes]
    finally:
        await sess.close()


async def test_navigate_clicks_second_take_class(tmp_path):
    s = _settings(tmp_path, "#classes")
    sess = BrowserSession(s)
    try:
        page = await sess.start()
        await page.goto(FIXTURE.as_uri() + "#classes")
        res = await browser_executor.execute(
            page, Action(type=ActionType.NAVIGATE, button_name="Take Class",
                         timeout_ms=2000, occurrence=1))
        assert res.ok, res.message
        assert page.url.endswith("#outline-plsql"), page.url
    finally:
        await sess.close()


async def test_full_multicourse_home_to_all_done(tmp_path):
    s = _settings(tmp_path, "#home")
    ctl = Controller(s)
    summary = await ctl.run()
    assert summary["final_state"] == "COMPLETED", summary
    # SQL course was already 100% (skipped after one outline visit),
    # PLSQL course needed its open section + 1 quiz question.
    assert summary["questions_done"] == 1, summary
    assert summary.get("courses_done", 0) == 2, summary
    states = [st["state"] for st in summary["steps"]]
    assert "NAVIGATE" in states and "ACT" in states
    # Both Take Class clicks happened (occurrences 0 and 1).
    takes = [st for st in summary["steps"] if st["state"] == "ACT" and "Take Class" in (st["action"] or "")]
    assert len(takes) == 2, summary["steps"]


async def test_second_run_skips_finished_courses_without_clicks(tmp_path):
    db = str(tmp_path / "shared.sqlite")
    s1 = _settings(tmp_path, "#home")
    s1.database_path = db
    summary1 = await Controller(s1).run()
    assert summary1["final_state"] == "COMPLETED", summary1

    s2 = _settings(tmp_path, "#home")
    s2.database_path = db
    summary2 = await Controller(s2).run()
    # Hub shows no unfinished class: no Take Class clicks, clean complete.
    # (Home -> hub entry click still happens to reach the hub.)
    assert summary2["final_state"] == "COMPLETED", summary2
    takes = [st for st in summary2["steps"]
             if st["state"] == "ACT" and "Take Class" in (st["action"] or "")]
    assert takes == [], summary2["steps"]
