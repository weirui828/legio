# legio

A software factory. Label a GitHub issue, and a fixed cast of roles takes it all the
way: doorkeeper → spec → build → gate → review → arbiter → you merge the PR.

- **legio** is the command and the system itself.
- **centuria** is the set of files stationed inside one project (`<project>/.centuria/`),
  and also the unit that runs that project.

One centuria per project. Many projects under one legio.

This repo carries a second tool: **swarm**, the review-only set — the same reviewer
cast with the whole pipeline removed (diff in, review files out, nothing else).
See the swarm section below and `swarm/README.md`.

---

## The split: legio does not know what the pipeline looks like

```
legio (one copy)                  centuria (one copy per project)
─────────────────                 ──────────────────────────────
find the projects                 the state machine, job.json
turn new issues into jobs         which stages exist
spawn nothing itself              which role belongs to each stage
read reports back                 what the artifacts are called
own the host registry             what counts as passing
                                  the prompt text (role + this round)
```

legio talks to a centuria through two commands:

```
job next <id> --json    a work order: {kind: agent|gate|human|done|noop,
                                       role, tier, cwd, role_file, header, task}
job done <id>           centuria reads the artifacts and decides where the job goes
```

So:

- **There is no stage name, role name, or `STATUS: READY` anywhere in `legio`.**
  (`grep -nE 'tesserarius|build\.md|VERDICT:' legio` comes back empty.)
- Upgrading the pipeline means re-copying `.centuria/`; legio does not change.
- Adding a host means changing `hosts/*.json`; centuria does not change.
- **legio can be deleted.** A centuria carries `bin/run` and can drive itself.

One line: **centuria owns the project, legio owns getting work to a host.**

---

## Three words, do not mix them

| word | what it is | where it lives | how many |
|---|---|---|---|
| **role** | the manual for one job | `<project>/.centuria/roles/*.md` | 8, fixed |
| **roster** | which roles this job fields, and at what tier | `job.json`'s `roster` field | one per job |
| **host** | how to hand a work order to an agent CLI | `legio/hosts/*.json` | one per CLI |

A centuria holds **roles**; it writes a **roster** for each job; legio uses a **host** to
run it.

## What remembers what

| layer | how many | lifetime | remembers |
|---|---|---|---|
| legio | 1 | permanent | nothing. It only drives |
| **centuria** | one per project | as long as the project | **everything**: `jobs/` holds every job.json and artifact |
| job | N per centuria | until merged / rejected | its own job.json and `round-N/` |
| **agent instance** | many per job | one call, writes one file, exits | **nothing**. It gets a work order |

An agent is a representative the centuria sends out, not a stateful assistant: **work
order in, one file out, exit**. That is why a dead session can resume, why swapping the
host changes nothing, and why a crashed agent cannot corrupt state — the memory lives
only in the centuria's files.

---

## The eight roles

The names are Roman army posts. **You cannot guess the function from the name**, so each
role file opens with it. Same table here:

| Roman name | Equivalent | Function, in one line | Output | When it runs |
|---|---|---|---|---|
| **Tesserarius** | intake | **doorkeeper**: is this issue worth building, how much, how risky | `intake.md` | once per issue |
| **Signifer** | spec-writer | **standard-bearer**: turn a request into a spec that can be executed and checked | `spec.md` | after ACCEPT |
| **Fabri** | builder | **engineer**: write code, run checks, commit, push, open the PR | `build.md` + code | once per round |
| **Probator** | reviewer-code | **inspector**: correct, in scope, actually tested | `review-probator.md` | every round |
| **Medicus** | reviewer-security | **surgeon**: injection, privilege, leaks, dependencies | `review-medicus.md` | `security` surface only |
| **Mensor** | reviewer-ux | **surveyor**: can a user understand it, get through it, recover from errors | `review-mensor.md` | `ui` surface only |
| **Librator** | reviewer-ui | **level-keeper**: alignment, spacing, hierarchy, theme | `review-librator.md` | `ui` surface only |
| **Primus Pilus** | approver | **arbiter**: can this go in, or does a human decide | `decision.md` | after every review passes |

The eight together are a fixed cast. **Instances are not fixed**: a job that burns all
its rounds spawns eighteen or more.

---

## Station a centuria in a project

```bash
legio add ~/dev/webapp --host claude-code
```

This:

1. copies `legio/centuria/` to `~/dev/webapp/.centuria/`
2. points `default_host_spec` at `legio/hosts/<host>.json`
3. writes `.centuria/`, `.worktrees/` — **and whatever paths the host itself creates in
   a project** (for claude that is `.claude/settings.local.json`, for dsh `.dsh/`) — into
   `~/dev/webapp/.git/info/exclude`

**Note step 3: `.git/info/exclude`, not `.gitignore`.** These files never enter git
history, and no tracked file in the project changes. `git status` stays clean.

