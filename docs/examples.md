# Example logs

How to read these: each `STATE X -> Y` line means the tool moved from step X
to step Y (the step names are INITIALIZE, OBSERVE, CLASSIFY, EXTRACT, SOLVE,
VALIDATE, AWAIT_APPROVAL, ACT, VERIFY, RECOVER, COMPLETED, STOPPED, FAILED).
`q=q1` is the current question ID. Log lines below are the program's real
output and are kept word-for-word.

Terms used once up front: mock solver (the built-in pretend answerer that
works offline with fixed answers), fixture (the built-in practice quiz page in
`tests/fixture/quiz.html`), SQLite (a simple database stored as one file).

## Successful run (pretend answerer on the local practice page)

```
2026-10-11 10:00:01 INFO browser-agent: STATE INITIALIZE -> OBSERVE | browser ready
2026-10-11 10:00:01 INFO agent.controller: [OBSERVE] q=q1
2026-10-11 10:00:01 INFO browser-agent: STATE OBSERVE -> CLASSIFY | url=file:///.../quiz.html
2026-10-11 10:00:01 INFO browser-agent: STATE CLASSIFY -> EXTRACT | question present
2026-10-11 10:00:01 INFO agent.controller: [EXTRACT] q=q1 3 options
2026-10-11 10:00:01 INFO browser-agent: STATE EXTRACT -> SOLVE | qid=q1
2026-10-11 10:00:01 INFO agent.controller: [SOLVE] q=q1 option=b text=None status=answered
2026-10-11 10:00:01 INFO browser-agent: STATE SOLVE -> VALIDATE | candidate received
2026-10-11 10:00:01 INFO browser-agent: STATE VALIDATE -> ACT | answer valid + authorized
2026-10-11 10:00:01 INFO agent.controller: [ACT] q=q1 select_option:b
2026-10-11 10:00:01 INFO agent.controller: [ACT] q=q1 click_button:Submit
2026-10-11 10:00:02 INFO browser-agent: STATE ACT -> VERIFY | actions executed
2026-10-11 10:00:02 INFO agent.controller: [VERIFY] q=q1 advanced: question id q1 -> q2
... (q2, q3-text, q4-delayed, q5 repeat) ...
2026-10-11 10:00:12 INFO agent.controller: [VERIFY] q=q5 completed: completion screen detected
2026-10-11 10:00:12 INFO browser-agent: STATE VERIFY -> COMPLETED | completed: completion screen detected

Final state: COMPLETED
Questions done: 5
Model calls: 5
```

`Model calls` means how many times the AI answerer was asked (once per
question here).

## Failed answer + safe recovery (answerer forced to say "I don't know")

Run with the setting `MOCK_SOLVER_MODE=unresolved` (this tells the pretend
answerer to always answer "unresolved", meaning "I don't know") before
starting (`python main.py`):

```
MOCK_SOLVER_MODE=unresolved python main.py

2026-10-11 10:05:01 INFO agent.controller: [EXTRACT] q=q1 3 options
2026-10-11 10:05:01 INFO agent.controller: [SOLVE] q=q1 option=None text=None status=unresolved
2026-10-11 10:05:01 INFO browser-agent: STATE SOLVE -> VALIDATE | candidate received
2026-10-11 10:05:01 WARNING agent.controller: [VALIDATE] q=q1 err=solver returned unresolved
2026-10-11 10:05:01 INFO browser-agent: STATE VALIDATE -> RECOVER | invalid answer: solver returned unresolved
2026-10-11 10:05:01 INFO agent.recovery: Retry 1/2 for 'generic': recover
2026-10-11 10:05:01 INFO browser-agent: STATE RECOVER -> OBSERVE | safe retry
2026-10-11 10:05:02 WARNING agent.controller: [VALIDATE] q=q1 err=solver returned unresolved
2026-10-11 10:05:02 INFO agent.recovery: Retry 2/2 for 'generic': recover
2026-10-11 10:05:02 INFO browser-agent: STATE RECOVER -> OBSERVE | safe retry
2026-10-11 10:05:03 WARNING agent.recovery: Retry budget exhausted for 'generic' (recover)
2026-10-11 10:05:03 INFO browser-agent: STATE RECOVER -> STOPPED | recovery exhausted; human needed

Final state: STOPPED
Questions done: 0
```

`Retry 1/2` means the first of at most 2 re-tries. `Retry budget exhausted`
means the capped number of re-tries ran out, so the run stops and asks for a
human instead of looping forever.

Note the main loop never submits a guess it cannot defend, never retries
forever, and saves a record of each main step to SQLite (the history file) so
what happened can be reviewed afterwards.
