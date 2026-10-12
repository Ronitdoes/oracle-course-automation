# Architecture

Terms used once up front: Playwright (the tool that drives the browser),
Chromium (the browser it drives), DOM (the page's built-in structure and
labels, as opposed to a screenshot picture), LLM (the AI that proposes
answers), API key (the password for the AI service), SQLite (a simple database
stored as one file).

## Data flow

```
                        ┌─────────────┐
                        │   Target    │
                        │    Page     │
                        └──────┬──────┘
                               │ Playwright
                ┌───────────────▼────────────────┐
                │ BrowserSession (start fresh /  │
                │ CDP = attach to open browser)  │
                └───────────────┬────────────────┘
                                ▼
┌──────────────────────────────────────────────────────┐
│ Main loop (Controller)                               │
│                                                      │
│  OBSERVE  observer.observe() → PageSnapshot          │
│           (a description of what the page shows)      │
│  CLASSIFY page_classifier.classify() → PageState     │
│           (a label: loading / question / result /    │
│            finished / unclear)                        │
│  EXTRACT  question_extractor.extract() → Question    │
│           (the question + its answer choices)         │
│  SOLVE    build_solver().solve() → AnswerCandidate   │
│           (the AI's proposed answer)                  │
│  VALIDATE validate_candidate() + action_planner.plan │
│           (check the answer fits + is allowed)        │
│  [AWAIT_APPROVAL if REQUIRE_APPROVAL]                │
│           (pause for a human yes/no when required)    │
│  ACT      executor.execute() → ActionResult          │
│           (click/type; report whether it worked)      │
│  VERIFY   verifier.verify(before, after) → Verdict   │
│           (compare the page before/after; decide:    │
│            moved on / finished / result shown /      │
│            no change / unclear)                       │
│  RECOVER  recovery.should_retry() (capped re-tries)  │
│  Saving   run_store.log_step() records each main     │
│           step into the history file (not a step     │
│           itself — it runs alongside the steps above)│
└──────────────────────────────────────────────────────┘
```

The full list of step names (INITIALIZE, OBSERVE, CLASSIFY, EXTRACT, SOLVE,
VALIDATE, AWAIT_APPROVAL, ACT, VERIFY, RECOVER, COMPLETED, STOPPED, FAILED)
lives in `agent/state_machine.py`.

## Why read the page structure first (DOM-first)

Raw page code (HTML) is messy and sending all of it to the AI is costly;
announced names (accessible roles, such as "a button named Submit") and the
`data-*` hidden labels give steady, meaningful anchors (stable places to
find). The readable page text (`visible_text`) is cut off after 8000
characters, and only the pulled-out `Question` (not the whole page) is sent to
the AI. Screenshots (saved pictures of the page) are taken when the page is
unclear (the AMBIGUOUS label) and also when a click or check fails, to help
diagnose what went wrong.

## Key rules the design keeps

1. Clicking ≠ success. Only the checker's decisions (`VERIFIER` verdicts —
   `ADVANCED`, meaning the next question appeared, or `COMPLETED`, meaning the
   finished screen appeared — based on the question ID changing, the wording
   changing, or the finished marker appearing) count as progress.
2. No endless loops: `max_retries` (cap on re-tries per problem),
   `max_questions` (cap on questions per run), and `max_actions` (cap on
   clicks/typings per run, 0 = unlimited / infinite; total-seconds cap
   `run_max_duration_sec` of 0 means unlimited); when the retry allowance runs
   out, the loop moves from RECOVER to STOPPED (stops and asks for a human).
3. No double submit (no sending the same answer twice): a `submitted_ids`
   memory (the list of already-submitted question IDs) plus a fresh check of
   the page just before submitting.
4. No blind continuation (never guessing onward when lost): an unclear page
   (AMBIGUOUS), a bad answer, or an unsupported format sends the loop to
   RECOVER (try again safely) or STOPPED (stop for a human).

## Limitations (honest)

- Multiple-choice + typing answers only; anything else is `UNSUPPORTED`
  (a format the tool refuses by design) and stops safely.
- Pages that show no visible change after submitting give `UNCERTAIN` (an
  unclear result, reported honestly — the tool does not pretend it worked).
- The screenshot backup path needs a picture-capable AI address
  (an `openai`-compatible, `groq`, or `gemini` provider) plus its key configured.
- Attaching to an already-open browser (CDP attach) needs Chromium started
  with the `--remote-debugging-port` flag (a start-up option that opens the
  remote-control port); an ordinary browser window without that flag cannot be
  adopted.
- The pretend answerer (mock solver) is fixed and predictable (it picks the
  known or first option) — fine for the practice quiz, not a general quiz AI.
