# swarm

A fixed cast of reviewers, one diff, one verdict. **swarm only does the review part.**

```bash
swarm run code-reviewer on ~/dev/webapp
swarm run all on ~/dev/webapp
```

It reads a diff, starts one agent per reviewer **at the same time**, and collects
one review file per reviewer into one report. There is no build, no round, no merge, no job
state: a run is diff in, review files out, and nothing survives except the report.

This is the review half of [centuria](../README.md), extracted as its own tool.
The difference is deliberate:

| | centuria | swarm |
|---|---|---|
| what it drives | issue → code → gate → review → merge | a diff → reviewers |
| state | `job.json`, stages, rounds | none |
| tree | a worktree per job | the repo you point it at |
| review output | one round folder inside a job | `review-<name>.md` per reviewer |
| failures | blocks the pipeline | becomes an `ERROR` row |

## Quick start

```bash
# from this checkout
./swarm/swarm run on ~/dev/webapp --host claude-code

# or put it on PATH
ln -s "$PWD/swarm/swarm" /usr/local/bin/swarm
```

The first run diffs the repo against `origin/main` (then `origin/HEAD`, `main`,
`master`, `HEAD~1` — the first base that is actually behind HEAD). Every run is
written to `<repo>/.swarm/<run-id>/`, and `.swarm/` goes into
`<repo>/.git/info/exclude`, never `.gitignore` — `git status` in that repo stays
clean and no tracked file changes, same policy as `legio add`.

## `swarm run`

```
swarm run [<reviewer> ...] [on] <repo> [flags]
```

The `on` is optional and purely for reading nicely; reviewers and the repo are
the only positionals. No reviewer named (or `all`) means every registered reviewer.

| flag | meaning |
|---|---|
| `--base <ref>` | diff base; default: first of `origin/main`, `origin/HEAD`, `main`, `master`, `HEAD~1` that is behind HEAD |
| `--head <ref>` | diff head; default `HEAD` |
| `--diff <path\|->` | review a patch you already have instead of computing one (`-` = stdin) |
| `--pr <n>` | review PR `#n` via `gh pr diff`; the PR body comes along as context |
| `--spec <path>` | issue/spec text as extra context (copied into the run folder) |
| `--host <name>` | host adapter; default from `config.json` (`claude-code`) |
| `--hosts-dir <dir>` | extra directory to search for host specs |
| `--risk low\|medium\|high` | moves **code-reviewer**'s tier only, like centuria's `route` |
| `--tier role=tier` | pin one reviewer's tier (repeatable) |
| `--jobs <n>` | how many agents at once; default: all of them |
| `--timeout <s>` | seconds per agent; default: the host's `timeout_seconds` |
| `--out <dir>` | output directory; default `<repo>/.swarm/<run-id>/` |
| `--yolo` | add the host's approval-skipping flags — **off by default** on purpose |
| `--dry-run` | print the exact commands and prompts, spawn nothing |
| `--json` | the report as JSON on stdout, nothing else |

Other commands: `swarm reviewers` (the cast and their tiers), `swarm hosts`
(every adapter swarm can see), `swarm version`.

**Exit codes:** `0` all PASS · `1` any CHANGES · `2` operational error (bad repo,
bad host, crashed reviewer) · `3` nothing to review (empty diff).

## The five reviewers

| name | tier | judges | from |
|---|---|---|---|
| `code-reviewer` | medium | correct, in scope, actually tested | probator |
| `security-reviewer` | strong | injection, privilege, leaks, dependencies | medicus |
| `ux-reviewer` | medium | can an ordinary user get through it | mensor |
| `ui-reviewer` | light | alignment, spacing, hierarchy, theme | librator |
| `ios-reviewer` | medium | Apple HIG conformance and App Store review risk | — (new) |