Then:

```bash
# 1. this project's real checks
$EDITOR ~/dev/webapp/.centuria/checks.sh

# 2. base_branch, protected_paths, merge_policy
$EDITOR ~/dev/webapp/.centuria/config.json

# 3. the three GitHub labels
legio labels webapp

# 4. health check
legio doctor webapp
```

`checks.sh` ships as a placeholder that exits 1 on purpose. A gate that passes when
unconfigured is worse than no gate: it turns "scripts decide whether it works" into
theatre.

---

## Driving it

**A centuria can run a whole job by itself; legio only discovers, installs and reports.**

```bash
# one: let legio forward (it picks the host spec for you)
legio run webapp --agent claude-code --max-steps 20

# two: let legio produce the prompt, paste it into an agent yourself
legio next webapp

# three: skip legio, drive the centuria directly
cd ~/dev/webapp
.centuria/bin/centuria run
.centuria/bin/centuria run --all      # up to `concurrency` jobs at once
```

All three run the same loop: `job next` → host process(es) → `job done`.

**Reviewers run concurrently.** `job next` returns the whole pending review set as one
work order (`kind: reviews`), the runner starts one process per reviewer, then collects
them all before settling. Four reviewers cost one reviewer's wall-clock time, not four.
They are independent by construction: same diff, each writes its own file.

## Centuria commands

```bash
cd ~/dev/webapp

.centuria/bin/centuria run [<job>]        # drive as far as it can go
.centuria/bin/centuria run --all          # up to concurrency jobs, one process each
.centuria/bin/centuria next <job>         # the next step (work order JSON)
.centuria/bin/centuria done <job>         # settle: advance if the artifacts justify it
.centuria/bin/centuria gate <job>         # run checks.sh in the job's worktree
.centuria/bin/centuria summary            # one table
.centuria/bin/centuria view               # JSON
.centuria/bin/centuria queue              # what is queued
.centuria/bin/centuria create <issue>     # turn a labelled issue into a job
.centuria/bin/centuria route <job>        # re-route the roster
.centuria/bin/centuria advance <job> <stage>   # move it by hand (illegal moves refused)
```

`--host-spec` is optional: without it, `.centuria/config.json`'s `default_host_spec` is
used. centuria does not own a host registry — the registry is one file set in
`legio/hosts/`, and a project only remembers which one it prefers.

## legio commands

```
legio add <path> [--host <name>]   station a centuria
legio remove <path>                take it out again
legio ls                           centuriae and their overall state
legio status [--all]               every job
legio inbox                        what is waiting on you, worst first
legio run <project>[:<job>]        turn new issues into jobs, then let centuria drive
legio next <project>[:<job>]       the next step, with a pasteable prompt
legio hosts [--json]               the available host adapters (JSON with --json)
legio labels <project>             create the three GitHub labels
legio sync [<project>]             turn new labelled issues into jobs, show the queue
legio say <project>:<job> <text>   feedback: the job goes back to build
legio reject <project>:<job> <text>  reject a job that waits on you
legio doctor [<project>]           is this centuria still healthy
```

---

## Layout

```
legio/                          the system
├── legio                       the command
├── config.json                 projects_root, stale threshold
├── hosts/                      one JSON per agent CLI
├── centuria/                   the template copied into a project
│   ├── bin/centuria            single entry point, forwards to the three below
│   ├── bin/job                 the state machine; the only writer of job.json
│   ├── bin/run                 the loop and the host adapter; starts agents
│   ├── bin/gate                runs checks.sh in a worktree
│   ├── roles/*.md              the eight roles
│   ├── config.json             routing, protected paths, merge policy
│   └── checks.sh               this project's checks (you fill this in)
├── swarm/                      review-only: a diff in, review files out
│   ├── swarm                   the command (reviewers and the repo, nothing else)
│   ├── api.py                  the library seam: review(...) -> Report
│   ├── hostkit.py              host adapter: build/spawn/collect
│   ├── roles/*.md              the five reviewers
│   ├── hosts/fake.json         test harness; real hosts come from ../hosts
│   └── config.json             reviewer tiers, default host
└── web/                        the dashboard: a camp of tents, one per centuria
    ├── serve.py                stdlib server: static files + GET /api/camp
    ├── index.html app.js styles.css
    ├── assets/                 generated art (WebP + manifest), committed
    ├── tools/prepare_assets.py trims, cuts out and slices the raw art
    └── tests/                  stdlib tests, no network, no model
```

Stationed, a project looks like:

```
<project>/
├── .centuria/
│   ├── bin/ roles/ config.json checks.sh version.json
│   └── jobs/<job>/           issue.md intake.md spec.md build.md round-N/ decision.md
├── .worktrees/<job>/         one worktree per job
└── (the project's own code — not one factory file in it)
```

