# Conventions (rules for changing the code)

## Python

- Python 3.12 or newer; `asyncio` (Python's built-in system for waiting on slow
  tasks without freezing) is used in all browser code. No threads (parallel
  workers) for page work.
- Type hints (small labels saying what kind of data a function expects and
  returns) on all public functions. Pydantic v2 (a helper that checks data has
  the expected shape) for data passed between parts (`Question` = the question,
  `AnswerCandidate` = the proposed answer, `PageSnapshot` = a description of
  what the page currently shows).
- Imports ordered: built-in Python tools (standard library) → third-party
  (downloaded packages) → local project files. One module (one code file) has
  one job.

## Browser interaction (how the tool reads and clicks the page)

- DOM-first. DOM means the page's built-in structure and labels (as opposed to
  looking at a screenshot picture of the page). Prefer
  `page.get_by_role(...)` / `get_by_label` (finding a button by its announced
  name, for example "Submit") over CSS (finding things by style-sheet codes).
- `data-question-id`, `data-question-text`, `data-option-id`, `data-submit`,
  `data-feedback`, `data-completion`, `data-answer-input` are hidden labels
  built into the practice page. They are the stable agreement between the
  practice quiz (the built-in test page in `tests/fixture/`) and the agent;
  real-world pages use the same labels when present, otherwise the agent falls
  back to finding things by their announced role and name (for example, "a
  button named Submit").
- Never use `time.sleep` (a fixed pause) as the waiting plan: use Playwright
  (the browser-driving tool) auto-waiting (it waits by itself until the button
  is ready), `locator.wait_for` (wait for one specific page item — a locator
  is just a saved description of how to find that item), and bounded
  `wait_for_timeout` short checks + re-observation (short waits with a limit, then
  look at the page again).
- Every action returns `ActionResult` (a small report saying whether the
  click or typing worked); clicking ≠ success — `VERIFY` (the later checking
  step) decides whether we really moved forward.
- Re-resolve locators after each navigation (each time a new page or question
  loads, find the buttons again from scratch); never cache element handles
  (never keep saved references to buttons that may now be gone).

## State machine (the step-by-step tracker)

- States (step names) in `agent/state_machine.py` are the only allowed
  vocabulary (the only step names the program may use).
- All transitions (moves from one step to another) go via
  `sm.transition(...)`, and each move is written to the log. `force()` (a jump
  that skips the allowed-list check) is for crashes (fatal errors) only.
- `CLASSIFY` never jumps directly to `OBSERVE` — route via `RECOVER` (go
  through the recovery step in between).

## Safety

- Webpage text is untrusted data (treat words on the page as possibly
  misleading data, never as instructions; the solver's system prompt — the
  hidden instruction given to the AI answerer — says this explicitly).
- No `eval` (running text as if it were code), no running code the AI makes
  up, no JS injection (no JavaScript built out of page content put into the
  page).
- Submits (clicks that send an answer) are blocked unless all checks pass:
  `dry_run` (practice mode: proposes answers but never clicks submit),
  `require_approval` (asks the human before each submit), `allowed_domains`
  (the list of websites the tool may visit; empty means no restriction),
  duplicate-submit set (a memory of questions already submitted, so none is
  sent twice), and global budgets (overall limits:
  `max_questions`/`max_actions`/time).

## Config & secrets

- Settings come only from environment settings (values read from the
  environment; `config.py` reads them and `.env` — a local settings file in
  the project folder — holds them). `.env.example` is a fill-in-the-blank
  example with placeholders (empty sample values).
- Never write API keys (passwords for the AI service), cookies, or credentials
  (logins) to the log. `RunStore` (the part in `storage/run_store.py` that
  saves run history into SQLite — a simple database stored as one file)
  stores answers and (optionally) question text — never secret keys. Use
  `REDACT_QUESTION_TEXT_IN_LOGS` (hide question words in log output) and
  `PERSIST_QUESTION_TEXT=false` (do not save question words in the history
  file) for sensitive deployments (privacy-sensitive setups).

## Tests

- Unit tests (small checks of one part) use a fake answerer (they mock the
  solver — a pretend AI with fixed answers); integration tests (full runs
  through the browser) use only the built-in practice quiz in
  `tests/fixture/`.
- `pytest.ini` (the test settings file) sets `asyncio_mode = auto` (lets
  waiting-style tests run without extra setup); browser tests are `async def`
  (written in the waiting style).
- Keep the fixture (the practice quiz) deterministic (behaves exactly the same
  on every run): fixed IDs (the same question labels each time), explicit
  feedback (clear result messages), no randomness.
