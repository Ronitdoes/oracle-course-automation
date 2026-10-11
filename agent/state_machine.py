"""Step tracker: remembers which step the quiz helper is on and records each move."""
from __future__ import annotations

import logging
from enum import Enum

log = logging.getLogger(__name__)


class AgentState(str, Enum):
    INITIALIZE = "INITIALIZE"
    OBSERVE = "OBSERVE"
    CLASSIFY = "CLASSIFY"
    EXTRACT = "EXTRACT"
    SOLVE = "SOLVE"
    VALIDATE = "VALIDATE"
    AWAIT_APPROVAL = "AWAIT_APPROVAL"
    ACT = "ACT"
    NAVIGATE = "NAVIGATE"
    RETURNING = "RETURNING"
    VERIFY = "VERIFY"
    RECOVER = "RECOVER"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


TERMINAL = {AgentState.COMPLETED, AgentState.STOPPED, AgentState.FAILED}

# Allowed step order. Anything else means the program has a bug.
ALLOWED: dict[AgentState, set[AgentState]] = {
    AgentState.INITIALIZE: {AgentState.OBSERVE, AgentState.FAILED},
    AgentState.OBSERVE: {AgentState.CLASSIFY, AgentState.RECOVER, AgentState.FAILED, AgentState.STOPPED},
    AgentState.CLASSIFY: {AgentState.EXTRACT, AgentState.NAVIGATE, AgentState.COMPLETED, AgentState.RECOVER, AgentState.FAILED, AgentState.STOPPED},
    AgentState.EXTRACT: {AgentState.SOLVE, AgentState.RECOVER, AgentState.FAILED, AgentState.STOPPED},
    AgentState.SOLVE: {AgentState.VALIDATE, AgentState.RECOVER, AgentState.FAILED},
    AgentState.VALIDATE: {AgentState.AWAIT_APPROVAL, AgentState.ACT, AgentState.RECOVER, AgentState.FAILED, AgentState.STOPPED},
    AgentState.AWAIT_APPROVAL: {AgentState.ACT, AgentState.STOPPED, AgentState.RECOVER},
    AgentState.ACT: {AgentState.VERIFY, AgentState.RECOVER, AgentState.STOPPED, AgentState.FAILED},
    AgentState.NAVIGATE: {AgentState.ACT, AgentState.AWAIT_APPROVAL, AgentState.RECOVER, AgentState.STOPPED, AgentState.FAILED},
    AgentState.RETURNING: {AgentState.OBSERVE, AgentState.COMPLETED, AgentState.STOPPED, AgentState.FAILED},
    AgentState.VERIFY: {AgentState.OBSERVE, AgentState.COMPLETED, AgentState.RETURNING, AgentState.STOPPED, AgentState.RECOVER, AgentState.FAILED},
    AgentState.RECOVER: {AgentState.OBSERVE, AgentState.STOPPED, AgentState.FAILED},
    AgentState.COMPLETED: set(),
    AgentState.STOPPED: set(),
    AgentState.FAILED: set(),
}


class StateMachine:
    def __init__(self, initial: AgentState = AgentState.INITIALIZE):
        self.current = initial
        self.history: list[tuple[str, str]] = []

    def transition(self, nxt: AgentState, reason: str = "") -> AgentState:
        if nxt not in ALLOWED.get(self.current, set()):
            raise ValueError(f"Illegal transition {self.current.value} -> {nxt.value} ({reason})")
        log.info("Step finished: %s, now on %s (%s)", self.current.value, nxt.value, reason)
        self.history.append((self.current.value, nxt.value))
        self.current = nxt
        return self.current

    def force(self, nxt: AgentState, reason: str = "") -> AgentState:
        """Forced move to another step (used only for serious errors). Still recorded in the log."""
        log.warning("Jumped from step %s to %s because of a serious problem (%s)", self.current.value, nxt.value, reason)
        self.history.append((self.current.value, nxt.value))
        self.current = nxt
        return self.current
