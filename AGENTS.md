# AGENTS.md — technical reference for agents and maintainers

**legio** turns labelled GitHub issues into pull requests. [`README.md`](README.md) is the human
introduction; this is the reference for changing the code safely. The pipeline's doorkeeper also
reads it as project context (`centuria/roles/tesserarius.md`), so §4–§6 describe what a build agent
receives. Everything is checked against the source; where a doc disagrees, the source wins (§14).

## Contents

1. [What this repo is](#1-what-this-repo-is) · [verify](#how-to-runverify-a-change) · [conventions](#conventions)
2. [Golden rules](#2-golden-rules) · 3. [Repository map](#3-repository-map) · 4. [Contracts](#4-contracts)
5. [The cast](#5-the-cast) · 6. [Prompt assembly and sessions](#6-prompt-assembly-and-session-reuse) · 7. [Host profiles](#7-host-profiles)
8. [CLI reference](#8-cli-reference) · 9. [Configuration](#9-configuration-reference) · 10. [Recipes](#10-recipes-for-common-changes)
11. [Testing](#11-testing-and-verification) · 12. [Web internals](#12-web-dashboard-internals) · 13. [Gotchas](#13-gotchas) · 14. [Doc map](#14-doc-map)

## 1. What this repo is

| piece | role | shipped as | stationed as |
|---|---|---|---|
| **legio** | finds projects, turns labelled issues into jobs, owns the host registry, wraps the centuria CLI | `legio`, `config.json`, `hosts/` | never copied into a project |
| **centuria** | the pipeline: state machine, roles, artifacts, one worktree per job | `centuria/` (template) | `<project>/.centuria/` |
| **swarm** | review-only: diff in, review files out | `swarm/` | runs against any git repo |
| **web** | dashboard, two skins (Principia, camp) + Legatus (a read-only `claude -p` agent) + three confirmed actions | `web/` | reads projects; changes them only through the CLI after the operator confirms (station, feedback, reject) |

Stationing copies `centuria/` to `<project>/.centuria/`, appends `.centuria/`, `.worktrees/` and the
host's `host_paths` to the project's **`.git/info/exclude`** (never `.gitignore`), and stamps
`.centuria/version.json`. A stationed project runs without legio via `.centuria/bin/centuria`, though
`run` still needs a host spec: `default_host_spec` points into the legio checkout, so pass
`--host-spec` or edit it first. This checkout dogfoods itself (`.centuria/` is untracked; jobs `001`–`003`).

Deps: Python stdlib only (README says 3.10+; source needs 3.9's `str.removeprefix`), `git`, an
authenticated `gh` for GitHub calls. `swarm` needs `git` (+`gh` only for `--pr`).
`web/tools/prepare_assets.py` is the only script needing Pillow + numpy, and is never imported by
shipped code.

### How to run/verify a change

```bash
./legio --help && ./legio hosts && ./legio doctor   # discovery/health, read-only
python3 -m unittest discover -s tests -p 'test_*.py' -v   # 8 tests
python3 -m unittest discover -s swarm/tests -v            # 24 tests
python3 -m unittest discover -s web/tests -v              # 36 tests
python3 -m py_compile legio centuria/bin/centuria centuria/bin/job \
  centuria/bin/gate centuria/bin/run swarm/swarm swarm/*.py web/*.py web/tools/*.py tests/*.py
bash .centuria/checks.sh          # this checkout's real static checks
```

Never run `legio add`/`remove`, mutate a real `.centuria/`, or spawn paid agents to verify a change;
fake hosts exist for that (§11).

### Conventions

- Edit the **template** (`centuria/`), never a stationed `.centuria/` copy (untracked, per project).
- Keep `legio` pipeline-blind (§2), state changes inside `centuria/bin/job`, tests offline.
- Markdown artifacts are contracts: header lines are parsed mechanically, so format changes are code changes.
- English, inline code for paths/commands, no build step, no dependencies.

## 2. Golden rules

| # | Rule | Why | Enforced by |
|---|---|---|---|
| 1 | **`job.json` has exactly one writer: `centuria/bin/job`** (not `bin/run`). | Concurrent runners, reviewers and humans must never interleave read-modify-write; the file is the whole state. | `save()` = `.tmp` + atomic `replace`; per-job `.lock` + `.centuria/.lock` (`fcntl.flock`); `advance()` refuses illegal stages; read-only readers skip locks (atomic replace suffices). |
| 2 | **legio never merges.** Default `merge_policy: human`; APPROVE only marks the PR ready. | A faulty reviewer must not ship code. | `advance()` allows `approve → merging` only when `merge_policy == "legio"`; `job merge` is the only merge path. |
| 3 | **No stage, role or artifact name hardcoded in `legio`.** | `centuria/` is a template, not a framework: upgrading the pipeline must not change legio. | `legio` shells out only to `.centuria/bin/{job,gate,run}` and never parses a job artifact — see the check below this table. |
| 4 | **A prompt must never start with `-`.** | Passed as argv for some hosts; a leading dash parses as an option (dsh answered `unknown option`). | `bin/run`/`hostkit.build()` start the body with the job header, role file after it. |
| 5 | **Local excludes go in `.git/info/exclude`, never `.gitignore`.** | Nothing legio creates may enter a project's history or dirty `git status`. | `legio add` adds `.centuria/`, `.worktrees/`, `host_paths`; `swarm/api.py::_ensure_excluded` adds `.swarm/`; `web` never writes to a project itself (its confirmed actions run `legio add` / `bin/job`; Legatus keeps a git-ignored `.legatus/` here). |
| 6 | **An agent is a courier: work order in, one file out, exit.** No conversation is state. | Crashed sessions resume, hosts are swappable, a chatty model cannot corrupt state. | Every prompt names the one artifact; loop = `job next` → host → `job done`; state lives only in `job.json` + artifacts. |
| 7 | **Tests stay offline: fake hosts, fake `centuria view`, no network, no model.** | Testable without credentials; fake hosts prove the host contract. | `hosts/fake.json` + `tests/fake-agent.py`; `swarm/hosts/fake.json` + `swarm/tests/fake-reviewer.py`; `web/tests` temp fixtures + `web/tests/fake_claude.py` (Legatus) + `web/tests/fake_cli.py` (actions). |
| 8 | **Stage names live in `centuria/bin/job`; role assignment lives in config.** | Adding a role is a table edit; adding a stage is a deliberate code change. | `TRANSITIONS`; `config.json` `stages`, `routing`, `surface_reviewers`, `role_tiers`, `tiers`. |
| 9 | **Never point `fake` at a real project.** | `tests/fake-agent.py` commits, pushes and writes artifacts unconditionally. | Host profiles warn; use a throwaway repo. |

Pipeline-blindness check: `grep -nE 'tesserarius|build\.md|VERDICT:' legio` comes back empty.

## 3. Repository map

| path | responsibility |
|---|---|
| `legio` | driver/registry CLI (807 lines, no pipeline names): discovery, `add`/`remove`, `labels`, `dispatch`, thin wrappers around `.centuria/bin/{job,gate,run}`. `VERSION = "0.1.0"`. |
| `config.json` | `projects_root` + `stale_minutes` (the latter unused). |
| `hosts/*.json` | the host registry: `claude-code`, `codex`, `dsh`, `echo`, `fake`, `gemini`. |
| `centuria/bin/centuria` | entry point; forwards `run`/`gate` to their scripts, everything else to `job`; preserves exit code. |
| `centuria/bin/job` | state machine; only writer of `job.json`; work orders; settlement; GitHub side effects. |
| `centuria/bin/run` | loop (`next` → host → `done`), prompt assembly, sessions, `live.json`, step budget, `--all`. |
| `centuria/bin/gate` | runs `.centuria/checks.sh` **inside the job worktree**; `protected_paths`; writes `round-N/checks.md`. |
| `centuria/roles/*.md` | the 8 role prompts (template; copied into each project). |
| `centuria/config.json` | routing, stages, tiers, protected paths, merge policy. |
| `centuria/checks.sh` | project checks placeholder; exits 1 on purpose. |
| `swarm/swarm` | argparse CLI over `api.review()`. |
| `swarm/api.py` | diff resolution, reviewer fan-out, verdict parsing, run folder + `Report`. |
| `swarm/hostkit.py` | host adapter: build/spawn/collect; no jobs, no sessions. |
| `swarm/config.json`, `roles/*.md`, `hosts/fake.json` | reviewer registry + 5 prompts + test harness (shadows `../hosts/fake.json`). |
| `web/serve.py` | stdlib HTTP: static `web/` + 3 read-only JSON endpoints + Legatus (`/api/legatus*`) + confirmed actions (`/api/action*`); shells out to `centuria view`, to `claude -p` (Legatus) and, after the operator confirms, to `legio add` / `bin/job` (actions). |
| `web/legatus.md` | Legatus's brief, appended to Claude Code's system prompt. |
| `web/principia/{index.html,app.js,styles.css}` | the default skin: three panels (projects / job track + scroll / needs you, at work, Legatus). |
| `web/{index.html,app.js,styles.css,assets,tools,tests,docs}` | the camp skin, 51 WebP + manifest, art pipeline, tests, screenshots. |
| `tests/` | `fake-agent.py`, `test_hosts_json.py` (5), `test_live_heartbeat.py` (3), `token-report.py`. |
| `design/` | local, not in git: art direction and raw art (`prototypes/ui/`), old design briefs (`archive/`). |
| `.centuria/`, `.worktrees/` (+ `.dsh/` with the dsh host) | local, untracked, listed in `.git/info/exclude`. |

## 4. Contracts

### 4.1 Three words

| word | what it is | lives in | count |
|---|---|---|---|
| **role** | instructions for one job: frontmatter + duty line + output contract | `<project>/.centuria/roles/*.md` | 8, fixed (`legio doctor` checks) |
| **roster** | which reviewers this job fields, at which tier | `job.json` → `roster.reviewers` | one per job |
| **host** | how to hand a prompt to an agent CLI | `legio/hosts/*.json` (+ `swarm/hosts/`) | one per CLI |

The roster never contains stage roles (`tesserarius`, `signifer`, `fabri`, `primus-pilus`); their
tiers come from `role_tiers`.

### 4.2 The legio ↔ centuria contract

legio never reads `job.json`; it shells out to `.centuria/bin/job` (cwd = project) and consumes `job
view` (the JSON list behind `ls`/`status`/`inbox`/`next`), `job next <id>` (one work order), `job
queue --json` (dispatch rows) and `job create <issue>`; it forwards `route`/`advance`/`feedback`/
`reject` to `job` and `gate` to `bin/gate`. It **never calls `job done`** — the `settle()` helper in
`legio` is dead code — and it never executes an agent: the `job next → host → job done` loop lives in
`centuria/bin/run` (§6).

| kind | when | extra fields |
|---|---|---|
| `agent` | stage in `config.stages` (`intake`, `spec`, `build`, `approve`) | `role`, `tier`, `cwd` (repo root), `role_file`, `header`, `task` |
| `reviews` | `stage == review` with pending reviewers | `cwd`, `header`, `roles[]` of `{role, tier, role_file, task}` |
| `gate` | `stage == gate` | `bin` (absolute), `argv` (`[job_id]`) |
| `human` | `needs-info` / `needs-human` | `why` (needs-human: `human_reason`) |
| `done` | `merged` / `rejected` | `why` = stage |
| `noop` | `review` with no pending reviewers | `why` |
| `unknown` | stage absent from `config.stages` | `why`; `bin/run` exits 1 |

Every order also has `id`, `stage`, `round`. The other half of the contract is `job done <id>` (called
by `bin/run` / `centuria done`, never by legio): `settle()` reads artifacts, `advance()` applies the next stage with its
guards, and it prints `{"id", "stage", "advanced": bool}`; terminal/`needs-info`/`needs-human` stages
print `advanced: false`. `job queue --json` is different: rows `{kind, issue, job, stage, note}` with
kinds `new|resume|wait|skip|hold`, used by `legio sync`, `bin/run` dispatch and `centuria queue`; it
also advances a `needs-human` job whose PR is merged.

### 4.3 Stage machine

`TRANSITIONS` in `centuria/bin/job` is the authority:

| from | allowed | guards / effects |
|---|---|---|
| `intake` | `needs-info`, `rejected`, `spec` | `intake.md` `DECISION` must be `NEEDS-INFO`/`REJECT`/`ACCEPT`; comments on the issue and moves labels (NEEDS-INFO adds, REJECT removes the queue label); `spec` requires a roster and creates the worktree |
| `needs-info` | `intake`, `rejected` | `intake`: archive `intake.md` → `intake-<k>.md`, clear `intake`, rewrite `issue.md`, remove label, require a slot; `rejected`: requires `rejection.md` (normally `job reject`) |
| `spec` | `build` | `spec.md` exists; `next_round()` → round 1 + `round-N/` |
| `build` | `gate`, `needs-human` | `gate`: `STATUS: READY`, clean worktree, commits ahead of `origin/<base>`, HEAD pushed, one open PR (discovered if absent); `needs-human`: `STATUS: BLOCKED`, escalate |
| `gate` | `review`, `build`, `needs-human` | `round-N/checks.md` exists with `COMMIT` == HEAD; PASS → review (reviews reset to `pending`); FAIL → next round or `needs-human` on the last round |
| `review` | `approve`, `build`, `needs-human` | all `review-<role>.md` present with valid verdicts; `approve` needs zero `CHANGES`; else next round or `needs-human` on the last round |
| `approve` | `merging`, `needs-human` | `decision.md` first line `APPROVE`/`ESCALATE`; `merging` (entered via `job merge`) needs `merge_policy == "legio"` + `APPROVE`; `needs-human` needs `human` policy or `ESCALATE` |
| `merging` | `merged`, `needs-human` | `gh pr view` reports `MERGED` |
| `needs-human` | `build`, `merged`, `rejected` | `build`: a `feedback-*.md` newer than `decision.md`, reset `round_limit = round + max_rounds`, next round, remove label; `merged`: PR merged; `rejected`: requires `rejection.md` |

`TERMINAL = {merged, rejected}`, `WAITING = {needs-info, needs-human}`; *active* = neither. Entering
`needs-human` writes `human_reason`, marks a draft PR ready, comments on the PR (or issue) and adds
the label. Entering a terminal stage removes the worktree and deletes the branch.

### 4.4 `job.json` schema

Written only by `centuria/bin/job` (`save()`): via `create`, `advance`, `sync`, `roster`, `cost`, and the commands built on them (`done`, `queue`, `feedback`, `reject`, `merge`).

| field | notes |
|---|---|
| `id` | `NNN-slug`; `NNN` = max existing prefix + 1 (3 digits); slug = first 4 lowercase alnum title words |
| `issue`, `title`, `issue_url` | from GitHub |
| `pr`, `pr_url` | set at `build → gate` from `gh pr list --head <branch>` |
| `branch`, `worktree` | `centuria/<id>`; absolute `<repo>/.worktrees/<id>` |
| `stage` | a `TRANSITIONS` key |
| `round`, `round_limit` | 0 until spec is done; limit starts at `max_rounds`, feedback resets to `round + max_rounds` |
| `intake`, `roster` | `{decision, rescoped, risk, surfaces[]}` / `{reviewers: {role: tier}}`, or null |
| `gate`, `reviews` | `PASS`/`FAIL`/null; `{role: "PASS"\|"CHANGES"\|"pending"\|"invalid"}` |
| `cost_usd`, `human_reason` | float; `"approved - merge the PR"` / `"needs a human"` / null |
| `started`, `ended` | ISO-8601 `…Z`; `ended` set on terminal **or waiting**, else null |

```json
{"id":"001-add-a-json-flag","issue":1,"pr":2,"stage":"merged","round":1,"round_limit":3,
 "branch":"centuria/001-add-a-json-flag","worktree":"/…/.worktrees/001-add-a-json-flag",
 "intake":{"decision":"ACCEPT","rescoped":false,"risk":"low","surfaces":[]},
 "roster":{"reviewers":{"probator":"light"}},"gate":"PASS","reviews":{"probator":"PASS"},
 "cost_usd":0.0,"human_reason":"approved - merge the PR","started":"…","ended":"…"}
```

Job folder: `job.json`, `.lock`, transient `live.json`; `issue.md`, `intake.md`, `intake-<k>.md`,
`spec.md`, `build.md`, `decision.md`, `rejection.md`, `feedback-<k>.md`;
`round-<N>/{checks.md,checks.log,review-<role>.md}`; `agent-<round>-<role>.log`;
`.session-<role>` only with `session.resume`.

### 4.5 Artifact contracts

`job` parses files, never prose. Headers are `KEY: value` lines before the first blank line
(`header()` stops there); the rest is body.

| file | written by | parsed contract |
|---|---|---|
| `issue.md` | `job create` / `job done` after a reply | quoted issue body + author/operator comments with a prompt-injection warning; Tesserarius input |
| `intake.md` | Tesserarius | headers `DECISION` (`ACCEPT`/`NEEDS-INFO`/`REJECT`), `RISK` (`low`/`medium`/`high`), `SURFACES` (comma list; `none` = empty), `RESCOPED` (`yes`/`no`) |
| `spec.md` | Signifer | existence only; `SPEC: READY` is convention |
| `build.md` | Fabri | **first line** `STATUS: READY` or `STATUS: BLOCKED`; reason in `## Blocked` |
| `round-N/checks.md` + `.log` | `bin/gate` | headers `GATE` (`PASS`/`FAIL`), `COMMIT` (full sha); `.log` is raw output (last 80 lines embedded in md) |
| `round-N/merge-checks.md`/`.log` | `bin/gate --merge` | same contract, written by `job merge` |
| `round-N/review-<role>.md` | reviewers | **first line** full-match `VERDICT:\s*(PASS\|CHANGES)`; anything else is `invalid` |
| `decision.md` | Primus Pilus / `escalate()` | **first line** `APPROVE`/`ESCALATE`; body after the first blank line is the human message |
| `feedback-<k>.md` | `job feedback` | `FEEDBACK: k` + text; must be **newer than `decision.md`** to advance |
| `rejection.md` | `job reject` | `REJECTED` + reason; required for a waiting job to be rejected |
| `agent-<round>-<role>.log` | `bin/run` | command, stdout, stderr, one per invocation |
| `live.json` | `bin/run` | `{roles:[…], round, started, pid}`; written before spawn, removed after |

`intake.md`/`checks.md` keys are upper-cased; `build.md`/`decision.md`/`review-*` use the first line
only (case-sensitive in centuria; swarm is looser, §8).

## 5. The cast

| role | function | tier | output | routed when |
|---|---|---|---|---|
| `tesserarius` | doorkeeper | `strong` (`role_tiers`) | `intake.md` | stage `intake` |
| `signifer` | standard-bearer | `strong` (`role_tiers`) | `spec.md` | stage `spec` |
| `fabri` | engineer | `strong` (`role_tiers`) | `build.md` + code | stage `build` |
| `probator` | inspector | risk-dependent | `review-probator.md` | every round |
| `medicus` | surgeon | `strong` | `review-medicus.md` | surface `security` |
| `mensor` | surveyor | `medium` | `review-mensor.md` | surface `ui` |
| `librator` | level-keeper | `light` | `review-librator.md` | surface `ui` |
| `primus-pilus` | arbiter | `strong` (`role_tiers`) | `decision.md` | stage `approve` |

Routing (`apply_routing()`) = `routing[risk]` plus `surface_reviewers[surface]` (later wins); unknown
risk/surface/role/tier is a hard error. Defaults: `low → probator light`, `medium → probator medium`,
`high → probator strong`; `ui` adds `mensor medium` + `librator light`; `security` adds `medicus
strong`. `roster = {"reviewers": {...}}`; routing is applied by `job done` when an ACCEPTed intake has
none (or `centuria route`, which saves it), and `intake → spec` refuses without it.

Role file anatomy (`centuria/roles/*.md`):

```markdown
---
role: fabri
function: engineer
output: build.md + code + commit + PR
model_tier: strong          # display only (web cast); routing uses config.json
tools: read / search / list / write / run commands
---

# Fabri · Engineer

> **Fabri were the legion's builders — this line is the job:**
> build what the spec says: write code, run the checks, commit, push, open a PR.
```

The blockquote is the dashboard's duty line; the output contract at the bottom says what the agent
must write. `job`/swarm parse the resulting artifacts. Agents write only their artifact (Fabri also
writes code), never edit another role's file, never merge/label/comment (scripts do that), never widen
the accepted scope.

## 6. Prompt assembly and session reuse

`centuria/bin/run::build()` is the centuria runner's only prompt builder (swarm has its own in
`swarm/hostkit.py`):

1. `header` = `Job: <id>. Job folder: <abs>/. Main checkout: <repo>. Worktree: <abs>. Branch:
   centuria/<id>. Base: origin/<base>. Issue: #n.`
2. body: `role.mode == "system"` → `header + "\n\n" + task`, role file passed via `role.flag`;
   `concat` → `header + "\n\n" + role text + "\n\n---\n\n" + task`.
3. cmd = `command`, then session flags, then `yolo` (only with `--yolo`), then `cwd.flag` when
   `cwd.mode == "flag"`, then `model.flag`.
4. `prompt.via: stdin` → body on stdin; `arg` → body as final argv.

`task` (`task_for()`) per stage: intake = read `issue.md`, write `intake.md` with the three header
lines; spec = read `intake.md`, write `spec.md`; build = `cd <worktree>`, fix exactly the named round
input (`spec.md` round 1, `checks.md` after a gate fail, `review-*.md` after CHANGES, latest
`feedback-*.md` after human feedback), then commit/push/open a draft PR; review = read `checks.md` +
`spec.md`, write `round-N/review-<role>.md`; approve = read everything, write `decision.md`. Every
stage runs with `cwd` = repo root (the sandbox must reach worktree, job folder and `.git`).

Sessions: for hosts with `session.resume`, id = `uuid5(NAMESPACE_URL, "<job>/<role>")`; first call
`session.new`, later `session.resume`, and `.session-<role>` records that the session exists (delete
it to reset). Hosts without the block (dsh) start fresh every time.

Runner behavior: **reviews run concurrently** (`kind: reviews` spawns all, then collects; a non-zero
exit stops settlement but peers are still logged); **`--yolo` is off by default** (it disables
approval prompts); **env** is `{"value":…}` or `{"shell":…}` resolved at spawn (15 s timeout, empty =
abort); **budget** `--max-steps` defaults to 10; each invocation writes `agent-<round>-<role>.log`;
`live.json` is written/removed around each agent, best-effort. **`bin/run` exits 1 only for its own
errors** — an agent/gate failure prints and returns, so exit 0 does not mean the job advanced.

## 7. Host profiles

A profile says how to invoke one agent CLI. Registry = `hosts/*.json`; swarm searches `--hosts-dir`,
then `swarm/hosts/`, then `../hosts/` (swarm/hosts wins).

| field | meaning |
|---|---|
| `host`, `about`, `untested` | display name, description; `untested` only warns |
| `command` | binary + fixed flags; tokens may use `{placeholders}` |
| `yolo` | flags added only with `--yolo` |
| `role` | `{mode: "system"\|"concat", flag: […]}`; `system` needs a flag consuming `{role_file}` |
| `prompt` | `{via: "stdin"\|"arg"}` (default `stdin`) |
| `cwd` | `{mode: "process"\|"flag", flag: […]}`; `flag` e.g. codex `-C {cwd}` |
| `model` | `{flag: […]}`; empty = no model flag |
| `model_tiers` | **tier → concrete model id** |
| `env` | `{KEY: {"value": …}\|{"shell": …}}`, resolved at spawn |
| `session` | `{new: […], resume: […]}`, both with `{session_id}`; absent = no resume |
| `host_paths` | paths the host creates in a project; `legio add` excludes them |
| `timeout_seconds` | per invocation (default 3600) |

Required keys: `command`, `role`, `prompt` (the host loaders `bin/run` / `hostkit.load_host` validate them). Placeholders: `{role_file}`, `{cwd}`,
`{model}`, `{job}`, `{stage}`, `{centuria}`, `{host_dir}` (centuria); `{repo}`, `{run}`, `{out}`,
`{role}`, `{reviewer}` (swarm). Unknown ones stay verbatim on purpose. Tier indirection:
`model = model_tiers[tier] or model_tiers["medium"] or ""`; changing hosts changes models, not the
centuria.

| host | role / prompt / cwd | model | session | host_paths |
|---|---|---|---|---|
| `claude-code` | system (`--append-system-prompt-file`) / stdin / process | `--model` | new+resume | `.claude/settings.local.json` |
| `codex` | concat / stdin / flag `-C` | `-m` | — | — |
| `dsh` | concat / arg / process | — | — | `.dsh/`; keychain `DEEPSEEK_API_KEY` via `env.shell` |
| `echo` | concat / stdin / process | — | — | — |
| `fake` | concat / stdin / process | — | — | — |
| `gemini` | concat / stdin / process | `-m` | — | — (`untested: true`) |

Add a host: create `hosts/<name>.json` only; verify `./legio hosts` and `.centuria/bin/run <job>
--host-spec hosts/<name>.json --dry-run`; set `"untested": true` until a real run passes; list
`host_paths` if the CLI writes into projects. No host-specific logic elsewhere.

## 8. CLI reference

### `legio`

Global flags parse anywhere: `--root DIR`, `--project NAME` (filter for `status`/`doctor`),
`--offline`, `--all`, `--dry-run`, `--force`, `--agent NAME`, `--host NAME`, `--max-steps N`,
`--yolo`, `--json`. Discovery = `<projects_root>/*/.centuria/config.json`, skipping folders named `~…`
(archives, third-party clones); root from `config.json`, `LEGIO_ROOT`, then `--root`.

| command | behavior |
|---|---|
| `add <path\|name> [--host H] [--force] [--dry-run]` | copy template → `<path>/.centuria/`, chmod, write `version.json`, set `default_host_spec` (default `echo`), add excludes; needs a git repo; refuses an existing `.centuria` without `--force` |
| `remove <path\|name> [--force]` | delete `.centuria/` (prompt unless `--force`); leaves exclude lines |
| `ls` / `status [--all]` / `inbox` | centuria counts + version / job table (active unless `--all`) / waiting jobs with `why` |
| `next <project>[:<job>]` | header + role file + round task (pasteable); only `kind: agent` |
| `route <project>:<job>` | risk + surfaces → roster (saved) |
| `gate <project>:<job>` / `advance <project>:<job> <stage>` | forward to `bin/gate` / `job advance` (illegal moves refused), exit code preserved |
| `say <project>:<job> <text>` / `reject <project>:<job> [reason]` | feedback (stdin) → back to build / reject a waiting job |
| `sync [<project>]` | dispatch new labelled issues, then show the queue |
| `doctor [<project>]` | health checks; exit 1 on problems (bins, checks.sh, version, 8 roles, routing targets, tiers, protected-path prefixes) |
| `labels <project>` | `gh label create --force` the three configured labels |
| `run <project>[:<job>] [--agent H] [--max-steps N] [--yolo] [--dry-run]` | **always** dispatches first (`job queue` → may create jobs), then forwards to `.centuria/bin/run`; no job = `--all`; propagates its exit code |
| `hosts [--json]` / `version` | table or `[{host, model_tiers, untested}]`; `legio 0.1.0` |

Exit: 0 ok; 1 for `die()`/refusal, `doctor` problems, propagated `gate`/`run` codes. `add`/`new` are
aliases; `go` is dead (unregistered).

### `centuria`, `job`, `gate`, `run`

`.centuria/bin/centuria <cmd>` forwards `run` → `bin/run`, `gate` → `bin/gate`, everything else →
`bin/job` (preserves exit code); `-h/--help` prints usage; missing target exits 1.

`job <cmd> <job>` — `<job>` is a **full id or issue number**; an all-digit arg is always an issue
number (`job next 003` = issue #3). Commands: `queue [--json]`, `create`, `advance`, `merge`,
`feedback` (stdin), `reject` (stdin), `roster`, `sync`, `cost`, `summary`, `view`, `route`, `next`,
`done`. `view`/`summary`/`next` are read-only (no write permission needed);
`queue`/`create`/`advance`/`merge`/`feedback`/`reject` may use `gh` (comments, labels, PR lookups). Errors/refusals exit 1.

`gate <job> [--merge]` → writes `round-N/checks.md` + `.log` (`merge-checks.*` with `--merge`); exits
**0** PASS, **1** FAIL, **2** error; refuses `round < 1`; fails when the branch changes/deletes an
existing `protected_paths` match (new files fine; `fnmatch`, `*` crosses `/`). `checks.sh` always runs
from `.centuria/checks.sh` with the worktree as cwd, so a branch cannot alter its judges.

`run [<job>] [--host-spec P] [--max-steps N] [--yolo] [--dry-run]`, or `run --all […]`: host spec
falls back to `default_host_spec` (error if neither), budget 10, no job dispatches first. `--all` runs
up to `concurrency` active jobs, one child `run` process each, then summarizes. `--dry-run` prints
command + full prompt and returns (for `reviews` only the first reviewer; no agent, log or settlement).

### `swarm` and `web`

`./swarm/swarm run [<reviewer> …] [on] <repo> [flags]` (`on` decorative; no reviewer or `all` = all).
Flags: `--base`, `--head`, `--diff <path|->`, `--pr N`, `--spec PATH`, `--host`, `--hosts-dir`,
`--risk`, `--tier ROLE=TIER` (repeatable), `--jobs N`, `--timeout S`, `--out DIR`, `--yolo`,
`--dry-run`, `--json`. Also `reviewers [--json]`, `hosts [--json]`, `version`. Exit: 0 PASS, 1 CHANGES,
2 error, 3 empty diff, 130 Ctrl-C; bare `swarm` prints help and exits 2.

`python3 web/serve.py [--port 8766] [--root DIR] [--demo] [--no-legatus] [--no-actions] [--legatus-model ID]`
binds `127.0.0.1`, exits 1 on bind failure; its only POSTs are Legatus's and the confirmed actions (§12).

## 9. Configuration reference

`config.json` (repo root): `projects_root` (default `~/dev`; overridden by `LEGIO_ROOT`, then
`--root`), `stale_minutes` (240, loaded into `opts` but **unused**; the web stale rule is its own
600 s constant) and `legatus` (`{model: "claude-opus-5-5", command?: ["claude"]}`, read by `web/serve.py`).

`<project>/.centuria/config.json`:

| key | default | meaning |
|---|---|---|
| `concurrency` | 2 | max active jobs; enforced by `job create` and `needs-info → intake`; `run --all` caps children |
| `max_rounds` | 3 | initial `round_limit`; feedback resets it to `round + max_rounds` |
| `base_branch` | `main` | worktree starts at `origin/<base>`; gate diffs `origin/<base>...HEAD` |
| `merge_method` | `merge` | `gh pr merge --<merge_method>` (when `merge_policy == "legio"`) |
| `merge_policy` | `human` | `human` = APPROVE stops at needs-human; `legio` = a manual `job merge` merges (never automatic) |
| `default_host_spec` | `null` | host JSON path; set by `legio add`; `null` + no `--host-spec` = error |
| `labels` | queue/needs-info/needs-human | requires all three keys for `legio labels` |
| `routing` | low/medium/high → probator | risk → base reviewers |
| `surface_reviewers` | `ui` → mensor+librator; `security` → medicus | surface → extra reviewers |
| `stages` | intake/spec/build/approve | stage → role for `kind: agent`; missing stage = `kind: unknown` |
| `role_tiers` | 4 stage roles = `strong` | tier for non-reviewer roles |
| `tiers` | `["light","medium","strong"]` | validation set; routed tiers must be in it |
| `protected_paths` | `.centuria/checks.sh`, `.centuria/config.json` | fails gate on modify/delete; additions allowed; `*` crosses `/` |
| `ports` | `{"base":5100,"step":10}` | **unused** (reserved, no reader) |

Default labels: `centuria`, `centuria:needs-info`, `centuria:needs-human`; colours
`5319E7`/`FBCA04`/`D93F0B`. Every pipeline comment is prefixed `<!-- centuria -->`; only comments by
the issue author or the `gh api user` login are trusted into `issue.md`.

`swarm/config.json`: `default_host` (`claude-code`), `out_dir` (`.swarm`), `timeout_seconds` (3600),
`max_diff_lines` (3000, warning only), `reviewers` (`{name: {tier, about}}`), `risk_reviewer`
(`code-reviewer`), `risk_tiers` (`light`/`medium`/`strong`).

Only `LEGIO_ROOT` is read from the environment (plus host `env` injection and, in swarm tests,
`SWARM_FAKE_VERDICT`/`SWARM_FAKE_FAIL`).

## 10. Recipes for common changes

**Add a centuria reviewer (cheap).** Edit `centuria/config.json` (`surface_reviewers`/`routing`), add
`centuria/roles/<role>.md` with the verdict contract, and teach the Tesserarius prompt the new surface
if it is one. `route`, the state machine and the gate are table-driven; unknown surfaces fail loudly.
Verify `./legio doctor`, then `centuria route <job>` + `centuria next <job>` in a scratch project.

**Add a stage (expensive).** Files: `centuria/bin/job` (+ config + role file). (1) add it to
`TRANSITIONS` (and `TERMINAL`/`WAITING` if not active); (2) add an `advance()` branch — guards + side
effects (comments/labels/worktree/next round) belong there; (3) add a `settle()` branch; (4) add
`task_for()` if agent-driven; (5) map it in `config.json` `stages` and add the role. Do not touch
`legio`; verify with the offline fake pipeline (§11), `legio doctor`, and `job view` flags.

**Add a swarm reviewer (cheap).** `swarm/roles/<name>.md` + a `swarm/config.json` `reviewers` entry;
verify `./swarm/swarm reviewers` and `./swarm/swarm run <name> on <scratch> --dry-run`.

**Retier a role.** Edit `role_tiers`/`routing`/`surface_reviewers` (tier must be in `tiers`); to change
what a tier *means*, edit `hosts/<host>.json` `model_tiers`. Verify `centuria next <job>` shows the
tier and `./legio doctor`.

**Add a host.** One `hosts/<name>.json` (§7); verify `./legio hosts` and a `--dry-run`; update the
README's prerequisite/host list if it is user-facing.

**Change the web UI.** Edit `web/{index.html,app.js,styles.css,assets}`; keep it read-only except for Legatus
and the three confirmed actions (§12): add no other POST, write or agent call; don't widen `JOB_FIELDS` or the artifact allowlist casually. Regenerate art
with `python3 web/tools/prepare_assets.py` (Pillow + numpy; source art is local in
`design/prototypes/ui/assets-src/`). Verify with web tests + `python3 web/serve.py --demo`, then update
`web/README.md` and screenshots in `web/docs/`.

## 11. Testing and verification

All suites are stdlib `unittest`, offline, temp-dir fixtures, from the repo root:

| command | tests | covers |
|---|---|---|
| `python3 -m unittest discover -s tests -p 'test_*.py' -v` | 8 | discovery skips `~…` folders, `legio hosts --json` shape/parse/fallbacks + `live.json` write/remove/missing folder |
| `python3 -m unittest discover -s swarm/tests -v` | 24 | fan-out, PASS/CHANGES/ERROR, exit codes, `--diff`/`--pr`/`--spec`, crashed reviewer, tier/risk overrides, `--jobs 1`, dry-run, empty diff, unknown reviewer/host, library API, clean `git status` |
| `python3 -m unittest discover -s web/tests -v` | 36 | payload allowlist, discovery (skips `~…` folders), uncharted repos, demo camp, HTTP routes, both skins served, scroll allowlist/caps, 405s, traversal, asset manifest, Host allowlist, Legatus (fake claude: argv, resume, origin/token, reset, failures, off states), actions (fake CLI: targets, stages, stdin, failures, token, demo) |
| `python3 -m unittest tests.test_live_heartbeat -v` | 3 | heartbeat tests, addressable individually |
| `bash .centuria/checks.sh` | — | this checkout's gate: `py_compile`, `json.tool`, `bash -n` |

Fake-host end-to-end (tests the pipeline, not legio's own tests): create a **throwaway** git repo with
a local bare `origin` (fake-agent commits and pushes), then station a centuria in it and drive it
**from that project's directory** — `.centuria/bin/run` resolves the centuria from its own path, so
running it from this checkout would drive this checkout's own `.centuria/` with its real host:

```bash
./legio add /tmp/scratch --host fake
cd /tmp/scratch && ./.centuria/bin/centuria run --max-steps 20
```

`tests/fake-agent.py` writes the artifact each role would write, through the real runner. Caveat:
`job create`/`queue`/`advance` call `gh`, and **no `gh` stub is committed** — for a fully offline run
provide a fake `gh` earlier on `PATH` answering `api user`, `issue view/list`, `issue comment/edit`,
`pr list/view`, `pr ready`. Never point `--host fake` at a real project.

Swarm's harness: `swarm/hosts/fake.json` + `swarm/tests/fake-reviewer.py`; knobs
`SWARM_FAKE_VERDICT=CHANGES[:role]`, `SWARM_FAKE_FAIL=<role>|all`.

Cost report (dev tool, DSH-specific): `python3 tests/token-report.py <job-id> [--sessions DIR]
[--workspace GLOB]` → per-role processes/steps/tokens from
`~/.dsh/sessions/*/session-*/session.v4.jsonl.zstd`; exits 1 if nothing matches, 2 on usage.

## 12. Web dashboard internals

`web/serve.py` = `ThreadingHTTPServer` on `127.0.0.1` (default 8766) serving `web/` statically plus
three read-only JSON endpoints; it shells out to `.centuria/bin/centuria view` (5 s timeout) and
never writes to a project itself. **Legatus** and the confirmed **actions** (below) are the only
exceptions to read-only: `GET /api/legatus`
(`{enabled, reason, model, busy, token, messages}`), `POST /api/legatus/ask` (`{token, text, context}`)
and `POST /api/legatus/reset` (`{token}`). Ask runs `claude -p --output-format json --model <m>
--append-system-prompt-file web/legatus.md --permission-mode default (--session-id|--resume) <id>
--add-dir <root> --allowedTools <read-only list> --disallowedTools Write Edit NotebookEdit` in the
legio checkout, prompt on stdin, 600 s limit, one at a time (409). POSTs need JSON, the per-start token
and a matching `Origin` (403 otherwise); state is `.legatus/{session,transcript}.json` (git-ignored).
Off with `--no-legatus`, in `--demo`, or without `claude` on PATH.

**Every request** must carry `Host` 127.0.0.1 / localhost / [::1] (403 otherwise: DNS-rebinding guard).
**Actions** (`GET /api/actions` → `{enabled, reason, hosts, default_host, token}`; `POST /api/action`
`{token, action, …}` → `{ok, code, command, output}`) run the CLI after the operator confirms in the UI:
`station` = `./legio add <path> --host <h>` for a server-listed uncharted path and a non-`fake` host;
`say` = `.centuria/bin/job feedback <id>` (stdin) for a `needs-human` job; `reject` =
`.centuria/bin/job reject <id>` (stdin) for a waiting job. No merge action. One at a time (409), 120 s,
off in `--demo` / `--no-actions`. Legatus's commands get a Run… button only when they parse to one of
these three.

| endpoint | returns |
|---|---|
| `GET /api/camp` | `{generated_at, demo, projects:[{name, path, ok, error, jobs, cast, lives}], uncharted:[{name, path}]}` (`uncharted` = git repos under the root without a centuria; folders named `.…` or `~…` are skipped); jobs filtered to `id, issue, title, stage, round, round_limit, pr, gate, reviews, roster, cost_usd, active, waiting, terminal, human_reason` (no worktree, prompts, config or secrets) |
| `GET /api/job?project=&job=` | allowlisted artifact listing (`files[]` with `path, size, kind`) |
| `GET /api/job/file?project=&job=&path=` | `{path, size, truncated, text}` for one artifact |

The three endpoints are read-only: a POST other than Legatus's and `/api/action` gets 405, and so
does every PUT/PATCH/DELETE. The project comes from a discovered
`*/.centuria/config.json`; job ids must match `[A-Za-z0-9][A-Za-z0-9._-]*`; reads must resolve inside
the job folder. Allowlist: `issue.md`, `intake.md`, `spec.md`, `build.md`, `decision.md`,
`rejection.md`, `feedback-*.md`, `round-*/checks.md`, `round-*/review-*.md`, `agent-*-*.log`;
`job.json` is never exposed. Markdown caps at 96 KB; logs return the **last** 64 KB, flagged
`truncated`. Errors: 400 bad query, 404 not found/traversal, 502 read failure.

Data: `read_jobs` runs `centuria view`; `read_lives` globs `.centuria/jobs/*/live.json` (adds `job`,
`age_seconds`, `stale`); `parse_cast` reads role frontmatter + blockquote. `--demo` serves a synthetic
four-project camp and `DEMO_SCROLLS`.

Two skins, same API. A directory with an `index.html` is served at `<dir>/` (`/principia` → 301).
**Principia** (`web/principia/`, the default): polls `/api/camp` every 2.5 s, builds each open job's
story from `/api/job` + header lines of `intake.md`, `decision.md`, `round-N/checks.md` and
`review-*.md` (cached per stage/round/gate/reviews), offers station / feedback / reject as confirmed actions and everything else (merging included) as
copied commands, with the default station host as a setting;
settings live in `localStorage["principia-prefs"]`. Routes `#/legion/<name>[/job/<id>]`.
**Camp** (`web/index.html` + `app.js`): `index.html` redirects to `principia/` unless
`localStorage["legio-skin"] == "camp"` or `?skin=camp`; lanes come only from
`active`/`waiting`/`terminal`; `live.json` roles appear at the desk; a heartbeat older than 600 s is
"last seen". Hash routes: `#/`, `#/legion/<name>`, `.../cast`, `.../job/<id>`, `.../scrolls`.

Assets: `web/assets/` is committed (51 WebP + `manifest.json` with `file/w/h`), generated from
`design/prototypes/ui/assets-src/` (local, not in git, 64 MB here) by `web/tools/prepare_assets.py`; art
direction in `design/prototypes/ui/assets.md` (local). Screenshots: `web/docs/{camp,tent,job,scrolls,cast,quiet}.jpg` (note the `web/`
prefix). Tests: 36, fake projects with a stub `centuria view`, a fake `claude` (Legatus) and a fake CLI (actions).

## 13. Gotchas

- **`legio add --force` destroys a stationed centuria**, including `jobs/` state; there is no safe
  upgrade via `add`. Copy template files by hand and merge `config.json`; never force a live project.
- **`legio run` always dispatches first**, even with an explicit job: `job queue` hits `gh`, may
  create jobs, and a `gh` failure aborts. Use `.centuria/bin/run <job>` for no GitHub traffic.
- **A numeric job argument means an issue number** (`job next 003` = issue #3).
- **`bin/run` exits 0 after an agent/gate failure** (prints and returns). Read the stage, not the exit.
- **There is no automatic merge path.** `human` policy stops an APPROVE at `needs-human`; with
  `merge_policy: legio`, `settle()` computes `needs-human` but `advance()` refuses that move, so
  `job done` errors and the job stays in `approve`. A human runs `centuria merge <job>` / `job merge`,
  which re-gates on the merged base and runs `gh pr merge --<merge_method>`. `legio` never merges.
- **`--dry-run` is not offline for `legio run`** (dispatch runs); swarm `--dry-run` spawns nothing but
  does create the run dir and write `diff.patch`.
- **Dead/no-op knobs:** `legio --offline` (accepted, unused), repo `config.json` `stale_minutes`
  (unused), centuria `ports` (unused), `legio go` (unregistered).
- **Locking:** per-job `.lock` serialises writers; `.centuria/.lock` serialises `git worktree
  add/remove` (they rewrite `.git/config`). Readers skip locks because `save()` is atomic; a writer
  that cannot lock fails loudly.
- **Concurrency:** `job create` and `needs-info → intake` refuse when `concurrency` active jobs exist;
  `run --all` starts at most `concurrency` children; separate centuriae are independent.
- **Worktrees:** one per job, created only at `intake → spec` from `origin/<base>`, removed on
  terminal. Factory branches are disposable; the PR holds the work.
- **Stale `live.json`:** a killed runner leaves one; the dashboard shows "last seen" after 10 minutes.
  Writers are best-effort (a read-only repo is fine).
- **`protected_paths`:** only **existing** files are protected; new files are allowed; `fnmatch` means
  `*` crosses `/`.
- **Artifact headers are brittle:** headers must precede the first blank line; a malformed verdict
  becomes `invalid` and blocks settlement.
- **Sessions are implicit state:** with `session.resume`, a marker resumes the same conversation across
  rounds; delete `.session-<role>` to reset. dsh has none.
- **`gh` is required** for `create`/`queue`/`labels`/`sync`/`merge` and transitions that comment/label
  or look up a PR; the test suites never need it.
- **Model ids drift** (`hosts/codex.json`'s `_note`): `model_tiers` is a snapshot.
- **`hosts/*.json` affects both tools**: swarm borrows the registry; `legio hosts --json` warns/skips
  invalid JSON, but a missing/malformed profile at run time is fatal.
- **Template ≠ deployed copy:** editing `centuria/` only affects future stations.
- **No cross-imports:** legio shells out to `.centuria/bin/*`; centuria has no host registry or legio
  import; swarm imports only its own package.

## 14. Doc map

| document | audience | update when |
|---|---|---|
| [`README.md`](README.md) | humans: pitch, quick start, cast, dashboard, swarm | user-facing behavior, commands, prerequisites, screenshots |
| `AGENTS.md` (this file) | agents/maintainers | any contract, stage, artifact, config key, host field, flag or test command changes |
| [`swarm/README.md`](swarm/README.md) | swarm users | flags, reviewers, exit codes, report format, library API |
| [`web/README.md`](web/README.md) | dashboard users/designers | endpoints, routes, heartbeat, asset pipeline, tests |
| `centuria/roles/*.md`, `hosts/*.json` `about`/`_note` | agents, operator | role behavior, surfaces, output contract; invocation, tiers, secrets |

Where a doc and the source disagree, prefer the source.
