---
name: build-tracker
description: Live HTML progress page for multi-step work - current task with elapsed time, done tasks with durations, to-do tasks with estimates, overall ETA, updating in real time. Use when the user says "set up the build tracker", "track progress of this work", "show me task progress", or asks for a progress page/dashboard for the work you are doing.
---

# Build tracker

A local page (`http://127.0.0.1:<port>/`) polls `state.json` every 2s. You keep the state current with
`tracker.py`; the script stamps all times, so never edit `state.json` by hand.

`tracker.py` sits in this skill's base directory (shown when the skill loads). Call it by full path,
written here as `$T`, e.g. `<base dir>/tracker.py next`. It needs `python3`. Run `$T --help` for every command.

## Set up

1. Break the work into 3-15 concrete tasks in execution order. Give each a rough estimate in minutes
   with `name:minutes` when you can; the page calibrates estimates against actual pace.
2. `$T init "<short title of the work>" "Task one:5" "Task two:10" ...` - starts the server and opens the browser.
   Default state dir is `~/.build-tracker/<cwd folder name>`; pass `--dir` for a second tracker in the same folder.
3. Tell the user the URL it printed.
4. `$T start` immediately, then do the work.

## While working

- Finish a task and begin the next: `$T next` (add `--note "..."` for a one-line result).
- Status line under the current task when a step is long: `$T note "running gradle tests"`.
- New work discovered: `$T add "Task" --est 5`. Dropped work: `$T skip <id> --note "why"`.
- Update the tracker at each task boundary, before moving on - a stale page is worse than none.
- All done: `$T finish`.

Lost the URL or the page says "offline": `$T url` restarts the server if needed.
