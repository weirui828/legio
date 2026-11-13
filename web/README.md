# Camp Legio — the dashboard

A local, read-only webapp for legio's centuriae, with two skins over the same
server and data:

- **Principia** (the default, `/principia/`): one dense page with three panels.
  Projects on the left; in the middle every job of the selected project on a
  progress track with its scroll underneath; on the right what needs you, who
  is at work and Legatus.
- **The camp** (the original, `/`): drawn as a Roman camp. One tent per
  project; inside a tent, the **TABULA OPERUM** board with its jobs and the
  role that is working right now.

Everything is generated art, nothing is fetched from the network, and neither
skin ever writes to a project.

```bash
python3 web/serve.py            # http://127.0.0.1:8766 — the real camp
python3 web/serve.py --demo     # a fake camp (four projects), for design work
python3 web/serve.py --port 9000 --root ~/dev
python3 web/serve.py --no-legatus             # without the agent panel
python3 web/serve.py --no-actions             # no buttons that change anything
python3 web/serve.py --legatus-model claude-sonnet-5-5
```

Stop with Ctrl-C. There is no build step and no dependency: Python's standard
library serves the page and shells out to `centuria view` for the data.

## Principia (the default skin)

Opening `/` sends you to `/principia/` unless you chose the camp. Switch in
Principia's settings (the gear, top right) or from the camp's HELP panel; the
choice is kept in the browser (`localStorage["legio-skin"]`), and
`/?skin=camp` always opens the camp.

- **Left:** every stationed project as a tent with its numeral, counts and a
  waiting / active / done bar. Under it, *Terra incognita*: git repositories
  under the projects root without a centuria. Clicking one opens a confirm
  step that stations it (`legio add <path> --host <host>`). The step starts
  on the default host from Settings.
- **Middle:** the selected project's open jobs, one row each, on a progress
  track across the stages (intake → merged) with the role at work, the round
  bars and what is happening now; finished jobs below. *Table* switches to a
  flat table. Selecting a job opens its scroll underneath: a
  timeline built from its files (intake decision, spec, each round's gate and
  reviews, feedback, decision) next to a reader for each file.
- **Right:** *Nuntii*, every job across all projects that waits on you, with
  the command to run; *At work*, the running roles with timers and the working
  character at the desk; *Legatus*, your agent (see below), who also reports
  what changed while the page is open.
- **Settings:** interface (Principia / camp), progress track (*Aqueduct*:
  water flows as far as the job has got, a crack marks a failed gate, a sluice
  means it waits on you; *Road*: milestones I–VI and the golden milestone;
  *Plain*), density, Latin or English labels, animations, the desk scene,
  costs, finished jobs, and the default host for stationing (with what each
  host is). Saved per browser.

Three things can be **done** from the page, each after a confirm step that
shows the exact command: station a repo, send feedback to a job that needs
you, reject a waiting job (see *Actions* below). Everything else, merging
included, is a **copied command** (`gh pr merge 9`) for you to run.
Legatus's suggested commands get a **Run…** button when they are one of
those three; it opens the same confirm step.
Keys: `⌘K` filter, `j`/`k` move between jobs, `v` Via/Table, `Esc` closes
settings. Deep links: `#/legion/<name>` and `#/legion/<name>/job/<id>`.

## What you see

