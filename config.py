"""Central settings. Values come from environment variables and the .env file when present."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _get_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _parse_key_list(raw: str) -> list[str]:
    """Split a key setting on commas/semicolons/newlines (single key -> one item)."""
    return [p.strip() for p in re.split(r"[,;\n]+", raw or "") if p.strip()]


@dataclass
class Settings:
    llm_provider: str = field(default_factory=lambda: _get_str("LLM_PROVIDER", "mock"))
    model_id: str = field(default_factory=lambda: _get_str("MODEL_ID", "mock-model"))
    api_key: str = field(default_factory=lambda: _get_str("LLM_API_KEY", ""))
    # Failover pool: LLM_API_KEYS (comma/semicolon/newline separated) plus
    # LLM_API_KEY. First key tried first; api_key stays the first for compat.
    api_keys: list[str] = field(default_factory=list)
    base_url: str = field(default_factory=lambda: _get_str("LLM_BASE_URL", "https://api.openai.com/v1"))
    mock_mode: str = field(default_factory=lambda: _get_str("MOCK_SOLVER_MODE", "auto"))

    target_url: str = field(default_factory=lambda: _get_str("TARGET_URL", ""))
    allowed_domains: list[str] = field(default_factory=list)

    headless: bool = field(default_factory=lambda: _get_bool("HEADLESS", True))
    connection_mode: str = field(default_factory=lambda: _get_str("BROWSER_CONNECTION_MODE", "launch"))
    cdp_endpoint: str = field(default_factory=lambda: _get_str("CDP_ENDPOINT", "http://localhost:9222"))
    navigation_timeout_ms: int = field(default_factory=lambda: _get_int("NAVIGATION_TIMEOUT_MS", 15000))
    action_timeout_ms: int = field(default_factory=lambda: _get_int("ACTION_TIMEOUT_MS", 8000))

    max_questions: int = field(default_factory=lambda: _get_int("MAX_QUESTIONS", 500))
    max_retries: int = field(default_factory=lambda: _get_int("MAX_RETRIES", 2))
    max_actions: int = field(default_factory=lambda: _get_int("MAX_ACTIONS", 500))
    run_max_duration_sec: int = field(default_factory=lambda: _get_int("RUN_MAX_DURATION_SEC", 300))

    screenshot_dir: str = field(default_factory=lambda: _get_str("SCREENSHOT_DIR", "./artifacts/screenshots"))
    database_path: str = field(default_factory=lambda: _get_str("DATABASE_PATH", "./artifacts/runs.sqlite"))
    log_level: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))

    dry_run: bool = field(default_factory=lambda: _get_bool("DRY_RUN", False))
    require_approval: bool = field(default_factory=lambda: _get_bool("REQUIRE_APPROVAL", False))
    auto_advance_lessons: bool = field(default_factory=lambda: _get_bool("AUTO_ADVANCE_LESSONS", False))
    redo_finished_sections: bool = field(default_factory=lambda: _get_bool("REDO_FINISHED_SECTIONS", False))

    redact_question_text: bool = field(default_factory=lambda: _get_bool("REDACT_QUESTION_TEXT_IN_LOGS", False))
    persist_question_text: bool = field(default_factory=lambda: _get_bool("PERSIST_QUESTION_TEXT", True))

    def __post_init__(self) -> None:
        raw = _get_str("ALLOWED_DOMAINS", "")
        if raw.strip():
            self.allowed_domains = [d.strip().lower() for d in raw.split(",") if d.strip()]
        else:
            self.allowed_domains = []
        combined: list[str] = []
        for k in _parse_key_list(self.api_key) + _parse_key_list(_get_str("LLM_API_KEYS", "")):
            if k not in combined:
                combined.append(k)
        self.api_keys = combined
        if combined:
            self.api_key = combined[0]
        self.llm_provider = (self.llm_provider or "mock").lower()
        self.connection_mode = (self.connection_mode or "launch").lower()
        self.log_level = (self.log_level or "INFO").upper()

    def is_domain_allowed(self, url: str) -> bool:
        """Empty allowed_domains means no restriction (local file URLs always allowed)."""
        if not self.allowed_domains:
            return True
        try:
            from urllib.parse import urlparse

            host = (urlparse(url).hostname or "").lower()
            if not host:
                return True  # file:// URLs have no host; allow them
            return any(host == d or host.endswith("." + d) for d in self.allowed_domains)
        except Exception:
            return False


def get_settings() -> Settings:
    return Settings()
