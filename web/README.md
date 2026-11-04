# Camp Legio — the dashboard

A local, read-only webapp for legio's centuriae, drawn as a Roman camp. One tent
per project; inside a tent, the **TABULA OPERUM** board with its jobs and the
role that is working right now. Everything is generated art, nothing is fetched
from the network, and the app never writes to a project.

```bash
python3 web/serve.py            # http://127.0.0.1:8766 — the real camp
python3 web/serve.py --demo     # a fake camp (four projects), for design work
python3 web/serve.py --port 9000 --root ~/dev
```

Stop with Ctrl-C. There is no build step and no dependency: Python's standard
library serves the page and shells out to `centuria view` for the data.

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
(finished — merged or rejected). One pinned note per job. The right side is the
desk: if a role is working right now, that role's chibi sits there with the job
name in a bubble, warm glow and floating hearts. If nobody is working, the desk
is empty and says so. The strip at the bottom is the cast; the on-duty role is
lit.

**MILITES.** The eight roles with their name, function, tier and the duty line
from their role file; the one on duty is ringed in brass.

Notes are clickable (job facts), the cast chips are clickable (role duty), and
`M` / `L` / `N` / `Esc` open the cast, the legions, the waiting list and close a
panel.

## Data (read-only, by construction)

`serve.py` discovers `*/​.centuria/config.json` under `projects_root` (from
legio's `config.json`, or `--root`), then for each project:

- runs `.centuria/bin/centuria view` (5s timeout) and keep only
  `id, issue, title, stage, round, round_limit, pr, gate, reviews, cost_usd,
  active, waiting, terminal, human_reason` — no worktree paths, prompts, logs,
  config or secrets reach the browser;
- reads the newest `.centuria/jobs/*/live.json` for "who is at the desk";
- parses `.centuria/roles/*.md` (frontmatter + first blockquote) for the cast.

`GET /api/camp` is the only endpoint; every other method is 405. There are no
write endpoints and no agent calls.

### The heartbeat

`centuria/bin/run` writes `.centuria/jobs/<id>/live.json` immediately before it
spawns an agent and deletes it when the agent exits:

```json
{"roles": ["fabri"], "round": 1, "started": "2026-11-03T18:00:00Z", "pid": 12345}
```

Parallel reviewers list several roles. The dashboard polls every 2.5s; a
`live.json` older than 10 minutes (a killed process) is shown as "last seen",
never as live.

## Layout

```
web/
├── serve.py                 stdlib server: static files + GET /api/camp
├── index.html               the shell
├── app.js                   routing, rendering, polling (no framework)
├── styles.css               the palette and every shape
├── assets/                  generated WebP + manifest.json, committed
├── tools/prepare_assets.py  trims / cuts out / slices the raw art (dev only)
└── tests/test_camp.py       stdlib tests: payload, HTTP, assets, read-only
```

## Assets

`web/assets/` is committed: 43 WebP files plus `manifest.json`, about 1.8 MB
total. They are generated from the raw PNGs in `docs/ui/assets-src/` (not
committed, about 50 MB) with:

```bash
python3 web/tools/prepare_assets.py      # needs Pillow + numpy
```

That script trims transparent padding, cuts the flat-white backgrounds out of
the desk/soldier/icon sheets, slices the sheets, resizes each sprite to 2x its
CSS size and writes the manifest. The art direction (and the prompts that made
it) lives in `docs/ui/assets.md`; the two style references are in
`docs/ui/reference/`. Missing assets are not faked: the app simply renders
broken images, so commit the output of the script when it changes.

## Tests

```bash
python3 -m unittest discover -s web/tests -v      # 15 tests, no network
python3 -m unittest tests.test_live_heartbeat -v  # the runner's heartbeat
```

The web tests build throwaway projects with a fake `centuria view` and check the
allowlist, error handling, discovery, the demo camp, static files, 405s, path
traversal and that every manifest file exists. The heartbeat test loads
`centuria/bin/run` and checks that `live.json` is written and removed (and that a
missing job folder is harmless).

## Screenshots

`docs/camp.jpg`, `docs/tent.jpg` and `docs/cast.jpg` were taken from
`--demo` mode at 1440x900.
