# Browser Agent

Browser Agent is a Windows app that works through your Oracle Academy courses for you. It opens your classes, answers the quiz questions with AI, and keeps going until each course reaches 100%.

## Install

1. Download `BrowserAgent-Setup-1.0.0.exe` from **[Releases](https://github.com/Ronitdoes/oracle-course-automation/releases/latest)**.
2. Run it. It installs for your user only (no admin rights needed).
3. Open **Browser Agent** from the Start Menu.

## Windows says this app is unsafe?

You may see a blue SmartScreen box saying Windows protected your PC. This is normal for a small independent app. It appears because the app is **unsigned** (no paid publisher certificate yet) — not because anything was found wrong with it.

To install anyway:

1. Click **More info**.
2. Click **Run anyway**.

The file properties now show the real publisher name (Browser Agent, v1.0.0). A paid code-signing certificate is the only thing that removes this warning completely — planned for a later release.

## First-time setup

When you first open the app, a setup window asks for two things:

1. **Provider** — pick `gemini`, `groq`, or `openai`. The app fills in the model by itself.
2. **API key** — paste your key. The window tells you where to get one:
   - Gemini: https://aistudio.google.com/apikey
   - Groq: https://console.groq.com/keys
   - OpenAI: https://platform.openai.com/api-keys

You can also add **backup keys** (comma-separated). If one key stops working, the app switches to the next one by itself and keeps going.

Your keys stay on your computer. They are never uploaded anywhere.

## How to run

1. Press **Open Oracle Academy** in the app (or open Chrome yourself). Log in.
2. Open **My Classes**, or any course page, and keep that tab in front.
3. Press **Start**.

The app will:

- Open each course with **Take Class**, starting with the first unfinished one.
- Work through every section, midterm, and final exam.
- Click **Finish Assessment** where needed.
- Go back to My Classes and move to the next course.
- Stop when every course shows 100%.

Just leave the browser window open while it works. Press **Stop** anytime to pause it.

## The three pages

- **Run** — start/stop, watch each step, and read the log. Tick boxes: Dry run (practice without clicking), Show browser, Require approval, Auto-advance lessons/courses.
- **History** — see your past runs and every step they took.
- **Settings** — change your key, provider, or limits anytime. Press **Save**.

## If something goes wrong

| What you see | What to do |
|---|---|
| App can't find your browser | Press **Open Oracle Academy** so the app opens its own browser tab, then press Start. |
| Says your key is missing | Open Settings and paste your API key, then Save. |
| It stops on a question it can't read | That question type isn't supported — answer it by hand in the browser, then press Start again. |
| It says it already did a section | It remembers finished work so it never repeats itself. To redo on purpose, tick Redo finished sections in Settings. |

To uninstall, use Windows Settings → Apps, like any other app. Your settings are kept separately and never deleted by reinstalls.
