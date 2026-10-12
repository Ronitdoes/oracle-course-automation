"""Runs the quiz step by step: look at the page, read the question, answer it, click, and check the result."""
from __future__ import annotations

import asyncio
import logging
import time

from agent.action_planner import plan, plan_navigation, section_key
from agent.recovery import RecoveryManager
from agent.state_machine import AgentState, StateMachine
from browser import executor as browser_executor
from browser.executor import ActionType
from browser.observer import observe
from browser.session import BrowserSession
from config import Settings
from perception import page_classifier, question_extractor, visual_perception
from solver.base import validate_candidate
from solver.llm_solver import build_solver
from solver.schemas import AnswerCandidate, PageSnapshot, PageState, Question
from storage.run_store import RunStore, course_key_for_url
from verification.verifier import Verdict, verify

log = logging.getLogger(__name__)


class Controller:
    def __init__(self, settings: Settings, approval_callback=None, nav_approval_callback=None):
        self.settings = settings
        self.sm = StateMachine()
        self.recovery = RecoveryManager(max_retries=settings.max_retries)
        self.store = RunStore(settings.database_path)
        self.solver = build_solver(settings)
        self.session = BrowserSession(settings)
        self.approval_callback = approval_callback or (lambda q, c: True)
        self.nav_approval_callback = nav_approval_callback
        self.run_id = ""
        self.questions_done = 0
        self.navigations_done = 0
        self.actions_taken = 0
        self.model_calls = 0
        self.model_latency = 0.0
        self.submitted_ids: set[str] = set()
        self.visited_urls: set[str] = set()
        self.pending_nav: str | None = None
        self.outline_url: str = ""
        self.classes_url: str = ""
        self.home_url: str = ""
        self.quizzes_done: int = 0
        self.courses_done: int = 0
        self.current_section: str | None = None
        self.current_course_title: str | None = None
        self._return_to: str = ""
        self._nav_from = None
        self.errors: list[str] = []
        self._stop_requested = False
        self._t0 = time.monotonic()

    def request_stop(self) -> None:
        self._stop_requested = True

    def _over_limits(self) -> str:
        if self._stop_requested:
            return "you asked to stop, so stopping now"
        if self.settings.max_questions > 0 and self.questions_done >= self.settings.max_questions:
            return f"question limit ({self.settings.max_questions}) reached, stopping as planned"
        if self.settings.max_actions > 0 and self.actions_taken >= self.settings.max_actions:
            return f"click limit ({self.settings.max_actions}) reached, stopping as planned"
        if getattr(self.settings, "run_max_duration_sec", 0) > 0 and \
                time.monotonic() - self._t0 > self.settings.run_max_duration_sec:
            return f"time limit ({self.settings.run_max_duration_sec}s) reached, stopping as planned"
        return ""

    def _qlog(self, text: str) -> str:
        if self.settings.redact_question_text:
            return "[redacted]"
        return text

    def _plan_forward_walk(self, snap_before, cls, s, lobby_exit):
        """Plan home/hub/outline/lesson/lobby clicks, skipping finished work.

        Finished sections come from earlier runs (saved in the database, read
        fresh each visit). REDO_FINISHED_SECTIONS=true turns the skipping off.
        Finished courses (My Classes hub titles) are always skipped, never
        re-entered, so the hub walks each course once.
        """
        from agent.action_planner import normalize_course_title
        finished: set[str] = set()
        finished_courses: set[str] = set()
        if cls == PageState.OUTLINE and not s.redo_finished_sections:
            course = course_key_for_url(snap_before.url or "")
            if course:
                try:
                    finished = set(self.store.finished_sections(course))
                except Exception as e:  # noqa: BLE001
                    log.debug("could not read finished sections: %s", e)
        if cls == PageState.CLASSES:
            try:
                done = self.store.finished_courses()
                finished_courses = {normalize_course_title(k) for k in done.keys()}
                # Also skip the course currently in progress this run when its
                # outline already showed all-done but the DB write races hub.
                # (DB is the source of truth; this set is read fresh each visit.)
            except Exception as e:  # noqa: BLE001
                log.debug("could not read finished courses: %s", e)
        return plan_navigation(snap_before, cls, s, revisit=lobby_exit,
                               finished=frozenset(finished),
                               finished_courses=frozenset(finished_courses))

    async def run(self) -> dict:
        s = self.settings
        self.run_id = self.store.create_run(s.target_url)
        self._t0 = time.monotonic()
        snap_before: PageSnapshot | None = None
        question: Question | None = None
        candidate: AnswerCandidate | None = None
        pending_actions: list = []
        verdict_note = ""
        try:
            # Start up, then look at the page.
            page = await self.session.start()
            self.sm.transition(AgentState.OBSERVE, "browser is ready, starting to look at the page")

            while self.sm.current not in (AgentState.COMPLETED, AgentState.STOPPED, AgentState.FAILED):
                limit_hit = self._over_limits()
                if limit_hit and self.sm.current not in (AgentState.COMPLETED,):
                    await self._log_step(self.sm.current.value, "", "", "", "", verdict_note, 0, limit_hit)
                    self.sm.transition(AgentState.STOPPED, limit_hit)
                    break
                st = self.sm.current

                if st == AgentState.OBSERVE:
                    snap_before = await observe(page)
                    await self._log_step("OBSERVE", snap_before.question_id or "", self._qlog(snap_before.question_text),
                                         "", "looked at the page", "", 0, "")
                    self.sm.transition(AgentState.CLASSIFY, f"looking at {page.url}")

                elif st == AgentState.CLASSIFY:
                    assert snap_before is not None
                    cls = page_classifier.classify(snap_before)
                    if cls == PageState.COMPLETION:
                        self.sm.transition(AgentState.COMPLETED, "finished page detected - the quiz looks complete")
                    elif cls == PageState.QUESTION:
                        self.sm.transition(AgentState.EXTRACT, "a question is showing, will read it")
                    elif cls in (PageState.LESSON, PageState.LOBBY, PageState.OUTLINE,
                                 PageState.HOME, PageState.CLASSES):
                        if cls == PageState.LESSON:
                            kind = "theory page"
                        elif cls == PageState.LOBBY:
                            kind = "quiz start page"
                        elif cls == PageState.HOME:
                            kind = "home page"
                            if not self.home_url:
                                self.home_url = snap_before.url or ""
                        elif cls == PageState.CLASSES:
                            kind = "My Classes hub"
                            if not self.classes_url:
                                self.classes_url = snap_before.url or ""
                        else:
                            kind = "course outline"
                            self.outline_url = snap_before.url or ""
                            # Remember which course this outline belongs to for
                            # course-level completion (hub needs its title).
                            # Hub navigation already set it (card title); only
                            # fill from the outline header in single-course mode.
                            if not self.current_course_title:
                                try:
                                    from agent.action_planner import outline_course_title
                                    t = outline_course_title(snap_before)
                                    if t:
                                        self.current_course_title = t
                                except Exception:
                                    pass
                        if not s.auto_advance_lessons:
                            await self._log_step("CLASSIFY", "", "", "", "", f"{kind} (walking forward is off)", 0,
                                                 f"{kind} needs AUTO_ADVANCE_LESSONS=true in the settings; stopping")
                            self.sm.transition(AgentState.STOPPED, f"{kind} needs AUTO_ADVANCE_LESSONS=true; stopping")
                        else:
                            self.sm.transition(AgentState.NAVIGATE, f"{kind}, planning a forward click")
                    elif cls == PageState.LOADING:
                        await asyncio.sleep(0.5)
                        # Loading pages need a fresh look; going through a safe retry step.
                        self.sm.transition(AgentState.RECOVER, "page is still loading, will look again")
                    elif cls == PageState.FEEDBACK:
                        # A result message between questions; wait briefly then look again.
                        try:
                            await page.wait_for_timeout(800)
                        except Exception:
                            pass
                        snap_before = await observe(page)
                        self.sm.transition(AgentState.RECOVER, "result message is temporary, will look again for the next question")
                    else:  # AMBIGUOUS
                        # Page text was not enough to tell what is showing -> save a picture, then try again.
                        vis = await visual_perception.capture(page, s, name=f"ambiguous-{self.questions_done}.png")
                        note = f"page layout unclear; saved picture at {vis.screenshot_path if vis.ok else 'could not save picture'}. Next: will look again."
                        await self._log_step("CLASSIFY", "", "", "", "", note, 0, "")
                        self.sm.transition(AgentState.RECOVER, note)

                elif st == AgentState.EXTRACT:
                    assert snap_before is not None
                    question = question_extractor.extract(snap_before)
                    if question is None:
                        dec = self.recovery.should_retry("extract", "could not read a question from the page")
                        await self._log_step("EXTRACT", "", "", "", "", "no question found", 0, "could not read a question from the page")
                        self.sm.transition(AgentState.RECOVER if dec.retry else AgentState.STOPPED,
                                           "could not read the question")
                    elif question.question_type.value == "unsupported":
                        await self._log_step("EXTRACT", question.question_id or "", self._qlog(question.text),
                                             "", "", "question type not supported", 0, "question type not supported; please answer by hand")
                        self.sm.transition(AgentState.STOPPED, "question type not supported; please answer by hand")
                    elif question.multi_answer:
                        need = f" (needs {question.required_count})" if question.required_count else ""
                        await self._log_step("EXTRACT", question.question_id or "", self._qlog(question.text),
                                             "", "", f"needs several choices{need}, {len(question.options)} choices shown", 0, "")
                        self.sm.transition(AgentState.SOLVE, f"question {question.question_id} needs several choices")
                    else:
                        await self._log_step("EXTRACT", question.question_id or "", self._qlog(question.text),
                                             "", "", f"{len(question.options)} choices shown", 0, "")
                        self.sm.transition(AgentState.SOLVE, f"question {question.question_id} ready to answer")

                elif st == AgentState.SOLVE:
                    assert question is not None
                    t0 = time.monotonic()
                    try:
                        candidate = await self.solver.solve(question)
                    except Exception as e:  # noqa: BLE001
                        self.errors.append(str(e))
                        await self._log_step("SOLVE", question.question_id or "", "", "", "", "", 0, str(e))
                        self.sm.transition(AgentState.RECOVER, f"answer helper failed: {e}")
                        continue
                    dt = time.monotonic() - t0
                    self.model_calls += 1
                    self.model_latency += dt
                    await self._log_step("SOLVE", question.question_id or "", "",
                                         _cand_str(candidate), "", f"answered in {dt:.2f}s", 0, "")
                    self.sm.transition(AgentState.VALIDATE, "proposed answer received, will check it")

                elif st == AgentState.VALIDATE:
                    assert question is not None and candidate is not None
                    ok, reason = validate_candidate(question, candidate)
                    if not ok:
                        await self._log_step("VALIDATE", question.question_id or "", "",
                                             _cand_str(candidate), "", reason, 0, reason)
                        self.sm.transition(AgentState.RECOVER, f"answer not usable: {reason}")
                        continue
                    planned = plan(question, candidate, s, self.submitted_ids)
                    if planned.blocked:
                        await self._log_step("VALIDATE", question.question_id or "", "",
                                             _cand_str(candidate), "", planned.reason, 0, planned.reason)
                        # Dry-run is a clean stop, not a failure.
                        if "dry-run" in planned.reason:
                            self.sm.transition(AgentState.STOPPED, planned.reason)
                        else:
                            self.sm.transition(AgentState.RECOVER, planned.reason)
                        continue
                    pending_actions = planned.actions
                    self.pending_nav = None
                    if planned.needs_approval or s.require_approval:
                        self.sm.transition(AgentState.AWAIT_APPROVAL, "needs your approval before clicking")
                    else:
                        self.sm.transition(AgentState.ACT, "answer looks good and is allowed, will click now")

                elif st == AgentState.AWAIT_APPROVAL:
                    if self.pending_nav is not None:
                        label = self.pending_nav
                        if self.nav_approval_callback is None:
                            await self._log_step("AWAIT_APPROVAL", "", "", "", label, "forward clicks need approval", 0,
                                                 "forward clicks need approval but no approval step was set up; stopping")
                            self.pending_nav = None
                            self.sm.transition(AgentState.STOPPED, "forward clicks need approval; stopping")
                        else:
                            try:
                                approved = bool(self.nav_approval_callback(label))
                            except Exception as e:  # noqa: BLE001
                                approved = False
                                self.errors.append(f"approval error: {e}")
                            if not approved:
                                await self._log_step("AWAIT_APPROVAL", "", "", "", label, "you did not approve it", 0,
                                                     "you did not approve the forward clicks; stopping as asked")
                                self.pending_nav = None
                                pending_actions = []
                                self.sm.transition(AgentState.STOPPED, "you did not approve, so stopping")
                            else:
                                self.sm.transition(AgentState.ACT, "you approved, will click now")
                        continue
                    assert question is not None and candidate is not None
                    try:
                        approved = bool(self.approval_callback(question, candidate))
                    except Exception as e:  # noqa: BLE001
                        approved = False
                        self.errors.append(f"approval error: {e}")
                    if not approved:
                        await self._log_step("AWAIT_APPROVAL", question.question_id or "", "",
                                             _cand_str(candidate), "", "you did not approve it", 0, "you did not approve; stopping as asked")
                        self.sm.transition(AgentState.STOPPED, "you did not approve, so stopping")
                    else:
                        self.sm.transition(AgentState.ACT, "you approved, will click now")

                elif st == AgentState.NAVIGATE:
                    assert snap_before is not None
                    cls = page_classifier.classify(snap_before)
                    self._nav_from = cls
                    url_key = snap_before.url or ""
                    # Back on a lobby left before: its quiz is done, so plan
                    # the way out (Save Progress) instead of starting again.
                    lobby_exit = cls == PageState.LOBBY and url_key in self.visited_urls
                    # Outline, hub, and home are revisited by design (back after
                    # each quiz/section/course), so only other pages use the loop guard.
                    if cls not in (PageState.OUTLINE, PageState.CLASSES, PageState.HOME) and url_key in self.visited_urls and not lobby_exit:
                        await self._log_step("NAVIGATE", "", "", "", "", "already been on this page", 0,
                                             "already been on this page; stopping so it does not loop")
                        self.sm.transition(AgentState.STOPPED, "already been on this page; stopping so it does not loop")
                        continue
                    nav = self._plan_forward_walk(snap_before, cls, s, lobby_exit)
                    if nav.blocked:
                        await self._log_step("NAVIGATE", "", "", "", "", nav.reason, 0, nav.reason)
                        if "dry-run" in nav.reason:
                            self.sm.transition(AgentState.STOPPED, nav.reason)
                        elif "no unfinished section found" in nav.reason and cls == PageState.OUTLINE:
                            # Current course outline shows 100% everywhere:
                            # record the course as done, then walk back to the
                            # My Classes hub for the next course when known.
                            # Record BOTH the hub card title (current) and the
                            # outline header so dash variants / positional
                            # fallbacks still match hub skipping next time.
                            try:
                                from agent.action_planner import normalize_course_title as _norm
                                from agent.action_planner import outline_course_title as _ot
                                titles = [self.current_course_title or "", _ot(snap_before)]
                                if not s.dry_run:
                                    for t in titles:
                                        if t:
                                            self.store.record_finished_course(_norm(t))
                            except Exception as e:  # noqa: BLE001
                                log.debug("could not record finished course: %s", e)
                            self.courses_done += 1
                            self.current_section = None
                            if self.classes_url:
                                self._return_to = self.classes_url
                                self.sm.transition(AgentState.RETURNING,
                                                   f"course complete ({self.current_course_title or 'outline'}), back to My Classes for the next course")
                                self.current_course_title = None
                            else:
                                self.sm.transition(AgentState.COMPLETED, f"course complete: {nav.reason}")
                        elif "already finished" in nav.reason and cls == PageState.OUTLINE and self.classes_url:
                            # Redo guard hit inside a multi-course run: do not
                            # loop on this outline; park it as done for hub
                            # skipping and continue with the next course.
                            try:
                                from agent.action_planner import normalize_course_title as _norm2
                                from agent.action_planner import outline_course_title as _ot2
                                titles = [self.current_course_title or "", _ot2(snap_before)]
                                if not s.dry_run:
                                    for t in titles:
                                        if t:
                                            self.store.record_finished_course(_norm2(t))
                            except Exception as e:  # noqa: BLE001
                                log.debug("could not record finished course: %s", e)
                            self._return_to = self.classes_url
                            self.sm.transition(AgentState.RETURNING,
                                               f"course already finished ({nav.reason}), back to My Classes for the next course")
                            self.current_course_title = None
                            self.current_section = None
                        elif "no unfinished class found" in nav.reason:
                            self.sm.transition(AgentState.COMPLETED, f"all classes complete: {nav.reason}")
                        elif "already finished" in nav.reason:
                            self.sm.transition(AgentState.STOPPED, nav.reason)
                        else:
                            self.sm.transition(AgentState.RECOVER, nav.reason)
                        continue
                    pending_actions = nav.actions
                    if cls == PageState.OUTLINE and nav.actions:
                        self.current_section = section_key(nav.actions[0].button_name)
                    if cls == PageState.CLASSES and nav.course_title:
                        self.current_course_title = nav.course_title
                    # Human-readable forward plan (hub shows the course title,
                    # not just the repeated "Take Class").
                    self.pending_nav = " then ".join(
                        (a.label or a.button_name) + (f" #{a.occurrence + 1}" if a.occurrence else "")
                        if (a.label or a.button_name) else "" for a in nav.actions)
                    await self._log_step("NAVIGATE", "", "", "", self.pending_nav,
                                         "forward clicks ready", 0, "")
                    if lobby_exit and not nav.blocked:
                        # Leaving a finished quiz behind: fresh answer memory
                        # for the next one (question numbers repeat per quiz).
                        self.submitted_ids.clear()
                        self.recovery = RecoveryManager(max_retries=s.max_retries)
                    if nav.needs_approval or s.require_approval:
                        self.sm.transition(AgentState.AWAIT_APPROVAL, "forward clicks need your approval")
                    else:
                        self.sm.transition(AgentState.ACT, "forward clicks ready, will click now")

                elif st == AgentState.ACT:
                    acting_on_nav = self.pending_nav is not None
                    assert question is not None or acting_on_nav
                    before = snap_before
                    assert before is not None
                    qid = (question.question_id or "") if question else ""
                    ok_all = True
                    err_msg = ""
                    for act in pending_actions:
                        if question is not None and act.type == ActionType.CLICK_BUTTON and question.question_id in self.submitted_ids:
                            ok_all = False
                            err_msg = "already submitted this question, skipping the second submit to be safe"
                            break
                        res = await browser_executor.execute(page, act)
                        self.actions_taken += 1
                        act_label = (getattr(act, "label", "") or act.button_name or act.option_id or act.text[:40])
                        if getattr(act, "occurrence", 0):
                            act_label += f" #{act.occurrence + 1}"
                        await self._log_step("ACT", qid, "",
                                             _cand_str(candidate) if candidate else (f"forward clicks: {self.pending_nav}" if acting_on_nav else ""),
                                             f"{act.type.value}:{act.option_id or act_label or act.text[:40]}",
                                             res.message, 0, "" if res.ok else res.message)
                        if not res.ok:
                            ok_all = False
                            err_msg = res.message
                            # Save a picture of the failure so you can see what the page looked like.
                            try:
                                shot = await self.session.screenshot(f"act-fail-{qid or 'q'}.png")
                                log.warning("Could not click/type; saved a picture of the page at %s to show what it looked like", shot)
                            except Exception:
                                pass
                            break
                        if act.type == ActionType.CLICK_BUTTON and question is not None:
                            self.submitted_ids.add(question.question_id or f"idx-{self.questions_done}")
                    if not ok_all:
                        scope = f"act-{qid}" if qid else "act-nav"
                        dec = self.recovery.should_retry(scope, err_msg)
                        self.sm.transition(AgentState.RECOVER if dec.retry else AgentState.STOPPED,
                                           f"could not click/type: {err_msg}. Next: will try a safe retry.")
                        continue
                    # Wait briefly for the page to react (checked properly afterwards, not just by waiting).
                    try:
                        await page.wait_for_timeout(600)
                    except Exception:
                        pass
                    self.sm.transition(AgentState.VERIFY, "clicks finished, will check the result")

                elif st == AgentState.VERIFY:
                    before = snap_before
                    acting_on_nav = self.pending_nav is not None
                    assert before is not None and (question is not None or acting_on_nav)
                    qid = (question.question_id or "") if question else ""
                    # Keep looking for a while (some pages answer slowly: a result
                    # message often shows first before the next question appears).
                    # Forward walks get longer patience: starting a quiz can
                    # take a while on the course site.
                    after = await observe(page)
                    deadline = time.monotonic() + (20.0 if acting_on_nav else 8.0)
                    result = verify(before, after)
                    while result.verdict in (Verdict.NO_CHANGE, Verdict.UNCERTAIN, Verdict.FEEDBACK) and time.monotonic() < deadline:
                        await asyncio.sleep(0.5)
                        after = await observe(page)
                        result = verify(before, after)
                        # A "wrong answer" message with no new question will
                        # never move on: stop waiting early and report it.
                        if result.verdict == Verdict.FEEDBACK and "incorrect" in (after.feedback_text or "").lower():
                            break
                    _plain = {
                        Verdict.COMPLETED: "quiz finished",
                        Verdict.ADVANCED: "moved to the next question",
                        Verdict.NAVIGATED: "moved to a new page",
                        Verdict.FEEDBACK: "page shows a result message",
                        Verdict.NO_CHANGE: "page did not change",
                        Verdict.UNCERTAIN: "unclear what happened",
                    }.get(result.verdict, result.verdict.value)
                    verdict_note = f"{_plain}: {result.detail}"
                    await self._log_step("VERIFY", qid, "",
                                         _cand_str(candidate) if candidate else (f"forward clicks: {self.pending_nav}" if acting_on_nav else ""),
                                         "checked the result", verdict_note, 0, "")
                    if result.verdict == Verdict.COMPLETED:
                        self.questions_done += 1
                        snap_before = after
                        question, candidate, pending_actions = None, None, []
                        self.pending_nav = None
                        self._nav_from = None
                        if self.current_section and not s.dry_run:
                            try:
                                course = course_key_for_url(self.outline_url)
                                if course:
                                    self.store.record_finished_section(course, self.current_section)
                            except Exception as e:  # noqa: BLE001
                                log.debug("could not record finished section: %s", e)
                            self.current_section = None
                        if s.auto_advance_lessons and self.outline_url:
                            self.quizzes_done += 1
                            self._return_to = self.outline_url
                            self.sm.transition(AgentState.RETURNING, verdict_note + " - quiz finished, going back to the outline")
                        else:
                            self.sm.transition(AgentState.COMPLETED, verdict_note)
                    elif result.verdict == Verdict.ADVANCED:
                        self.questions_done += 1
                        snap_before = after
                        question, candidate, pending_actions = None, None, []
                        self.pending_nav = None
                        self._nav_from = None
                        self.sm.transition(AgentState.OBSERVE, verdict_note)
                        # The fresh page copy is already in hand;
                        # the next loop looks again anyway (cheap and safe).
                    elif result.verdict == Verdict.NAVIGATED:
                        self.navigations_done += 1
                        if before.question_id:
                            # Left a question behind for a non-question page
                            # (quiz submitted, site returned to lobby): count it.
                            self.questions_done += 1
                        # Outline/hub/home revisits are the normal way back after
                        # each quiz/section/course, so only other pages count as
                        # walked for the loop guard.
                        if self._nav_from not in (PageState.OUTLINE, PageState.CLASSES, PageState.HOME):
                            self.visited_urls.add(before.url or "")
                        snap_before = after
                        question, candidate, pending_actions = None, None, []
                        self.pending_nav = None
                        self._nav_from = None
                        self.sm.transition(AgentState.OBSERVE, verdict_note)
                    elif result.verdict == Verdict.FEEDBACK:
                        # Result message shown but no new question yet: look again for the next question.
                        snap_before = after
                        self.pending_nav = None
                        self._nav_from = None
                        self.sm.transition(AgentState.OBSERVE, verdict_note)
                        # The current page shows a result message;
                        # the next look will pick up the next question if it appears.
                    else:
                        try:
                            shot = await self.session.screenshot(
                                f"verify-uncertain-{qid or 'q'}.png")
                            verdict_note += f" [picture saved at {shot}]"
                        except Exception:
                            pass
                        dec = self.recovery.should_retry(
                            f"verify-{qid or 'nav'}", verdict_note,
                            maybe_already_succeeded=False)
                        if dec.retry:
                            snap_before = after  # re-observe already done
                            self.sm.transition(AgentState.RECOVER, verdict_note)
                        else:
                            self.errors.append(verdict_note)
                            self.sm.transition(AgentState.STOPPED, verdict_note)

                elif st == AgentState.RETURNING:
                    target = self._return_to or self.outline_url
                    if not target:
                        self.sm.transition(AgentState.COMPLETED, "quiz finished and no outline to return to")
                    else:
                        is_hub = target == self.classes_url
                        try:
                            await self.session.goto(target)
                        except Exception as e:  # noqa: BLE001
                            where = "My Classes hub" if is_hub else "the outline"
                            await self._log_step("RETURNING", "", "", "", target, "", 0,
                                                 f"finished work but could not get back to {where} ({e}); open it by hand and say go")
                            self.sm.transition(AgentState.STOPPED, f"finished work but could not get back to {where} ({e})")
                            continue
                        # Fresh slate for the next section/course; redo memory kept
                        # so finished sections/courses are never entered twice.
                        self.submitted_ids.clear()
                        self.recovery = RecoveryManager(max_retries=s.max_retries)
                        self._return_to = ""
                        if is_hub:
                            self.sm.transition(AgentState.OBSERVE, "back on My Classes hub for the next course")
                        else:
                            self.sm.transition(AgentState.OBSERVE, "back on the course outline")

                elif st == AgentState.RECOVER:
                    # Safe retry: check whether the last submit already worked before trying again.
                    # First give a loading page a moment to settle: re-looking
                    # instantly often catches it mid-load with no buttons yet.
                    try:
                        await page.wait_for_timeout(2500)
                    except Exception:
                        pass
                    fresh = await observe(page)
                    if snap_before is not None and fresh.question_id != snap_before.question_id and fresh.question_id:
                        snap_before = fresh
                        question, candidate, pending_actions = None, None, []
                        self.pending_nav = None
                        self._nav_from = None
                        self.sm.transition(AgentState.OBSERVE, "a new question appeared, continuing there")
                        continue
                    snap_before = fresh
                    question, candidate, pending_actions = None, None, []
                    self.pending_nav = None
                    self._nav_from = None
                    # Limited tries: if this page has been retried too often, stop and ask a person.
                    scope = f"recover-{fresh.question_id or 'page'}"
                    dec = self.recovery.should_retry(scope, "trying a safe retry after a problem")
                    if not dec.retry and dec.escalate_to_human:
                        self.sm.transition(AgentState.STOPPED, "tried several times with no progress; please take over by hand")
                    else:
                        # Stop after too many steps without progress (avoid looping forever).
                        self.sm.transition(AgentState.OBSERVE, "trying again safely by looking at the page fresh")
                else:
                    self.sm.force(AgentState.FAILED, f"unexpected step {st}; stopping safely")
            # ---- terminal bookkeeping ----
            final = self.sm.current.value
            self.store.finish_run(self.run_id, final, self.questions_done,
                                  self.model_calls, self.model_latency, "; ".join(self.errors))
            summary = self.store.summary(self.run_id)
            summary["final_state"] = final
            summary["navigations_done"] = self.navigations_done
            summary["quizzes_done"] = self.quizzes_done
            summary["courses_done"] = self.courses_done
            return summary
        except Exception as e:  # noqa: BLE001 - never crash without persisting
            log.exception("The quiz helper stopped unexpectedly: %s", e)
            try:
                self.sm.force(AgentState.FAILED, str(e))
            except Exception:
                pass
            try:
                self.store.finish_run(self.run_id, "FAILED", self.questions_done,
                                      self.model_calls, self.model_latency, str(e))
                summary = self.store.summary(self.run_id)
                summary["final_state"] = "FAILED"
                summary["error"] = str(e)
                summary["navigations_done"] = self.navigations_done
                summary["quizzes_done"] = self.quizzes_done
                summary["courses_done"] = self.courses_done
                return summary
            except Exception:
                return {"final_state": "FAILED", "error": str(e)}
        finally:
            try:
                await self.session.close()
            except Exception:
                pass

    async def _log_step(self, state: str, qid: str, qtext: str, answer: str,
                        action: str, verification: str, retries: int, error: str) -> None:
        qtext_store = "" if not self.settings.persist_question_text else qtext
        try:
            self.store.log_step(self.run_id, state, qid, qtext_store, answer, action,
                                verification, retries, error)
        except Exception as e:  # noqa: BLE001
            log.debug("could not save progress to the local file: %s", e)
        if error:
            log.warning("[%s] question=%s problem=%s", state, qid, error)
        else:
            log.info("[%s] question=%s %s", state, qid, verification or action or answer)


def _cand_str(c: AnswerCandidate | None) -> str:
    if c is None:
        return ""
    ids = c.selected_option_ids or []
    status_plain = "no answer found" if c.status.value == "unresolved" else c.status.value
    return (f"choice={c.selected_option_id} choices={ids or '-'} "
            f"typed={c.text_answer} result={status_plain}")