A full swarm is roughly one opus + three sonnets + one haiku. Each reviewer's
prompt is `roles/<name>.md`; the verdict contract is the same everywhere: the
**first line of the review file** is `VERDICT: PASS` or `VERDICT: CHANGES`, and
only problems that make the change unfit to merge may block.

A reviewer that crashes, times out, or writes no verdict does not take the others
down: it becomes an `ERROR` row, the rest are still collected and reported, and
the run exits 2.

## What a run leaves behind

```
<repo>/.swarm/<run-id>/
├── diff.patch           the exact change that was reviewed
├── context.md           --spec and/or the PR body (only when given)
├── review-<name>.md     what each agent wrote — the actual review
├── agent-<name>.log     the command's stdout/stderr, for when one fails
├── report.md            one table + the merged "must fix" list
└── report.json          the same, machine-readable (this is `--json`)
```

The run id is `<UTC timestamp>-<short head sha>`, so runs sort and never collide.

## Hosts

swarm does not have its own host registry: it borrows legio's `../hosts/*.json`
(claude-code, codex, dsh, gemini, echo, fake) and looks in `swarm/hosts/` first,
so `fake` — swarm's test harness — shadows legio's. A profile is a dozen fields;
`../hosts/claude-code.json` is the reference.

`--yolo` is the only way to get the approval-skipping flags, and it is off by
default: a non-interactive agent has to be pre-authorized or it stops to ask, but
those flags disable every prompt, so you opt in explicitly.

Secrets stay out of the JSON and out of your shell — the host's `env` block can
run a command at spawn time:

```json
"env": {"DEEPSEEK_API_KEY": {
  "shell": "security find-generic-password -a \"$USER\" -s deepseek-api -w"}}
```

## The library

The CLI is a thin wrapper; the seam is `review()`.

```python
from swarm.api import review

report = review(
    "~/dev/webapp",
    reviewers=["code-reviewer", "security-reviewer"],   # None = all
    base="origin/main",
    host="claude-code",
)
report.verdicts    # {"code-reviewer": "PASS", "security-reviewer": "CHANGES"}
report.overall     # "PASS" | "CHANGES" | "ERROR"
report.exit_code   # 0 | 1 | 2
report.must_fix()  # [(reviewer, item), ...]
report.to_dict()   # exactly what --json prints
```

Run it from the repo root (`python3 -c` or a script with the checkout on
`sys.path`); nothing is installed.

## Adding a reviewer

1. add `roles/<name>.md` (copy the shape of an existing one — the output contract
   at the bottom is what the parser reads)
2. add `"<name>": {"tier": "...", "about": "..."}` to `config.json`'s `reviewers`
3. nothing else: the CLI, the fan-out and the report are driven by that table

`swarm run <name> on <repo>` works the moment the entry exists; an unknown name
fails loudly with the list of valid ones.

## Testing swarm itself

`tests/fake-reviewer.py` plus `hosts/fake.json` run a whole five-reviewer swarm
with no model and no network:

```bash
python3 -m unittest discover -s swarm/tests -v
```

The fake reviewer writes the file an agent would write; `SWARM_FAKE_VERDICT=CHANGES[:<reviewer>]`
and `SWARM_FAKE_FAIL=<reviewer>|all` drive the CHANGES and crash paths. The suite
covers every verdict and exit code, `--pr`/`--diff`/`--spec` paths, single-reviewer
selection, `--jobs 1`, `--dry-run`, empty diffs, unknown reviewers and hosts, the
library import, and the fact that `git status` stays clean.

## Two habits worth keeping

**The prompt must never start with `-`.** When it goes in as argv, a leading dash
is parsed as an option (dsh once answered `unknown option` and echoed the whole
prompt back). `api._order()` therefore always starts with the `Swarm run:` header,
never with the role file's `---`.

**The diff goes in a file, not in argv.** A large patch on the command line is a
literal argument limit waiting to happen, and it bloats every log. Reviewers are
told to read `diff.patch`; the header only carries its path and shape.