**CASTRA — the camp.** One illustrated scene, one tent per project. The banner
over a tent is `LEGIO <n> · <project>` plus counts (`active / waiting / done`);
a project whose `centuria view` failed gets the warped tent and a red "cannot
read" tag instead of pretending to be healthy. The top row is the nav:
CASTRA (the camp), MILITES (this project's cast — only inside a tent),
LEGIONES (every project), NUNTII (what waits on you). Top right: the operator,
the recorded cost in denarii, and a STATUS meter for "how many projects read
cleanly". Bottom left: notifications. Bottom right: HELP.

**A tent.** Cream canvas, a wooden floor and the **TABULA OPERUM**:
`AD FACIENDUM` (waiting on a human), `IN CURSU` (being worked), `FACTUM`
(finished — merged or rejected). One pinned note per job, and the note carries
the **cast faces** of that job: the role of the current stage, the reviewers
from its roster and whoever reviewed it — a green or red ring is their verdict,
a brass ring means that role is working on it right now (hover a face for its
title and duty). The right side is the
desk: if a role is working right now, that role's chibi sits there with the job
name in a bubble, warm glow and floating hearts. If nobody is working, the desk
is empty and says so. The strip at the bottom is the cast; the on-duty role is
lit.

**MILITES.** The eight roles with their name, function, tier and the duty line
from their role file; the one on duty is ringed in brass.

Notes are clickable: a wide job panel opens with the stage, round, gate, PR,
cost, what waits on a human and the review verdicts, and it has a deep link
(`#/legion/<name>/job/<id>`). From there, **read the scrolls** opens
(`#/legion/<name>/job/<id>/scrolls`): the job's issue, intake, spec, build,
gate checks, every review and the agent logs, side by side in a reading pane. The cast chips are clickable (role duty), and
`M` / `L` / `N` / `Esc` open the cast, the legions, the waiting list and close a
panel. If a lane holds more notes than fit, it scrolls and grows a `+N more`
pill that opens the whole lane in the same wide panel. Both panels are drawn
from the same CSS parchment palette — no extra art is needed for them.

## Scrolls (the job's own files)

The scrolls page reads the job folder under `.centuria/jobs/<id>/`, but only a
whitelist: `issue.md`, `intake.md`, `spec.md`, `build.md`, `decision.md`,
`rejection.md`, `feedback-*.md`, `round-*/checks.md`, `round-*/review-*.md` and
`agent-*-*.log`. `job.json` and anything else are not exposed. Markdown is
capped at 96 KB, a log comes back as its last 64 KB (flagged as truncated); the
whole thing is a plain `textContent` render, never HTML.

There are two read-only endpoints behind it: `GET /api/job?project=&job=`
(listing) and `GET /api/job/file?project=&job=&path=` (one file). Both refuse
anything outside the whitelist and anything that resolves outside the job
folder, and `--demo` serves a small synthetic set.

## Legatus (the agent)

Legatus is Claude Code running on **your own login** (`claude -p`), with
**Opus 5.5** by default (`claude-opus-5-5`; set `legatus.model` in the repo's
`config.json` or pass `--legatus-model`). Ask him about the camp from the right
panel or, with the panel folded, from his face on the rail.

- **One ongoing conversation.** The first question starts a Claude Code
  session; later ones `--resume` it, so he remembers what you discussed. Your
  usual Claude settings, `CLAUDE.md` files and memory load as in any session.
  *New conversation* (the ↺ button, click twice) starts over.
- **Read-only tools.** He runs in the legio checkout with `--add-dir <projects
  root>` and may only read files and run look-only commands (`./legio status`,
  `inbox`, `ls`, `hosts`, `next`, `doctor`, `git log/status/diff/show`,
  `gh pr|issue view/list`). `Write`, `Edit` and everything else are refused.
  When something needs doing he gives you the exact command in a code block
  with a Copy button; legio still never merges on its own.
- **Context.** Each question carries a line saying which project and job you
  are looking at, so "this job" works.
- **His brief** is `web/legatus.md` (appended to Claude Code's system prompt).
- **State.** The conversation id and transcript live in `.legatus/` in the
  legio checkout (git-ignored). Nothing is written to any project.
- **Off** with `--no-legatus`, in `--demo` (he would read your real
  projects), or when `claude` is not on `PATH`; the panel then says why.

The endpoints only answer this page: `POST /api/legatus/ask` and
`/api/legatus/reset` need a JSON body, a per-start token (handed out by
`GET /api/legatus`, which other sites cannot read) and, when the browser sends
one, an `Origin` equal to this server. One question runs at a time (409 while
busy); answers can take a few minutes (600 s limit).

## Actions (confirmed, run by the CLI)

| action | from | runs | allowed when |
|---|---|---|---|
| station | *Terra incognita* | `./legio add <path> --host <host>` (cwd: legio) | the path is one the server listed as uncharted; the host is in `hosts/` and is not `fake` |
| feedback | job header, Legatus | `.centuria/bin/job feedback <id>` with the text on stdin (what `legio say` runs) | the job is `needs-human` |
| reject | job header, Legatus | `.centuria/bin/job reject <id>` with the reason on stdin (what `legio reject` runs) | the job is `needs-info` or `needs-human` |

The page never edits a project itself: the pipeline's own guards still
apply, and the text goes on stdin so nothing in it can be read as an option.
Merging is never an action. `POST /api/action` takes the same guard as
Legatus (JSON, the per-start token, a matching `Origin`), one at a time, 120 s
limit, and returns `{ok, code, command, output}` (last 40 lines). Off in
`--demo` and with `--no-actions`. `GET /api/actions` lists the hosts.

## Who may talk to the server

Every request must be addressed to `127.0.0.1`, `localhost` or `[::1]` (the
`Host` header), or it gets 403. That stops DNS rebinding, where a hostile site
points its own name at your machine to read the dashboard. Every POST also
needs JSON, the per-start token (from `GET /api/actions` or `/api/legatus`,
which other sites cannot read) and, when the browser sends one, an `Origin`
equal to this server.

## Data (read-only, by construction)

`serve.py` discovers `*/​.centuria/config.json` under `projects_root` (from
legio's `config.json`, or `--root`), then for each project:

- runs `.centuria/bin/centuria view` (5s timeout) and keep only
  `id, issue, title, stage, round, round_limit, pr, gate, reviews, roster,
  cost_usd, active, waiting, terminal, human_reason` — no worktree paths,
  prompts, logs, config or secrets reach the browser;
- reads every `.centuria/jobs/*/live.json` for "who is at the desk" (concurrency
  can be more than one, so several jobs can be working at once);
- parses `.centuria/roles/*.md` (frontmatter + first blockquote) for the cast.

`GET /api/camp` also lists `uncharted`: `{name, path}` of git repositories
under the root that have no centuria (nothing inside them is read). With the
two scroll endpoints above, Legatus's three and the two action ones, these
are the only routes; every other method is 405. The only POSTs are Legatus's
and `/api/action`; the only processes besides `centuria view` are his
`claude -p` and the confirmed action commands.

### The heartbeat

`centuria/bin/run` writes `.centuria/jobs/<id>/live.json` immediately before it
spawns an agent and deletes it when the agent exits:

```json
{"roles": ["fabri"], "round": 1, "started": "2026-11-03T18:00:00Z", "pid": 12345}
```

Parallel reviewers list several roles, and **two jobs can run at the same time**
(concurrency 2): each job writes its own `live.json`, so the tent shows the
freshest one at the desk, a small "also at work" panel for the rest, a working
pip on every note whose job is running, and a live dot on the camp banner. The
cast strip and MILITES light up every role that is on duty. The dashboard polls
every 2.5s; a `live.json` older than 10 minutes (a killed process) is shown as
"last seen", never as live.

## Layout

```
web/
├── serve.py                 stdlib server: static files + the read-only API
├── principia/               the default skin: index.html, app.js, styles.css
├── legatus.md               Legatus's brief (appended to Claude Code's system prompt)
├── index.html               the camp's shell (sends you to principia/ by default)
├── app.js                   routing, rendering, polling (no framework)
├── styles.css               the palette and every shape
├── assets/                  generated WebP + manifest.json, committed
├── tools/prepare_assets.py  trims / cuts out / slices the raw art (dev only)
└── tests/test_camp.py       stdlib tests: payload, HTTP, assets, read-only
```

## Assets

`web/assets/` is committed: 51 WebP files plus `manifest.json`, about 1.9 MB
total. They are generated from the raw PNGs in `design/prototypes/ui/assets-src/` (local,
not committed, about 50 MB) with:

```bash
python3 web/tools/prepare_assets.py      # needs Pillow + numpy
```

That script trims transparent padding, cuts the flat-white backgrounds out of
the desk/soldier/icon sheets (with a soft, de-fringed edge — no white halo),
slices the sheets, resizes each sprite to 2x its CSS size and writes the
manifest. The art direction (and the prompts that made
it) is in `design/prototypes/ui/assets.md`; the two style references are in
`design/prototypes/ui/reference/`. Both are local. Missing assets are not faked: the app simply renders
broken images, so commit the output of the script when it changes.

## Tests

```bash
python3 -m unittest discover -s web/tests -v      # 35 tests, no network (fakes: tests/fake_claude.py, tests/fake_cli.py)
python3 -m unittest tests.test_live_heartbeat -v  # the runner's heartbeat
```

The web tests build throwaway projects with a fake `centuria view` and check the
allowlist, error handling, discovery, the demo camp, static files, 405s, path
traversal and that every manifest file exists. The heartbeat test loads
`centuria/bin/run` and checks that `live.json` is written and removed (and that a
missing job folder is harmless).

## Screenshots

`docs/camp.jpg`, `docs/tent.jpg`, `docs/cast.jpg`, `docs/quiet.jpg`,
`docs/job.jpg` and `docs/scrolls.jpg` were taken from `--demo` mode at 1440x900.
