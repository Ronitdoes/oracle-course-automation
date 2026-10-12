"""Read/write the .env settings file, preserving comments and order."""
from __future__ import annotations

import os
from pathlib import Path

KNOWN_KEYS: list[str] = [
    "LLM_PROVIDER", "MODEL_ID", "LLM_API_KEY", "LLM_API_KEYS", "LLM_BASE_URL", "MOCK_SOLVER_MODE",
    "TARGET_URL", "ALLOWED_DOMAINS",
    "HEADLESS", "BROWSER_CONNECTION_MODE", "CDP_ENDPOINT",
    "NAVIGATION_TIMEOUT_MS", "ACTION_TIMEOUT_MS",
    "MAX_QUESTIONS", "MAX_RETRIES", "MAX_ACTIONS", "RUN_MAX_DURATION_SEC",
    "SCREENSHOT_DIR", "DATABASE_PATH", "LOG_LEVEL",
    "DRY_RUN", "REQUIRE_APPROVAL", "AUTO_ADVANCE_LESSONS", "REDO_FINISHED_SECTIONS",
    "REDACT_QUESTION_TEXT_IN_LOGS", "PERSIST_QUESTION_TEXT",
]

# (key, label, kind, choices?) — kind: text|password|bool|int|combo
FIELD_SPECS: list[tuple] = [
    ("LLM_PROVIDER", "Provider", "combo", ["mock", "gemini", "groq", "openai"]),
    ("MODEL_ID", "Model ID", "text", None),
    ("LLM_API_KEY", "API key", "password", None),
    ("LLM_API_KEYS", "Backup API keys (failover, comma-separated)", "text", None),
    ("LLM_BASE_URL", "Base URL", "text", None),
    ("MOCK_SOLVER_MODE", "Mock mode", "combo", ["auto", "unresolved"]),
    ("TARGET_URL", "Target URL", "text", None),
    ("ALLOWED_DOMAINS", "Allowed domains (comma-separated)", "text", None),
    ("HEADLESS", "Headless (hide browser)", "bool", None),
    ("BROWSER_CONNECTION_MODE", "Connection", "combo", ["launch", "cdp"]),
    ("CDP_ENDPOINT", "CDP endpoint", "text", None),
    ("NAVIGATION_TIMEOUT_MS", "Navigation timeout (ms)", "int", None),
    ("ACTION_TIMEOUT_MS", "Action timeout (ms)", "int", None),
    ("MAX_QUESTIONS", "Max questions", "int", None),
    ("MAX_RETRIES", "Max retries", "int", None),
    ("MAX_ACTIONS", "Max actions", "int", None),
    ("SCREENSHOT_DIR", "Screenshot dir", "text", None),
    ("DATABASE_PATH", "Database path", "text", None),
    ("LOG_LEVEL", "Log level", "combo", ["DEBUG", "INFO", "WARNING", "ERROR"]),
    ("DRY_RUN", "Dry run (never submit)", "bool", None),
    ("REQUIRE_APPROVAL", "Require approval", "bool", None),
    ("REDO_FINISHED_SECTIONS", "Redo finished sections/courses", "bool", None),
    ("REDACT_QUESTION_TEXT_IN_LOGS", "Redact questions in logs", "bool", None),
    ("PERSIST_QUESTION_TEXT", "Persist question text", "bool", None),
]

GROUPS: list[tuple[str, list[str]]] = [
    ("Model", ["LLM_PROVIDER", "MODEL_ID", "LLM_API_KEY", "LLM_API_KEYS", "LLM_BASE_URL", "MOCK_SOLVER_MODE"]),
    ("Target", ["TARGET_URL", "ALLOWED_DOMAINS"]),
    ("Browser", ["HEADLESS", "BROWSER_CONNECTION_MODE", "CDP_ENDPOINT",
                 "NAVIGATION_TIMEOUT_MS", "ACTION_TIMEOUT_MS"]),
    ("Limits", ["MAX_QUESTIONS", "MAX_RETRIES", "MAX_ACTIONS"]),
    ("Storage", ["SCREENSHOT_DIR", "DATABASE_PATH", "LOG_LEVEL"]),
    ("Safety & privacy", ["DRY_RUN", "REQUIRE_APPROVAL", "REDO_FINISHED_SECTIONS",
                          "REDACT_QUESTION_TEXT_IN_LOGS", "PERSIST_QUESTION_TEXT"]),
]


def default_env_path() -> Path:
    return Path(".env")


def load_env(path: Path | str = ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return values
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            values[k] = v
    return values


def save_env(path: Path | str, updates: dict[str, str]) -> None:
    """Update keys in place, preserving comments; append missing keys."""
    p = Path(path)
    lines: list[str] = []
    if p.exists():
        lines = p.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            out.append(line)
            continue
        k, _, _ = s.partition("=")
        k = k.strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
            if k:
                seen.add(k)
    for k in KNOWN_KEYS:
        if k in updates and k not in seen:
            out.append(f"{k}={updates[k]}")
    for k, v in updates.items():
        if k not in seen and k not in KNOWN_KEYS:
            out.append(f"{k}={v}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def bool_to_str(v: bool) -> str:
    return "true" if v else "false"


def str_to_bool(v: str) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def default_browsers_path() -> Path:
    """Per-user dir for Playwright browser downloads (no admin needed).

    The installed app keeps its Chromium here so it survives reinstalls
    and never needs elevated rights. Normal desktop use (attaching to the
    user's own Chrome) never touches this folder.
    """
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        return Path(local) / "BrowserAgent" / "ms-playwright"
    return Path.home() / ".cache" / "BrowserAgent" / "ms-playwright"


def bundled_path(root: Path, name: str) -> Path:
    """Locate a file shipped with the app.

    Dev runs keep it next to the project (``root / name``). Frozen builds
    (PyInstaller onedir) place data files under ``sys._MEIPASS`` (the
    ``_internal`` folder beside the exe), so look there too.
    """
    direct = root / name
    if direct.exists():
        return direct
    try:
        import sys
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            cand = Path(meipass) / name
            if cand.exists():
                return cand
    except Exception:
        pass
    return direct
