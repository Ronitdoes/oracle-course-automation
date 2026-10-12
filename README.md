# Browser Agent

This tool uses Playwright (a tool that controls a web browser automatically) to work through a quiz page. It reads the page's underlying structure (called the DOM — basically the text and buttons as the browser sees them, listed first because that is the main method), picks out the question, asks an AI model (called an LLM — large language model — which you can choose in settings) for the answer, clicks or types the answer by finding buttons and boxes by their visible labels, checks that the page moved to the next question, and repeats until done. If reading the page structure is unclear, it falls back to looking at a screenshot picture of the page.

## Download (Windows, no Python needed)

Get `BrowserAgent-Setup-*.exe` from **[Releases](https://github.com/Ronitdoes/oracle-course-automation/releases/latest)**, run it (per-user install, no admin rights), and launch **Browser Agent** from the Start Menu.

What happens on first launch:

1. A setup wizard asks for your AI key (it shows where to get one) plus basic run settings — saved locally, never uploaded.
2. Press **Open Oracle Academy**, log in, and open your quiz in that browser tab.
3. Press **Start**. The app drives your open tab and works through the course outline (sections and midterm/final exams alike) until everything reaches 100%.

## Quickstart (terminal, from source)

These steps set up and start the tool. Type each line in your terminal (the text window for commands):

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  |  source .venv/bin/activate (macOS/Linux)
pip install -r requirements.txt
playwright install chromium   # downloads the browser driver
copy .env.example .env         # Windows  |  cp .env.example .env
# edit .env: set TARGET_URL (default points at the local fixture)
python main.py
```

What each step does:

- `python -m venv .venv` creates a private folder (called a virtual environment) that holds this project's Python pieces separately from the rest of your computer.
- The `activate` line switches your terminal to use that private folder.
- `pip install -r requirements.txt` downloads the needed helper libraries listed in the `requirements.txt` file (`pip` is Python's installer).
- `playwright install chromium` downloads Chromium (the Chrome-like web browser that Playwright drives automatically; here "driver" just means the browser copy it controls).
- `copy .env.example .env` (Windows) or `cp .env.example .env` (macOS/Linux) makes your settings file (called `.env` — a small text file that holds your settings) from the provided example.
- Editing `.env` to set `TARGET_URL` tells the tool which web page to open (by default this points at the bundled sample quiz page included for practice, called the "fixture").
- `python main.py` starts the tool.

Run against the bundled sample quiz page (the fixture) explicitly:

```bash
python main.py --target-url "file:///D:/projects/Browser-Automation/tests/fixture/quiz.html"
```

## Configuration (.env)

These are the settings inside your `.env` settings file. Each setting is a named value. `Default` is what is used if you leave it blank.

| Var | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `mock` | Which answer source to use: `mock` (built-in pretend answers for offline practice, no internet needed), `gemini` (Google's AI service), `groq` (Groq's OpenAI-compatible API), or `openai` (a standard-compatible AI service) |
| `MODEL_ID` | `mock-model` | The name of the AI model to ask, for the provider above (defaults auto-selected by the setup wizard: `gemini-3.5-flash-lite`, `openai/gpt-oss-120b`, `gpt-4o-mini`) |
| `LLM_API_KEY` | `` | Secret password for the AI service (called an API key) — required for the `gemini`, `groq`, and `openai` providers (the setup wizard asks for it on first launch; Groq keys come from https://console.groq.com/keys) |
| `LLM_API_KEYS` | `` | Extra API keys for automatic failover (comma/semicolon/newline separated) — if one key fails (bad key, spent quota, provider hiccup) the agent switches to the next without breaking the run and sticks to the working key; tried in order, first key first |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Alternate web address to ask for answers, only if you use a different AI host (examples: Microsoft Azure, Ollama for running AI on your own computer, vLLM for hosting AI yourself; Groq defaults to `https://api.groq.com/openai/v1` when `LLM_PROVIDER=groq`) |
| `MOCK_SOLVER_MODE` | `auto` | For practice answers only: `auto` answers the sample page normally; `unresolved` pretends it does not know, to force the backup-fix path (called recovery) for testing |
| `TARGET_URL` | `` | The web page to automate (`file://…` web addresses work for the sample page) |
| `ALLOWED_DOMAINS` | `` | Safety list of allowed websites (comma-separated); empty = no restriction, it may visit any page |
| `HEADLESS` | `true` | Whether the browser window is hidden: `true` runs invisibly in the background; `false` shows the window so you can watch it click (called headed mode, useful for fixing problems) |
| `BROWSER_CONNECTION_MODE` | `launch` | How the tool opens the browser: `launch` (starts a fresh browser itself) or `cdp` (connects to a browser you already started; CDP means Chrome DevTools Protocol — a built-in remote-control connection — and that browser must have been started with the `--remote-debugging-port` flag) |
| `CDP_ENDPOINT` | `http://localhost:9222` | The address of that already-open browser; only used when `BROWSER_CONNECTION_MODE=cdp` |
| `MAX_QUESTIONS` / `MAX_ACTIONS` / `RUN_MAX_DURATION_SEC` | `500/500/300` | Safety stop limits: stop after this many questions, this many clicks/typing steps, or this many seconds |
| `MAX_RETRIES` | `2` | How many times to retry a failed step before giving up |
| `NAVIGATION_TIMEOUT_MS` / `ACTION_TIMEOUT_MS` | `15000/8000` | Longest time to wait for a page to load / for a click to work, in milliseconds (thousandths of a second); the tool waits only as long as needed, never a fixed pause |
| `SCREENSHOT_DIR` / `DATABASE_PATH` | `./artifacts/...` | Where to save problem-solving pictures (screenshots) and history; the folders under `./artifacts/` (the saved-output folder) hold these, and history is kept in SQLite (a simple file-based record-keeper, no separate server needed) |
| `LOG_LEVEL` | `INFO` | How much detail to write to the log file; `DEBUG` gives extra detail useful when the tool cannot find a button |
| `DRY_RUN` | `false` | Practice mode: if `true`, it picks answers but never clicks Submit |
| `REQUIRE_APPROVAL` | `false` | If `true`, it pauses and asks you to press Enter in the terminal (the text window where you started it, via keyboard input called stdin) before each submit |
| `AUTO_ADVANCE_LESSONS` | `false` | If `true`, it also walks course pages by itself: clicks Save and Continue on theory pages, then Take an Assessment and Start to open the quiz. When done with a quiz it stops and reports; it never clicks Previous, Return, or Exit |
| `REDACT_QUESTION_TEXT_IN_LOGS` / `PERSIST_QUESTION_TEXT` | `false/true` | Privacy controls: whether to hide question text from saved logs / whether to save question text in the history file |

Extra options you type after `python main.py` on the command line (called CLI flags — command-line interface flags: `--dry-run`, `--headed`, `--max-questions N`, `--target-url …`, `--require-approval`) change settings for that one run only, overriding the `.env` file.

## Architecture

`main.py` starts the Controller (the main organizer, in `agent/controller.py` plus `state_machine.py` — "state machine" just means a step-by-step checklist that tracks which step it is on):

```
main.py -> Controller (agent/controller.py + state_machine.py)
  OBSERVE  browser/observer.py      -> PageSnapshot (a saved copy of what the page shows right now)
  CLASSIFY perception/page_classifier.py -> PageState (a label for what kind of page this is, e.g. question vs. finished)
  EXTRACT  perception/question_extractor.py -> Question (the question text plus its answer choices)
  SOLVE    solver/llm_solver.py (mock | OpenAI-compatible) -> AnswerCandidate (the AI's suggested answer)
  VALIDATE solver/base.py + agent/action_planner.py -> Action[] (the checked list of clicks/typing steps to do)
  ACT      browser/executor.py (finds buttons by their visible labels and waits for them to be ready automatically)
  VERIFY   verification/verifier.py (checks several clues together — question change, feedback message, finished marker — never the missing-button clue alone)
  RECOVER  agent/recovery.py (limited retries, plus a guard against clicking Submit twice)
  STORE    storage/run_store.py (saves runs and steps in SQLite — a simple file-based record-keeper)
  NAVIGATE agent/action_planner.py -> forward clicks (only used when walking course pages, see below)
```

Loop (the repeating path it follows): `INITIALIZE→OBSERVE→CLASSIFY→EXTRACT→SOLVE→VALIDATE→[AWAIT_APPROVAL→]ACT→VERIFY→OBSERVE…→COMPLETED/STOPPED/FAILED` (in plain words: start up → look at page → label the page → read the question → ask the AI → check the planned clicks → [optionally wait for your approval →] do the clicks/typing → check it worked → look again … until finished, stopped, or failed). On theory/quiz-start pages the path instead goes `CLASSIFY→NAVIGATE→[AWAIT_APPROVAL→]ACT→VERIFY→OBSERVE` (plan a forward click → optionally wait for approval → click → check the new page loaded).

Loop (the repeating path it follows): `INITIALIZE→OBSERVE→CLASSIFY→EXTRACT→SOLVE→VALIDATE→[AWAIT_APPROVAL→]ACT→VERIFY→OBSERVE…→COMPLETED/STOPPED/FAILED` (in plain words: start up → look at page → label the page → read the question → ask the AI → check the planned clicks → [optionally wait for your approval →] do the clicks/typing → check it worked → look again … until finished, stopped, or failed).
Every step change is written to the log. Picture-looking (`perception/visual_perception.py` — screenshot-based backup) only runs when reading the page structure (the DOM) is unclear or gives mixed results.

Safety: allowed-websites list (domain allowlist), practice mode that never submits (dry-run), pause-to-ask-you step before submitting (approval gate), protection against clicking Submit twice (duplicate-submit guard), limits on tries, waiting time, and total steps (bounded retries/timeouts/action budget), quiz text treated as plain reading material and never followed as instructions (webpage text treated as untrusted data), the AI is never allowed to run computer code (no generated-code execution), and if the page asks you to prove you are human or to log in (called CAPTCHA — a human-check puzzle — or auth — login), the tool stops instead of bypassing it (no CAPTCHA/auth bypass).

## Walking a whole course (theory pages → quiz)

With `AUTO_ADVANCE_LESSONS=true` in `.env`, the helper starts from a theory (lesson) page and walks forward by itself:

1. On the course outline it opens the first section that is not at 100% (a missing number counts as unfinished too) — sections and exams alike (midterm, final, cumulative). If everything is finished it stops and tells you.
2. On reading pages it clicks **Save and Continue** (or Save Progress).
3. On the quiz card page it clicks **Take an Assessment**, then **Start** in the pop-up box.
4. Then it answers questions exactly as in questions-only mode.
5. When the quiz is done and the course sends it back to the quiz card, it leaves via **Save Progress** (never starting the same quiz twice) and goes back to the outline for the next unfinished section, until no sections remain. Finished sections are remembered in the history file — even if the outline still shows one open — so it never redoes a finished section. If that ever blocks something it shouldn't, `REDO_FINISHED_SECTIONS=true` turns the memory off.

## Walking all My Classes (home → hub → every course)

Still with `AUTO_ADVANCE_LESSONS=true`, start at the Oracle Academy landing page (or the My Classes hub) and the helper walks every course in turn:

1. On the home page (`My Student Benefits`) it clicks **My Classes** (`View course materials assigned by a faculty member`).
2. On the **My Classes** hub it clicks the first **Take Class** whose course title is not yet recorded as fully complete (e.g. `Database Programming with SQL – English`, then `Database Programming with PLSQL – English`, `Database Foundations`, `Database Design`). Identical buttons are told apart by card order (`occurrence`), and the card title is read from the button's own card so finished courses are skipped by normalized title across runs.
3. Inside each course it does the whole-course walk above (all sections, midterms, final and cumulative exams). When that outline shows 100% everywhere, the course title is recorded in the history file (`finished_courses`) and the helper goes back to the hub for the next unfinished **Take Class**, until the hub reports `no unfinished class found`.
4. Starting directly on one outline keeps the old single-course behaviour (no hub needed).

Rules that keep this safe: it only ever clicks forward buttons — Previous, Return to Course/Exit, and Course are never clicked. If it ever returns to a page it already walked, it stops instead of looping. In preview mode (`DRY_RUN=true`) it lists the planned clicks without clicking; with `REQUIRE_APPROVAL=true` it asks you before each set of clicks. Without the setting (default), it stops on the first theory/quiz-start page and tells you to turn it on.

## Desktop app (Windows)

Run / History / Settings pages. Approvals appear as dialogs instead of
terminal prompts. Settings edits `.env` locally; keys are never logged.
The **Setup** button on the Run page re-opens the first-run wizard anytime.

Prefer to run from source instead of the installer?

```bash
pip install -r requirements.txt
python -m app.main
```

Prefer to build the installer yourself?

```bat
build_installer.bat
```

This builds the portable exe (`dist\BrowserAgent\BrowserAgent.exe`, also
buildable alone via `build_exe.bat`) and then the real installer
(`dist-installer\BrowserAgent-Setup-*.exe`, needs the free Inno Setup once).
The installer is per-user (no admin rights), adds a Start Menu entry with an
optional desktop icon, and registers an uninstaller. First run copies
`.env.example` to `.env` by itself and opens a setup wizard that asks for
your AI key (with a link to where you get one) plus the basic run settings;
your settings are never overwritten by reinstalls. Normal use drives your
own Chrome (no browser download needed);
if launch-mode ever needs Chromium, the app's Install button fetches it into
your own profile folder.

## Testing

Automatic checks are run with `pytest` (the automatic test runner; `-q` means quiet/short output):

```bash
pytest -q            # full suite (unit + local-fixture integration)
pytest -q tests/test_extractor.py tests/test_solver.py   # fast unit subset
```

Here "full suite" means all automatic checks: small single-piece checks (called unit tests) plus a full run against the local sample page (called integration). The "fast unit subset" checks just two small pieces (question-reading and answer-picking).

The sample page (fixture — the bundled practice quiz at `tests/fixture/quiz.html`) has 5 questions (3 multiple-choice, 1 type-in-the-answer (text-entry), 1 where the next question waits 1.5 seconds before appearing (1500 ms delayed transition — ms means milliseconds, or thousandths of a second)), a test address ending in `?only=empty` that shows a question with no answer choices (the empty-options case), built-in hidden markers that say "right/wrong" and "quiz finished" (explicit `[data-feedback]` + `[data-completion]` signals — small labeled markers in the page), and fixed ID numbers for each question so tests can recognize them (predictable `data-question-id` values). Tests never visit real websites (no third-party sites are used).

## Troubleshooting

| What you see (symptom) | What to do (fix) |
|---|---|
| `TARGET_URL is not set` | Copy `.env.example` to `.env` (your settings file), then set `TARGET_URL` inside it |
| `playwright: Executable doesn't exist` | The automated browser is not downloaded yet — in the desktop app press **Install now**, or run `playwright install chromium` |
| `Unknown LLM_PROVIDER` | Use `mock` (built-in practice answers), `gemini` (Google's AI service), `groq` (Groq's API), or `openai` (standard AI service) |
| `LLM_API_KEY is not set` | Put your AI-service secret password (API key) in `.env`, or stay on `mock` (no key needed) |
| Stuck on `RECOVER` | It is stuck on its backup-fix step — look at the saved pictures in `artifacts/screenshots` (the saved-output folder), and turn on detailed logging with `LOG_LEVEL=DEBUG` |
| `STOPPED … unsupported` | The page has a format the question-reader marks `UNSUPPORTED` (meaning "not supported") — this is on purpose (by design) |

## Limitations

- Only multiple-choice (choice) and typed-answer (text-entry) questions work; dragging items or drawing on the page (drag-drop/canvas) is marked as not supported (`UNSUPPORTED`) and skipped.
- To know it moved on, the tool needs a visible clue (called an observable signal): the question number changes (question-id change), a right/wrong message appears (feedback), or a finished message shows (completion marker); otherwise it reports `UNCERTAIN` (meaning "not sure").
- The screenshot-picture backup (vision fallback) saves pictures but needs a standard-AI-service key (`openai`-provider key) to understand pictures.
- Connecting to an already-open browser (called CDP attach — CDP means Chrome DevTools Protocol, a built-in remote-control connection) only works if that Chrome-like browser (Chromium) was started with the special remote-control flag `--remote-debugging-port`; a normal Chrome window you opened yourself cannot be taken over.

Example run outputs (logs) are in `docs/examples.md`. Shared rules (conventions) are in `docs/conventions.md`.
