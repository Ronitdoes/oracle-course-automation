"""Picture fallback: takes a screenshot when the page text cannot be read.

This version only saves the picture; answering from the picture happens only
when picture-answering is turned on. Otherwise it reports 'not available'
so the helper tries a safe retry instead of guessing blindly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page

from config import Settings

log = logging.getLogger(__name__)


@dataclass
class VisualObservation:
    ok: bool
    screenshot_path: str = ""
    note: str = ""
    width: int = 0
    height: int = 0


async def capture(page: Page, settings: Settings, name: str = "fallback.png") -> VisualObservation:
    try:
        outdir = Path(settings.screenshot_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        path = str(outdir / name)
        await page.screenshot(path=path)
        vp = page.viewport_size or {"width": 0, "height": 0}
        return VisualObservation(ok=True, screenshot_path=path, note="picture of the visible page saved",
                                 width=vp.get("width", 0), height=vp.get("height", 0))
    except Exception as e:  # noqa: BLE001
        return VisualObservation(ok=False, note=f"could not take a picture of the page: {e}")


def is_vision_enabled(settings: Settings) -> bool:
    # Picture-answering needs an explicitly picture-capable AI plan plus its secret key.
    # Keep text-first by default; turn on with LLM_PROVIDER=openai|groq|gemini plus an API key.
    return settings.llm_provider in {"openai", "openai-compatible", "groq", "gemini"} and bool(settings.api_key)
