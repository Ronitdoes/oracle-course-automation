# Implementation Steps (per spec §11)

Phases were executed in order; each phase ended with its tests passing.

## Phase 1 — Environment

- Inspected the empty work folder; confirmed Python 3.13.
- Wrote `requirements.txt` (the list of needed packages: playwright — the
  browser-driving tool — plus pydantic, dotenv, pytest, pytest-asyncio, httpx),
  `.env.example` (a fill-in-the-blank example settings file), `.gitignore` (a
  list of files not to save in version history), and `config.py` (the file
  that reads settings).

## Phase 2 — Browser + practice quiz

- `browser/session.py` (starting the browser + CDP-connect — CDP is the
  standard way to attach to an already-open browser — + graceful close, meaning
  shutting down cleanly without leaving windows behind).
- `tests/fixture/quiz.html`: q1 (multiple-choice), q2 (multiple-choice), q3
  (typing an answer), q4-delayed (1500 ms pause before the next question
  appears), q5 (multiple-choice), a finished screen at the end, and an
  `?only=empty` broken-question variant (a version of the page with a question
  that has no answer options, for testing safe stops). Predictable `data-*`
  IDs (the same hidden labels every run) and `[data-feedback]` signals (the
  page's result messages, such as "Correct!").

## Phase 3 — Reading the page

- `browser/observer.py` produces a `PageSnapshot` (a description of what the
  page currently shows; it looks at announced button/field names first).
- `perception/page_classifier.py` labels the page LOADING (still loading) /
  QUESTION (a question is showing) / FEEDBACK (a result message is showing) /
  COMPLETION (the finished screen) / AMBIGUOUS (unclear — the page could not
  be identified).
- `perception/question_extractor.py` pulls out the question (multiple-choice /
  typing an answer / UNSUPPORTED, meaning a format the tool does not handle by
  design).

## Phase 4 — Answer shapes + answerer interface

- `solver/schemas.py` defines the shared shapes (`Question` = the question,
  `AnswerOption` = one answer choice, `AnswerCandidate` = the proposed
  answer, and similar).
- `solver/base.py` (`BaseSolver`, the common plug-in shape every answerer
  follows, + `validate_candidate`, the check that a proposed answer fits the
  question).

## Phase 5 — AI answerer

- `solver/llm_solver.py`: `MockSolver` (a built-in pretend answerer that works
  offline with no key; `auto` answers the practice quiz, `unresolved` always
  says "I don't know" to test the recovery path) + `OpenAICompatibleSolver`
  and `GeminiSolver` (clients that send the question as JSON — a standard data
  format — to a chat-style AI; they work with OpenAI / Azure / Ollama / vLLM /
  Google Gemini through the `LLM_BASE_URL` address setting).
  `build_solver()` picks which answerer to use based on settings.

## Phase 6 — Step tracker + main loop

- `agent/state_machine.py` (13 step names, an allow-list — the list of which
  step-to-step moves are permitted — and every move written to the log).
- `agent/controller.py` (the full INITIALIZE→…→COMPLETED loop, from starting
  the browser through finishing the quiz).
- `agent/action_planner.py` (checks before acting: practice-mode / human-
  approval / already-submitted blocks).
- `agent/recovery.py` (limited retries — a capped number of re-tries — plus a
  check whether a previous submit already succeeded before trying again).

## Phase 7 — Actions + checking the result

- `browser/executor.py` (finds buttons by meaning — by announced name such as
  "Submit" — waits until they are ready automatically, and saves error
  screenshots to help diagnose failures).
- `verification/verifier.py` (checks several signals: the question ID
  changed / the question wording changed / a result message appeared / the
  finished screen appeared; the submit button merely disappearing is never
  counted as success by itself).

## Phase 8 — Saving history + logging

- `storage/run_store.py` (SQLite — a simple database stored as one file —
  with `runs` + `steps` tables; passwords and keys are never saved).
- `main.py` (command-line options + asking the human for approval + a run
  summary + exit codes, meaning the numbers the program returns to say
  success or failure).

## Phase 9 — Screenshot backup path

- `perception/visual_perception.py` (saves a picture of the visible part of
  the page — the viewport, meaning what is currently on screen; reading that
  picture with AI happens only when an `openai`-compatible, `groq`, or `gemini`
  provider plus its API key — its password for the AI service — is configured;
  otherwise it reports explicitly "unavailable" so the main loop goes to
  RECOVER instead of acting blindly).

## Phase 10 — Test suite

- `test_extractor` (13), `test_solver` (23), `test_state_machine` (10),
  `test_verification` (6), `test_browser_workflow` (10 browser runs),
  `test_apex` (11 runs on pages without hidden labels).
- `pytest.ini` (the test settings file; `asyncio_mode=auto` lets
  waiting-style tests run without extra setup). The suite uses local practice
  pages only — no third-party websites.

## Phase 11 — Docs

- `README.md` (setup/config/architecture/testing/troubleshooting),
  `docs/conventions.md`, `docs/examples.md`, this file.