---

## The pipeline

```
issue labelled `centuria`
   │
   ▼
Tesserarius ──NEEDS-INFO──► asks the author, parks
   │        └─REJECT─────► says why, drops the label
   ▼ ACCEPT (scope may be cut) + RISK / SURFACES
route (script)               → roster + model tiers
   ▼
Signifer                     → spec.md
   ▼
Fabri                        → commit · push · draft PR "Closes #n"
   ▼            ▲
gate (script) ──FAIL──┘      checks.sh + protected_paths; no reviewer runs on a red build
   ▼ PASS
reviewers (started together) ──CHANGES──► Fabri (at most max_rounds rounds)
   ▼ all PASS
Primus Pilus ──APPROVE──► PR ready, waiting for you
              └─ESCALATE─► PR ready, with the one question you have to answer
   ▼
you merge the PR            merge_policy defaults to human: legio never merges for you
   ▼
merged (legio sync notices and closes the job out)
```

---

## Adding a reviewer

Almost free, because routing is a table lookup:

1. add a `surface_reviewers` entry in `config.json`
   (`"perf": {"ballistarius": "medium"}`)
2. add `roles/ballistarius.md`, copying the shape of an existing role
3. teach Tesserarius's prompt that this surface exists

The state machine, the gate and `route` do not change. If the doorkeeper emits a surface
that `config.json` does not list, `route` **fails loudly** instead of silently dropping
it.

Adding a **stage** is the expensive change: `TRANSITIONS` at the top of `bin/job` and the
branches inside `advance()`.

## swarm — the review half

`swarm/` is the second tool in this repo, and it is deliberately small: **review only**.
No issue, no intake, no spec, no build, no rounds, no merge — you hand it a diff and it
hands back reviewers' verdicts.

```bash
./swarm/swarm run code-reviewer on ~/dev/webapp    # one reviewer
./swarm/swarm run all on ~/dev/webapp              # all five, at the same time
```

| name | tier | judges | centuria role |
|---|---|---|---|
| `code-reviewer` | medium | correct, in scope, actually tested | Probator |
| `security-reviewer` | strong | injection, privilege, leaks, dependencies | Medicus |
| `ux-reviewer` | medium | can an ordinary user get through it | Mensor |
| `ui-reviewer` | light | alignment, spacing, hierarchy, theme | Librator |
| `ios-reviewer` | medium | Apple HIG conformance and App Store review risk | — (new) |

It keeps the two things that matter from the pipeline above — the role prompts and the
verdict contract (`VERDICT: PASS` / `VERDICT: CHANGES` as the first line of
`review-<name>.md`) — and it borrows `hosts/` rather than copying it, so one host fix
reaches both tools. A run lands in `<repo>/.swarm/<run-id>/` and that path goes into the
project's `.git/info/exclude`, so the reviewed project's `git status` stays clean.

Exit codes: `0` all PASS · `1` any CHANGES · `2` operational error · `3` empty diff. It
never merges, comments or labels, and it keeps no state between runs. Full reference:
`swarm/README.md`.

## Camp Legio — the dashboard

`web/` is a local, read-only webapp that shows the centuriae as a Roman camp: one tent
per project, and inside a tent a **TABULA OPERUM** (AD FACIENDUM / IN CURSU / FACTUM)
plus the role that is working right now. It is a separate tool: it reads the same
contracts (`centuria view`, the role files, the live heartbeat) and writes nothing.

```bash
python3 web/serve.py              # http://127.0.0.1:8766, the real camp
python3 web/serve.py --demo       # a fake camp, for design work
```

Each job is a pinned note; the lane comes from `active` / `waiting` / `terminal`, so the
UI never learns stage semantics. `bin/run` writes
`.centuria/jobs/<id>/live.json` around every agent call (`roles`, `round`, `started`,
`pid`), which is how the desk knows who is on duty; a file older than ten minutes is
shown as "last seen", not live. Full reference, asset pipeline and tests:
`web/README.md`.

## Two hard rules

1. **`job.json` has exactly one writer**: `bin/job`. It holds a file lock, writes
   atomically, and validates every transition. Anything that wants to change state has to
   go through it.
2. **legio does not merge.** The default `merge_policy` is `human`: an `APPROVE` only
   turns the PR ready and tells you. Merging is a click you make. Set
   `merge_policy: "legio"` if you want it automated.

## Model tiers

Roles are bound to a **tier** (`light` / `medium` / `strong`), not to a model name, so a
centuria's config stays host-agnostic. The tier becomes a concrete model in the **host**
file:

- Claude: `haiku` / `sonnet` / `opus`
- Codex: something else
- switching hosts changes the profile, not the centuria

Non-reviewer roles are set in `role_tiers` (Tesserarius, Signifer, Fabri and Primus Pilus
are all `strong`); reviewers are routed by risk and surface.

