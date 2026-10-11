"""Start the quiz helper: python main.py [--dry-run] [--headless/--headed] [--max-questions N].

Preview mode (--dry-run) prepares answers without submitting them."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from agent.controller import Controller
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
try:
    from pathlib import Path as _Path
    _Path("artifacts").mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler("artifacts/agent.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)
except Exception:
    pass
log = logging.getLogger("browser-agent")


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="AI Browser Agent (answers quiz questions in your browser)")
    p.add_argument("--dry-run", action="store_true", default=None)
    p.add_argument("--headed", action="store_true")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--max-questions", type=int, default=None)
    p.add_argument("--target-url", type=str, default=None)
    p.add_argument("--require-approval", action="store_true", default=None)
    return p.parse_args(argv)


async def amain() -> int:
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    if args.headed:
        os.environ["HEADLESS"] = "false"
    if args.headless:
        os.environ["HEADLESS"] = "true"
    if args.max_questions is not None:
        os.environ["MAX_QUESTIONS"] = str(args.max_questions)
    if args.target_url:
        os.environ["TARGET_URL"] = args.target_url
    if args.require_approval:
        os.environ["REQUIRE_APPROVAL"] = "true"

    settings = get_settings()
    logging.getLogger().setLevel(getattr(logging, settings.log_level, logging.INFO))
    if not settings.target_url and settings.connection_mode != "cdp":
        log.error("TARGET_URL is not set. Copy .env.example to .env and set TARGET_URL.")
        return 2
    if not settings.target_url:
        log.info("No website address given: using the browser tab you already have open. Keep the quiz tab open and the helper will continue there.")

    def approve(question, candidate):
        # Human approval gate: print Q/A and ask on stdin.
        print(f"\nQ [{question.question_id}]: {question.text}")
        for o in question.options:
            print(f"  {o.option_id}: {o.text}")
        print(f"Proposed: option={candidate.selected_option_id} text={candidate.text_answer}")
        try:
            resp = input("Approve submit? [y/N] ").strip().lower()
        except EOFError:
            return False
        return resp in {"y", "yes"}

    def approve_nav(label):
        # Approval gate for forward clicks (Save and Continue, Take an Assessment, Start).
        print(f"\nPlanned forward clicks: {label}")
        try:
            resp = input("Approve clicks? [y/N] ").strip().lower()
        except EOFError:
            return False
        return resp in {"y", "yes"}

    controller = Controller(settings,
                            approval_callback=approve if settings.require_approval else None,
                            nav_approval_callback=approve_nav if settings.require_approval else None)
    try:
        summary = await controller.run()
    except KeyboardInterrupt:
        log.warning("Stopped by you (Ctrl+C). Your browser was left as it was.")
        return 130
    print(f"\nHow it ended: {summary.get('final_state')}")
    print(f"Questions done: {summary.get('questions_done')}")
    print(f"Quizzes done: {summary.get('quizzes_done', 0)}")
    print(f"Pages walked: {summary.get('navigations_done', 0)}")
    print(f"AI answers requested: {summary.get('model_calls')}")
    for step in summary.get("steps", [])[-15:]:
        print(f"  [{step['state']}] question={step['question_id']} action={step['action']} check={step['verification']} problem={step['error']}")
    return 0 if summary.get("final_state") == "COMPLETED" else 1


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
