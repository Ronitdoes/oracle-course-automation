"""Page reader: reads the page's text and buttons into a standard summary the rest of the program can use. Prefers the page's built-in labels over raw layout."""
from __future__ import annotations

import html
import logging
import re

from playwright.async_api import Page

from browser.selectors import CHOICE
from perception.question_extractor import extract_apex_block
from solver.schemas import AnswerOption, ControlInfo, PageSnapshot

log = logging.getLogger(__name__)

# Curated finish phrases (see note at use site): bare "completion" is
# excluded because answer choices like the name "completion_%" match it.
COMPLETION_PHRASES = ("quiz complete", "quiz completed", "all done",
                      "congratulations", "you finished",
                      "assessment complete", "assessment submitted",
                      "test submitted", "exam submitted",
                      "thank you for completing",
                      "score:", "final score")
# How-to banners that look like result messages but are always on screen
# (e.g. quiz pages saying "Choices - Just one correct!"). Real submit results
# ("Correct!", "Incorrect, try again") never match these.
FEEDBACK_EXCLUSIONS = re.compile(
    r"just one correct|choose one|select all that apply|mark all that apply|^\s*choices\s*-",
    re.IGNORECASE)


async def observe(page: Page, screenshot_on_demand: bool = False,
                 screenshot_path: str | None = None) -> PageSnapshot:
    """Read the address/title/text/buttons. Prefers the page's built-in labels over raw layout."""
    url = page.url
    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        visible_text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        visible_text = ""
    visible_text = (visible_text or "").strip()[:8000]

    # Loading indicator heuristics (non-fatal).
    is_loading = False
    try:
        loading_loc = page.locator("[aria-busy='true'], .loading, .spinner, [data-loading='true']")
        is_loading = await loading_loc.count() > 0 and await loading_loc.first.is_visible()
    except Exception:
        is_loading = False

    snap = PageSnapshot(url=url, title=title, visible_text=visible_text, is_loading=is_loading)

    # --- Usual question markers (practice pages + well-formed pages) ---
    try:
        qroot = page.locator("[data-question-id]").first
        if await qroot.count() > 0 and await qroot.is_visible():
            qid = await qroot.get_attribute("data-question-id")
            snap.question_id = (qid or "").strip() or None
            qtext_loc = qroot.locator("[data-question-text]").first
            if await qtext_loc.count() > 0:
                snap.question_text = ((await qtext_loc.inner_text()) or "").strip()[:2000]
            else:
                # Fallback: heading inside question root.
                for sel in ("h1, h2, h3", "legend", "p"):
                    cand = qroot.locator(sel).first
                    if await cand.count() > 0:
                        t = ((await cand.inner_text()) or "").strip()
                        if len(t) > 3:
                            snap.question_text = t[:2000]
                            break
            # Choices: marked choice elements first.
            opt_els = qroot.locator("[data-option-id]")
            n = await opt_els.count()
            for i in range(min(n, 20)):
                el = opt_els.nth(i)
                oid = (await el.get_attribute("data-option-id") or "").strip() or f"opt-{i}"
                otext = ((await el.inner_text()) or "").strip()[:500] or oid
                snap.options.append(AnswerOption(option_id=oid, text=otext, control_hint=otext[:80]))
            # Round/square choice inputs inside the question block.
            if not snap.options:
                inputs = qroot.locator("input[type='radio'], input[type='checkbox']")
                n2 = await inputs.count()
                for i in range(min(n2, 20)):
                    el = inputs.nth(i)
                    val = (await el.get_attribute("value") or "").strip()
                    oid = val or f"opt-{i}"
                    label = ""
                    try:
                        # Associated <label for=...> or wrapping label.
                        el_id = await el.get_attribute("id")
                        if el_id:
                            lab = page.locator(f"label[for='{el_id}']").first
                            if await lab.count() > 0:
                                label = ((await lab.inner_text()) or "").strip()
                    except Exception:
                        pass
                    if not label:
                        label = oid
                    snap.options.append(AnswerOption(option_id=oid, text=label[:500], control_hint=label[:80]))
    except Exception as e:  # noqa: BLE001 - reading must keep trying
        log.debug("usual question reading did not work: %s; trying the next way", e)

    # --- Backup reading for pages without markers (quiz sites et al.) ---
    try:
        await _generic_choice_fallback(page, snap)
    except Exception as e:  # noqa: BLE001
        log.debug("backup question reading did not work: %s", e)

    # --- Typing-box detection ---
    # (recorded as a control; the reader step decides the question kind)

    # --- Buttons, boxes, and links list (by visible kind, limited count) ---
    # Links get a bigger cap: the course outline holds dozens of them and the
    # section entries live at the end of the list. A small cap silently cut
    # them off once, stranding a run on a "finished" outline.
    try:
        for role, kind in (("radio", "radio"), ("checkbox", "checkbox"),
                           ("textbox", "text"), ("button", "button"), ("link", "link")):
            cap = 60 if kind == "link" else 15
            loc = page.get_by_role(role)
            try:
                n = await loc.count()
            except Exception:
                continue
            for i in range(min(n, cap)):
                try:
                    item = loc.nth(i)
                    if not await item.is_visible():
                        continue
                    name = ""
                    try:
                        name = (await item.get_attribute("aria-label") or "").strip()
                    except Exception:
                        pass
                    if not name:
                        try:
                            name = ((await item.inner_text()) or "").strip()[:120]
                        except Exception:
                            try:
                                name = ((await item.input_value()) or "").strip()[:120]
                            except Exception:
                                name = ""
                    name = html.unescape(name)
                    hint = ""
                    if kind == "link" and re.match(r"section\s+\d+", name.strip(), re.IGNORECASE):
                        hint = await _row_percent(item)
                    snap.controls.append(ControlInfo(kind=kind, name=name, visible=True,
                                                     selector_hint=hint,
                                                     enabled=await item.is_enabled()))
                except Exception:
                    continue
    except Exception as e:  # noqa: BLE001
        log.debug("could not list the page's buttons and boxes: %s", e)

    # --- Result / finished signals ---
    low = visible_text.lower()
    try:
        # Read ALL result areas: pages often pair a permanent how-to
        # banner (skipped below) with a separate live result area.
        loc = page.locator("[data-feedback], [role='status'], [role='alert']")
        n = await loc.count()
        for i in range(min(n, 10)):
            el = loc.nth(i)
            try:
                if not await el.is_visible():
                    continue
                t = ((await el.inner_text()) or "").strip()[:1000]
                if t and not FEEDBACK_EXCLUSIONS.search(t):
                    snap.feedback_text = t
                    break
            except Exception:
                continue
    except Exception:
        pass
    if not snap.feedback_text:
        for kw in ("correct", "incorrect", "wrong answer", "try again", "accepted", "rejected"):
            if kw in low:
                # Capture the line containing the keyword.
                for line in visible_text.splitlines():
                    if kw in line.lower():
                        snap.feedback_text = line.strip()[:500]
                        break
                break
    # How-to banners ("Choices - Just one correct!") are permanent page
    # text, not submit results - never report them as result messages.
    if snap.feedback_text and FEEDBACK_EXCLUSIONS.search(snap.feedback_text):
        log.debug("Ignoring a permanent how-to banner (not a result message): %r", snap.feedback_text[:80])
        snap.feedback_text = ""
    try:
        comp = page.locator("[data-completion], [data-testid='completion']").first
        if await comp.count() > 0 and await comp.is_visible():
            snap.is_completion = True
    except Exception:
        pass
    if not snap.is_completion:
        # NOTE: bare "completion" is deliberately absent - choice texts like
        # the code name "completion_%" contain it mid-quiz and once wrongly
        # looked like the end. All phrases below are multi-word or
        # score-based and never appear inside answer choices.
        snap.is_completion = any(k in low for k in COMPLETION_PHRASES)

    if screenshot_on_demand and screenshot_path:
        try:
            await page.screenshot(path=screenshot_path)
            snap.screenshot_path = screenshot_path
        except Exception as e:  # noqa: BLE001
            log.debug("picture of the page could not be saved: %s", e)
    return snap