Default routing:

| risk | reviewer | tier |
|---|---|---|
| low | Probator | light |
| medium | Probator | medium |
| high | Probator | strong |
| + `ui` | Mensor / Librator | medium / light |
| + `security` | Medicus | strong |

A low-risk change with no UI runs one cheap reviewer; a change that touches both UI and
permissions runs four.

---

## Host adapters

```
legio/hosts/
├── claude-code.json   role file becomes a real system prompt (--append-system-prompt-file)
├── codex.json         role file is concatenated; codex has no separate system-prompt flag
├── dsh.json           dsh headless; needs DEEPSEEK_API_KEY from the keychain
├── gemini.json        untested (gemini is not installed here)
├── echo.json          dry run: prints the prompt
└── fake.json          test harness: writes the artifact an agent would write
```

```bash
legio hosts
legio run webapp --agent claude-code --max-steps 20
legio run webapp --dry-run                 # show the exact command
legio run webapp --agent claude-code --yolo   # add the "do not ask me" flags
```

A profile is a dozen fields:

| field | job |
|---|---|
| `command` | binary plus fixed flags |
| `yolo` | flags added only with `--yolo` (they disable every approval prompt) |
| `role.mode` | `system` (separate system prompt) or `concat` (merged into the prompt) |
| `prompt.via` | `stdin` or `arg` |
| `cwd.mode` | `process` or `flag` (codex's `-C`) |
| `model.flag` | how to name a model |
| `model_tiers` | **tier → concrete model** (host-specific) |
| `env` | variables to inject: `{"value": "..."}` or `{"shell": "..."}` |
| `session` | `new` / `resume` flag templates, so a role can continue its own session |
| `host_paths` | paths this host creates in a project; `legio add` excludes them |
| `timeout_seconds` | per invocation |

**The prompt must never start with `-`.** When it goes in as `argv`, a leading dash is
parsed as an option (dsh answered `unknown option`, echoing the whole prompt back).
`bin/run` therefore builds the prompt as: job header, then role file, then this round's
task.

**Session reuse.** A role that runs more than once in a job (Fabri across rounds, a
reviewer across rounds) can keep its conversation instead of rediscovering the repo every
time. The runner derives a stable uuid from `(job, role)`, passes the profile's
`session.new` flags the first time and `session.resume` flags afterwards, and records
that with a `.session-<role>` marker in the job folder:

```json
"session": {"new":    ["--session-id", "{session_id}"],
            "resume": ["--resume",    "{session_id}"]}
```

A host without a `session` block simply starts fresh every time (dsh headless has no
resume flag). Delete `.centuria/jobs/<id>/.session-*` to force a new session.

**`--yolo` is off by default.** A non-interactive agent has to be pre-authorized to use
its tools, or it stops to ask and the pipeline hangs; but those flags disable every
approval, so you opt in explicitly.

**Secrets** stay out of the JSON and out of your shell:

```json
"env": {"DEEPSEEK_API_KEY": {
  "shell": "security find-generic-password -a \"$USER\" -s deepseek-api -w"}}
```

```bash
security add-generic-password -a "$USER" -s deepseek-api -w 'sk-...'
```

The shell form is resolved only when an agent is spawned, so the key lives in the macOS
keychain and never in a dotfile or a dotfiles repo.

---

## Testing the pipeline itself

`legio/tests/fake-agent.py` plus `hosts/fake.json` run a whole job with no model and no
network to GitHub (a `gh` stub provides the API):

```bash
legio run <project> --agent fake --max-steps 20
```

Every agent invocation is written next to the job as `agent-<round>-<role>.log`, holding
the command, stdout and stderr, so any failure can be read back later.

swarm uses the same trick through `swarm/tests/fake-reviewer.py` plus
`swarm/hosts/fake.json`:

```bash
python3 -m unittest discover -s swarm/tests -v
```

No model and no network there either; it covers the reviewer fan-out, all exit codes,
the `--diff`/`--spec` paths, a crashed reviewer, and the clean-`git status` guarantee.

## What a job cost

```bash
legio/tests/token-report.py 001-add-a-json-flag
```

Reads the host's own session logs and prints, per role: agent processes, model requests
("steps"), how many steps actually executed checks, and input / output / cache-read tokens.
It is host-specific and a development tool, not part of the pipeline.

It exists because **the bill is not proportional to the token total**: cache reads usually
cost a fraction of fresh input, while output costs more per token. Multiply each column by
your host's price; do not read the token total as money.

The useful signal is steps. Each step resends the whole conversation, so cost grows
roughly quadratically inside one agent process. Cutting redundant steps is the only lever
that compounds — but a step cut that causes another build round is a loss, so always
compare "cost" with "did the PR pass review first time".
