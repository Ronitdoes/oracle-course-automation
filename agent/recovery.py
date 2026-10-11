"""Retry helper: tries again a limited number of times, avoids submitting twice, and asks a person when stuck."""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RecoveryDecision:
    retry: bool
    reason: str = ""
    escalate_to_human: bool = False


class RecoveryManager:
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
        self._counts: dict[str, int] = {}

    def retries_for(self, key: str) -> int:
        return self._counts.get(key, 0)

    def should_retry(self, key: str, error: str, maybe_already_succeeded: bool = False) -> RecoveryDecision:
        """Before trying a submit again, the caller must look at the page fresh to make sure the last try did not already work."""
        used = self._counts.get(key, 0)
        if maybe_already_succeeded:
            return RecoveryDecision(retry=False, reason="the last try may already have worked; look at the page again before trying again")
        if used >= self.max_retries:
            log.warning("Gave up retrying %r after several tries (%s). Next: please take over by hand.", key, error)
            return RecoveryDecision(retry=False, reason=f"tried {self.max_retries} times already, stopping so a person can help", escalate_to_human=True)
        self._counts[key] = used + 1
        log.info("Try %d of %d again for %r: %s", used + 1, self.max_retries, key, error)
        return RecoveryDecision(retry=True, reason=f"try {used + 1} of {self.max_retries}")