async def _row_percent(item) -> str:
    """Progress percent shown next to a course-section link, or "".

    Reads the link's own text first, then its parent row's text (the number
    sits beside the link, not inside it, on some pages). Takes the LAST
    number-with-% so wrapper text never wins over the row's own figure.
    Stored on the control (not in its name) so clicking still uses the name.
    """
    for get_text in (
        lambda: item.inner_text(),
        lambda: item.evaluate("e => (e.parentElement && e.parentElement.innerText) || ''"),
    ):
        try:
            found = re.findall(r"(\d+)\s*%", (await get_text()) or "")
        except Exception:
            continue
        if found:
            return f"{found[-1]}%"
    return ""


async def _generic_choice_fallback(page: Page, snap: PageSnapshot) -> None:
    """Pages without question markers (quiz sites): 'Question N of M' text plus plain choice buttons."""
    if not snap.question_id or not snap.question_text:
        qid, qtext = extract_apex_block(snap.visible_text)
        if qid and not snap.question_id:
            snap.question_id = qid
        if qtext and not snap.question_text:
            snap.question_text = qtext
    if snap.options:
        return
    try:
        radios = page.locator(CHOICE)
        n = await radios.count()
    except Exception:
        return
    for i in range(min(n, 20)):
        try:
            el = radios.nth(i)
            if not await el.is_visible():
                continue
            tag = ""
            try:
                tag = ((await el.evaluate("e => e.tagName.toLowerCase()")) or "")
            except Exception:
                tag = ""
            el_id = ((await el.get_attribute("id")) or "").strip()
            value = ((await el.get_attribute("value")) or "").strip()
            label = ""
            if tag == "input" and el_id and "'" not in el_id and '"' not in el_id:
                try:
                    lab = page.locator(f"label[for='{el_id}']").first
                    if await lab.count() > 0:
                        label = ((await lab.inner_text()) or "").strip()
                except Exception:
                    label = ""
            if not label and tag == "input":
                try:
                    anc = el.locator("xpath=ancestor::label[1]").first
                    if await anc.count() > 0:
                        label = ((await anc.inner_text()) or "").strip()
                except Exception:
                    pass
            if not label:
                try:
                    label = ((await el.get_attribute("aria-label")) or "").strip()
                except Exception:
                    pass
            if not label and tag != "input":
                # Picture-only choices (quiz sites): the element's own text.
                try:
                    label = ((await el.inner_text()) or "").strip()
                except Exception:
                    pass
            label = html.unescape(label).strip()
            if not label:
                continue
            snap.options.append(AnswerOption(option_id=value or f"opt-{len(snap.options)}",
                                             text=label[:500], control_hint=label[:80]))
        except Exception:
            continue
