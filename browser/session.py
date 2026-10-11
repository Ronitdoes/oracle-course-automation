"""Browser session: opens a fresh browser window, or connects to the browser window you already have open."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from config import Settings

log = logging.getLogger(__name__)


class BrowserSession:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._owned = True  # False when using your already-open browser: never close your browser.
        self._own_pages: list[Page] = []  # tabs opened by us; safe to close

    @property
    def page(self) -> Optional[Page]:
        return self._page

    async def start(self, url: str | None = None) -> Page:
        target = url if url is not None else self.settings.target_url
        if target and not self.settings.is_domain_allowed(target):
            raise PermissionError(f"Navigation to {target!r} blocked by ALLOWED_DOMAINS={self.settings.allowed_domains}")
        self._pw = await async_playwright().start()
        mode = self.settings.connection_mode
        if mode == "cdp":
            # Connect to a browser you already started with remote debugging turned on.
            # This does NOT work with a normally started Chrome window.
            log.info("Connecting to your already-open browser at %s. Next: keep that window open.", self.settings.cdp_endpoint)
            self._browser = await self._pw.chromium.connect_over_cdp(self.settings.cdp_endpoint)
            self._owned = False
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            if target:
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
                if not pages:
                    self._own_pages.append(self._page)
            else:
                # Use your current tab: the automation's tab list can include
                # stale or blank entries, so find the live quiz address directly
                # and open it in a fresh tab of the same window (same login).
                discovered = _discover_url_via_cdp(self.settings.cdp_endpoint,
                                                   self.settings.allowed_domains)
                self._page = await self._context.new_page()
                self._own_pages.append(self._page)
                if discovered:
                    log.info("Opening your quiz page at %s in a new tab", _redact_url(discovered))
                    await self._page.goto(discovered, wait_until="domcontentloaded")
                    await self._page.wait_for_load_state("domcontentloaded")
                else:
                    self._page = _pick_existing_page(_all_pages(self._browser),
                                                     self.settings.allowed_domains)
                    self._context = self._page.context
                    log.info("Using your current open tab: %s", _redact_url(self._page.url))
        else:
            if not target:
                raise ValueError("No website address configured (TARGET_URL). A fresh browser window needs an address to open. Copy .env.example to .env and set TARGET_URL, or use the already-open-browser mode.")
            log.info("Opening a fresh browser window (hidden=%s). Set HEADLESS=false to watch it work.", self.settings.headless)
            self._browser = await self._pw.chromium.launch(headless=self.settings.headless)
            self._context = await self._browser.new_context(viewport={"width": 1280, "height": 800})
            self._page = await self._context.new_page()
            self._own_pages.append(self._page)
        assert self._page is not None
        self._page.set_default_timeout(self.settings.action_timeout_ms)
        self._page.set_default_navigation_timeout(self.settings.navigation_timeout_ms)
        # Quiz submit buttons ("Complete Assessment") often pop up a
        # "Are you sure?" message. The automation normally closes such
        # pop-ups by itself, which would silently cancel the submit.
        # So click Yes on "Are you sure?" messages (you allowed finishing
        # quizzes); close plain info pop-ups.
        async def _on_dialog(dialog) -> None:
            try:
                if dialog.type == "confirm":
                    log.info("The page asked 'Are you sure?' - clicking Yes: %r", (dialog.message or "")[:120])
                    await dialog.accept()
                else:
                    await dialog.dismiss()
            except Exception as e:  # noqa: BLE001
                log.debug("could not answer the page's pop-up message: %s", e)
        try:
            self._page.on("dialog", _on_dialog)
        except Exception as e:  # noqa: BLE001
            log.debug("could not set up automatic pop-up handling: %s", e)
        if target:
            log.info("Opening page %s", _redact_url(target))
            await self._page.goto(target, wait_until="domcontentloaded")
            await self._page.wait_for_load_state("domcontentloaded")
        return self._page

    async def screenshot(self, name: str = "shot.png") -> str:
        if self._page is None:
            raise RuntimeError("Browser is not open yet. It should have been opened first.")
        outdir = Path(self.settings.screenshot_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        path = str(outdir / name)
        await self._page.screenshot(path=path)
        return path

    async def close(self) -> None:
        # Always close tabs opened by the helper (quiz work tabs and leftovers it owns).
        for p in list(self._own_pages):
            try:
                await p.close()
            except Exception as e:  # noqa: BLE001
                log.debug("Could not close a tab opened by the helper: %s", e)
        self._own_pages = []
        # When using your already-open browser, it stays yours: only disconnect,
        # never close your pages or your window.
        if not self._owned:
            try:
                if self._pw is not None:
                    await self._pw.stop()
            except Exception as e:  # noqa: BLE001
                log.debug("Could not disconnect cleanly from your browser: %s", e)
            finally:
                self._page = self._context = self._browser = self._pw = None
                log.info("Disconnected from your browser (your window was left open)")
            return
        # Close in reverse order; never leave the helper running.
        for closer, label in (
            (self._page, "page"),
            (self._context, "context"),
            (self._browser, "browser"),
        ):
            try:
                if closer is not None:
                    await closer.close()
            except Exception as e:  # noqa: BLE001 - shutdown must be best-effort
                log.debug("Could not close %s cleanly: %s", label, e)
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception as e:  # noqa: BLE001
            log.debug("Could not stop the browser helper cleanly: %s", e)
        finally:
            self._page = self._context = self._browser = self._pw = None
            log.info("Browser window closed")


def _all_pages(browser) -> list:
    found = []
    try:
        for ctx in browser.contexts:
            try:
                found.extend(ctx.pages)
            except Exception:
                continue
    except Exception:
        pass
    return found


def _discover_url_via_cdp(cdp_endpoint: str, allowed_domains: list[str]) -> str:
    """Read the open-tab list from the browser's debugging address.

    Returns the quiz page address, or "" when nothing usable is open.
    Raises AmbiguousTabs when several DIFFERENT quiz pages are open - picking
    one blindly could answer the wrong quiz try, so please
    leave exactly one quiz tab open instead.
    """
    import json
    import urllib.request

    try:
        base = cdp_endpoint.rstrip("/")
        with urllib.request.urlopen(base + "/json/list", timeout=5) as resp:
            targets = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        log.debug("could not list your open browser tabs: %s", e)
        return ""
    pages = [t for t in targets
             if isinstance(t, dict) and t.get("type") == "page"
             and (t.get("url") or "").startswith("http")]
    if not pages:
        return ""
    if allowed_domains:
        matching = [t["url"] for t in pages
                    if any(d in (t.get("url") or "").lower() for d in allowed_domains)]
        # Group by quiz try (quiz links carry per-tab session parts and codes
        # that differ per tab even for the same try). One try open in several
        # tabs is fine - the website shares the state - so use the freshest tab.
        # Distinct tries mean stop and ask instead of answering the wrong quiz.
        groups: dict[str, list[str]] = {}
        for u in matching:
            groups.setdefault(_attempt_key(u), []).append(u)
        if len(groups) > 1:
            raise AmbiguousTabs(
                f"found {len(groups)} different quiz tries open "
                f"({', '.join(sorted(groups))}); "
                "please leave exactly one quiz tab open and run again")
        if matching:
            return groups[sorted(groups)[0]][-1]
    return pages[0].get("url") or ""


def _attempt_key(url: str) -> str:
    """Simplify a quiz web address to its quiz try (removes the per-visit session part and security code)."""
    u = re.sub(r"[?&]cs=[^&]*", "", url or "")
    head, sep, rest = u.partition("f?p=")
    if not sep:
        return u
    segs = rest.split(":")
    if len(segs) >= 3:
        segs[2] = "SESSION"  # per-load APEX session id
    return head + "f?p=" + ":".join(segs)


class AmbiguousTabs(RuntimeError):
    pass


def _pick_existing_page(pages, allowed_domains: list[str]):
    """Pick the tab that most likely holds the quiz (without opening any new page)."""
    if not pages:
        raise RuntimeError("No open tabs found in your browser. Please open the quiz page first.")
    if len(pages) == 1:
        return pages[0]
    for p in pages:
        try:
            url = (p.url or "").lower()
        except Exception:
            continue
        if not url or url in ("about:blank", "chrome://newtab/", "chrome://new-tab-page/"):
            continue
        if allowed_domains and any(d in url for d in allowed_domains):
            return p
    for p in pages:
        try:
            if p.url and p.url not in ("about:blank",):
                return p
        except Exception:
            continue
    return pages[0]


def _redact_url(url: str) -> str:
    # Never show passwords hidden inside web addresses.
    try:
        from urllib.parse import urlparse, urlunparse

        parts = urlparse(url)
        if parts.password:
            netloc = parts.hostname or ""
            if parts.username:
                netloc = f"{parts.username}:***@{netloc}"
            if parts.port:
                netloc += f":{parts.port}"
            return urlunparse(parts._replace(netloc=netloc))
        return url
    except Exception:
        return url
