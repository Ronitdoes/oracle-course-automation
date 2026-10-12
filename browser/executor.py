"""Clicks and types for the helper using the page's buttons and labels."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from playwright.async_api import Page

from browser.selectors import CHOICE

log = logging.getLogger(__name__)


class ActionType(str, Enum):
    OBSERVE = "observe"
    SELECT_OPTION = "select_option"
    CLEAR_SELECTIONS = "clear_selections"
    FILL_TEXT = "fill_text"
    CLICK_BUTTON = "click_button"
    NAVIGATE = "navigate"
    WAIT = "wait"
    SCREENSHOT = "screenshot"


@dataclass
class Action:
    type: ActionType
    option_id: str = ""
    text: str = ""
    button_name: str = ""
    timeout_ms: int = 8000
    screenshot_path: str = ""
    # Nth matching button/link with the same visible name (0-based).
    # My Classes hub shows one identical "Take Class" button per course card,
    # so the 2nd course needs occurrence=1 to avoid always clicking the first.
    occurrence: int = 0
    # Human display only, e.g. "Take Class - Database Programming with SQL".
    # Never used for matching; matching uses button_name + occurrence.
    label: str = ""


@dataclass
class ActionResult:
    ok: bool
    message: str = ""
    screenshot_path: str = ""
    detail: dict = field(default_factory=dict)


async def execute(page: Page, action: Action) -> ActionResult:
    """Do one click or typing step. Never assume it worked - the caller looks at the page again to check."""
    try:
        if action.type == ActionType.OBSERVE:
            return ActionResult(ok=True, message="looked at the page")
        if action.type == ActionType.SCREENSHOT:
            if action.screenshot_path:
                await page.screenshot(path=action.screenshot_path)
            return ActionResult(ok=True, message="picture of the page saved", screenshot_path=action.screenshot_path)
        if action.type == ActionType.WAIT:
            try:
                await page.wait_for_load_state("networkidle", timeout=action.timeout_ms)
            except Exception:
                pass  # waiting is best-effort; the caller checks the page again explicitly
            return ActionResult(ok=True, message="waited briefly")
        if action.type == ActionType.SELECT_OPTION:
            return await _select_option(page, action.option_id, action.timeout_ms)
        if action.type == ActionType.CLEAR_SELECTIONS:
            return await _clear_selections(page, action.timeout_ms)
        if action.type == ActionType.FILL_TEXT:
            return await _fill_text(page, action.text, action.timeout_ms)
        if action.type == ActionType.CLICK_BUTTON:
            return await _click_button_and_confirm(page, action.button_name, action.timeout_ms)
        if action.type == ActionType.NAVIGATE:
            return await _navigate_click(page, action.button_name, action.timeout_ms,
                                         occurrence=action.occurrence)
        return ActionResult(ok=False, message=f"unknown step {action.type}. Next: report this to the helper's owner.")
    except Exception as e:  # noqa: BLE001
        log.warning("click/typing step %s did not work: %s", action.type, e)
        return ActionResult(ok=False, message=f"{type(e).__name__}: {e}")


async def _select_option(page: Page, option_id: str, timeout_ms: int) -> ActionResult:
    # 1) Usual practice-page marker: [data-option-id="..."] (button or label or input).
    try:
        el = page.locator(f"[data-option-id='{option_id}']").first
        # Escape single quotes defensively.
    except Exception:
        el = None
    if el is not None:
        try:
            if await el.count() > 0:
                # If it wraps an input, check it; if it's a button/label, click it.
                inner_input = el.locator("input[type='radio'], input[type='checkbox']").first
                try:
                    if await inner_input.count() > 0:
                        await inner_input.scroll_into_view_if_needed(timeout=timeout_ms)
                        await inner_input.check(timeout=timeout_ms)
                        return ActionResult(ok=True, message=f"ticked choice {option_id}")
                except Exception:
                    pass
                tag = ""
                try:
                    tag = (await el.evaluate("e => e.tagName.toLowerCase()")) or ""
                except Exception:
                    tag = ""
                await el.scroll_into_view_if_needed(timeout=timeout_ms)
                if tag == "input":
                    await el.check(timeout=timeout_ms)
                else:
                    await el.click(timeout=timeout_ms)
                return ActionResult(ok=True, message=f"clicked choice {option_id}")
        except Exception as e:  # noqa: BLE001
            log.debug("usual choice lookup did not match for %r: %s; trying the next way", option_id, e)
    # 2) input[value=...].
    try:
        inp = page.locator(f"input[type='radio'][value='{option_id}'], input[type='checkbox'][value='{option_id}']").first
        if await inp.count() > 0:
            await inp.scroll_into_view_if_needed(timeout=timeout_ms)
            await inp.check(timeout=timeout_ms)
            return ActionResult(ok=True, message=f"ticked choice {option_id}")
    except Exception as e:  # noqa: BLE001
        log.debug("choice lookup by value did not work: %s; trying the next way", e)
    # 3) Positional fallback for pages without markers (quiz choices are choice-0..choice-N).
    # Same lookup as the page reader, so number N is the same control.
    # Plain tick boxes are ticked; picture-only round/ square choices are clicked.
    m = re.fullmatch(r"opt-(\d+)", option_id)
    if m:
        try:
            loc = page.locator(CHOICE).nth(int(m.group(1)))
            await loc.scroll_into_view_if_needed(timeout=timeout_ms)
            try:
                await loc.check(timeout=timeout_ms)
            except Exception:
                await loc.click(timeout=timeout_ms)
            return ActionResult(ok=True, message=f"picked choice number {m.group(1)}")
        except Exception as e:  # noqa: BLE001
            log.debug("choice lookup by number did not work: %s; trying the next way", e)
    # 4) Visible label / choice name.
    for attempt in (page.get_by_role("radio", name=option_id), page.get_by_text(option_id, exact=False)):
        try:
            first = attempt.first
            if await first.count() > 0 and await first.is_visible():
                await first.scroll_into_view_if_needed(timeout=timeout_ms)
                await first.click(timeout=timeout_ms)
                return ActionResult(ok=True, message=f"clicked choice named {option_id}")
        except Exception:
            continue
    return ActionResult(ok=False, message=f"could not find or click choice '{option_id}'. Next: check that the choice is visible and clickable.")


async def _clear_selections(page: Page, timeout_ms: int) -> ActionResult:
    """Untick everything currently ticked so the planned set is exact.

    Plain tick boxes are unticked; picture-only choices get marked unpicked.
    Round single-choice buttons cannot be unticked through the browser
    (the next pick replaces them instead) and are skipped.
    """
    cleared = 0
    try:
        loc = page.locator(CHOICE)
        n = await loc.count()
    except Exception as e:  # noqa: BLE001
        return ActionResult(ok=False, message=f"could not clear previous ticks: {e}. Next: reload the question and try again.")
    for i in range(min(n, 20)):
        el = loc.nth(i)
        try:
            tag = ((await el.evaluate("e => e.tagName.toLowerCase()")) or "")
        except Exception:
            continue
        try:
            if tag == "input":
                try:
                    if await el.is_checked():
                        await el.uncheck(timeout=timeout_ms)
                        cleared += 1
                except Exception:
                    pass  # e.g. round single-choice buttons: cannot be unticked, skip
            else:
                try:
                    if (await el.get_attribute("aria-checked")) == "true":
                        await el.evaluate("e => e.setAttribute('aria-checked', 'false')")
                        cleared += 1
                except Exception:
                    pass
        except Exception:
            continue
    return ActionResult(ok=True, message=f"cleared {cleared} ticked choice(s)")


async def _fill_text(page: Page, text: str, timeout_ms: int) -> ActionResult:
    candidates = [
        page.locator("[data-answer-input]").first,
        page.get_by_role("textbox").first,
        page.locator("input[type='text'], input:not([type]), textarea").first,
    ]
    last_err = ""
    for loc in candidates:
        try:
            if await loc.count() > 0 and await loc.is_visible():
                if not await loc.is_enabled():
                    last_err = "textbox disabled"
                    continue
                await loc.scroll_into_view_if_needed(timeout=timeout_ms)
                await loc.fill(text, timeout=timeout_ms)
                return ActionResult(ok=True, message="typed into the text box")
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            continue
    return ActionResult(ok=False, message=f"could not find a place to type ({last_err}). Next: check that a text box is visible.")


async def _click_button(page: Page, name: str, timeout_ms: int) -> ActionResult:
    # Prefer the practice-page marker, then the exact visible button name.
    for loc in (page.locator("[data-submit]").first, page.get_by_role("button", name=name).first):
        try:
            if await loc.count() > 0:
                if not await loc.is_visible():
                    continue
                if not await loc.is_enabled():
                    return ActionResult(ok=False, message=f"the '{name}' button is greyed out, so it cannot be clicked yet. Next: wait for the page to enable it.")
                await loc.scroll_into_view_if_needed(timeout=timeout_ms)
                await loc.click(timeout=timeout_ms)
                return ActionResult(ok=True, message=f"clicked '{name}'")
        except Exception as e:  # noqa: BLE001
            log.debug("click attempt for %r did not work: %s; trying the next way", name, e)
            continue
    # Known submit wordings ("Submit Answer", "Complete Assessment", ...).
    # Submit buttons only: tried in fixed order, first visible and clickable wins.
    if name.strip().lower() == "submit":
        from browser.selectors import SUBMIT_SYNONYMS

        for synonym in SUBMIT_SYNONYMS:
            try:
                loc = page.get_by_role("button", name=synonym).first
                if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                    await loc.scroll_into_view_if_needed(timeout=timeout_ms)
                    await loc.click(timeout=timeout_ms)
                    return ActionResult(ok=True, message=f"clicked '{synonym}' (as Submit)")
            except Exception as e:  # noqa: BLE001
                log.debug("wording click %r did not work: %s; trying the next way", synonym, e)
                continue
    # Last resort: an explicit submit button.
    for loc in (page.locator("button[type='submit']").first,):
        try:
            if await loc.count() > 0 and await loc.is_visible() and await loc.is_enabled():
                await loc.click(timeout=timeout_ms)
                return ActionResult(ok=True, message="clicked the submit button")
        except Exception:
            continue
    return ActionResult(ok=False, message=f"could not find a button called '{name}'. Next: check the page shows that button.")


async def _navigate_click(page: Page, name: str, timeout_ms: int, occurrence: int = 0) -> ActionResult:
    """Click a forward-walk button or section link by its exact visible name.

    Unlike submit clicks there are deliberately NO wordings or fallbacks here:
    on lesson/lobby pages a wrong click (Previous, Return to Course, Exit)
    would walk away from the quiz, so a missing control is a clean failure.
    One exception: a stale pop-up box left open (e.g. from an earlier click)
    is dismissed with Escape first — but only when it holds nothing matching
    this click, so a live Start/confirm box is never touched.

    occurrence picks the Nth matching button/link (0-based) for duplicate
    names such as the My Classes hub's repeated "Take Class" buttons.
    """
    if not (name or "").strip():
        return ActionResult(ok=False, message="no forward button name was planned")
    # A section link name can end with its row's own progress number
    # ("Section 8 - ... 90%"). Match with the clean name: the number is only
    # metadata for picking, and a bare name always matches the link.
    name = re.sub(r"\s*\d+\s*%\s*$", "", name).strip() or name
    try:
        dialog = page.get_by_role("dialog").first
        if await dialog.count() > 0 and await dialog.is_visible():
            keeps = False
            for role in ("button", "link"):
                try:
                    cand = dialog.get_by_role(role, name=name).first
                    if await cand.count() > 0 and await cand.is_visible():
                        keeps = True
                        break
                except Exception:
                    continue
            if not keeps:
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
                except Exception:
                    pass
    except Exception as e:  # noqa: BLE001
        log.debug("pop-up check did not work: %s", e)
    for role in ("button", "link"):
        try:
            all_loc = page.get_by_role(role, name=name)
            try:
                total = await all_loc.count()
            except Exception:
                continue
            if total == 0:
                continue
            # Collect visible matches in order; occurrence picks the Nth one
            # (My Classes hub repeats identical "Take Class" buttons).
            target = None
            seen = 0
            for i in range(min(total, 20)):
                try:
                    cand = all_loc.nth(i)
                    if not await cand.is_visible():
                        continue
                    if seen == occurrence:
                        target = cand
                        break
                    seen += 1
                except Exception:
                    continue
            if target is None:
                # Fallback: first visible when occurrence out of range.
                try:
                    first = all_loc.first
                    if await first.count() > 0 and await first.is_visible():
                        target = first
                    else:
                        continue
                except Exception:
                    continue
            loc = target
            if not await loc.is_enabled():
                return ActionResult(ok=False, message=f"the '{name}' {role} is greyed out, so it cannot be clicked yet. Next: wait for the page to enable it.")
            await loc.scroll_into_view_if_needed(timeout=timeout_ms)
            await loc.click(timeout=timeout_ms)
            extra = f" #{occurrence + 1}" if occurrence else ""
            return ActionResult(ok=True, message=f"clicked '{name}'{extra}")
        except Exception as e:  # noqa: BLE001
            log.debug("forward click %r (%s) did not work: %s", name, role, e)
            continue
    return ActionResult(ok=False, message=f"could not find a button or link called '{name}'. Next: check the page shows it.")


async def _click_button_and_confirm(page: Page, name: str, timeout_ms: int) -> ActionResult:
    """Submit click plus one same-wording confirmation inside a pop-up box.

    Some quiz sites answer the first submit click with a pop-up box carrying
    a second same-worded button. When such a box is open after the first
    click, click its button once. Limited to at most two clicks, both only
    on submit wordings, pop-up button only.
    """
    from browser.selectors import SUBMIT_SYNONYMS

    first = await _click_button(page, name, timeout_ms)
    if not first.ok:
        return first
    try:
        await page.wait_for_timeout(900)
        dialog = page.get_by_role("dialog").first
        if await dialog.count() == 0 or not await dialog.is_visible():
            return first
        for label in (name, *SUBMIT_SYNONYMS):
            try:
                btn = dialog.get_by_role("button", name=label).first
                if await btn.count() > 0 and await btn.is_visible() and await btn.is_enabled():
                    await btn.scroll_into_view_if_needed(timeout=timeout_ms)
                    await btn.click(timeout=timeout_ms)
                    return ActionResult(ok=True, message=f"{first.message}, then confirmed '{label}' in the pop-up by clicking Yes")
            except Exception as e:  # noqa: BLE001
                log.debug("pop-up Yes-click %r did not work: %s", label, e)
                continue
    except Exception as e:  # noqa: BLE001
        log.debug("pop-up check did not work: %s", e)
    return first
