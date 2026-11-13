#!/usr/bin/env python3
"""Camp Legio — a local, read-only dashboard for legio's centuriae.

    python3 web/serve.py                 # real data from the discovered projects
    python3 web/serve.py --demo          # a fake camp, for design work
    python3 web/serve.py --port 8766 --root ~/dev

Serves web/ as static files (two skins: Principia at /principia/, the
default, and the original illustrated camp at /) and `GET /api/camp` as JSON.
Two guarded exceptions to read-only, both POST-only and only for this
dashboard's own page (Host allowlist on every request, a per-start token and
a matching Origin on every POST):

- Legatus (`/api/legatus*`) runs `claude -p` with read-only tools so the
  operator can ask about the camp; it writes only `.legatus/` here.
- Actions (`/api/action`) are operator-confirmed CLI calls: station an
  uncharted repo (`legio add`), send feedback to or reject a waiting job
  (`.centuria/bin/job feedback|reject`). Never merge.

Everything else is strictly read-only:
it never writes to a project, never runs an agent and never transitions a job.
Standard library only; the only thing it shells out to is `centuria view`.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

WEB = Path(__file__).resolve().parent
REPO = WEB.parent
READ_TIMEOUT = 5          # seconds per `centuria view`
LIVE_STALE = 600          # a live.json older than this is "last seen", not live

# the only job fields the browser is allowed to see
# the cast in pipeline order, not alphabetical
ROLE_ORDER = (
    "tesserarius", "signifer", "fabri", "probator", "medicus", "mensor",
    "librator", "primus-pilus",
)

JOB_FIELDS = (
    "id", "issue", "title", "stage", "round", "round_limit", "pr", "gate",
    "reviews", "roster", "cost_usd", "active", "waiting", "terminal",
    "human_reason",
)

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def projects_root(root: str | None) -> Path:
    if root:
        return Path(root).expanduser()
    config = REPO / "config.json"
    try:
        return Path(json.loads(config.read_text())["projects_root"]).expanduser()
    except (OSError, KeyError, ValueError):
        return Path.home() / "dev"


def parse_cast(centuria: Path) -> list[dict]:
    """Read the eight role files: name, function, title, duty, tier."""
    out = []
    roles = sorted((centuria / "roles").glob("*.md"))
    for path in roles:
        text = path.read_text(errors="replace")
        meta: dict[str, str] = {}
        if text.startswith("---"):
            try:
                _, front, _ = text.split("---", 2)
            except ValueError:
                front = ""
            for line in front.strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()
        heading = re.search(r"^#\s+(.+)$", text, re.M)
        title = heading.group(1).strip() if heading else meta.get("role", path.stem)
        quote = [line[1:].strip() for line in text.splitlines()
                 if line.startswith(">")]
        duty_lines = [line for line in quote if "this line is the job" not in line]
        duty = re.sub(r"\*\*", "", " ".join(duty_lines)).strip()
        out.append({
            "role": meta.get("role", path.stem),
            "function": meta.get("function", ""),
            "title": title,
            "duty": duty,
            "tier": meta.get("model_tier", ""),
        })
    out.sort(key=lambda entry: (ROLE_ORDER.index(entry["role"])
                               if entry["role"] in ROLE_ORDER else 99))
    return out


# ---- job artifacts (read-only scrolls) -------------------------------------

ARTIFACT_CAP = {"md": 96_000, "log": 64_000}
ARTIFACT_MAIN = ("issue.md", "intake.md", "spec.md", "build.md", "decision.md",
                 "rejection.md")


def allowed_artifact(rel: str) -> bool:
    if rel in ARTIFACT_MAIN:
        return True
    for pattern in ("feedback-*.md", "round-*/checks.md", "round-*/review-*.md",
                    "agent-*-*.log"):
        if fnmatch.fnmatch(rel, pattern):
            return True
    return False


def stationed_configs(base: Path) -> list[Path]:
    """The config of each stationed project under the root.

    A folder whose name starts with `~` (archives, third-party clones) is not a project.
    """
    return [c for c in sorted(base.glob("*/.centuria/config.json"))
            if not c.parent.parent.name.startswith("~")]


def resolve_job_dir(root: str | None, name: str, job: str) -> Path:
    base = projects_root(root)
    project = None
    if base.is_dir():
        for config in stationed_configs(base):
            if config.parent.parent.name == name:
                project = config.parent.parent
                break
    if project is None:
        raise LookupError("unknown project")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", job or ""):
        raise LookupError("invalid job id")
    job_dir = project / ".centuria" / "jobs" / job
    if not job_dir.is_dir():
        raise LookupError("unknown job")
    return job_dir


def artifact_sort(rel: str) -> tuple:
    if rel in ARTIFACT_MAIN:
        return (0, ARTIFACT_MAIN.index(rel), rel)
    if rel.endswith(".log"):
        return (3, 0, rel)
    if rel.startswith("round-"):
        return (2, 0, rel)
    return (1, 0, rel)


def list_artifacts(job_dir: Path) -> list[dict]:
    files = []
    for path in job_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(job_dir).as_posix()
        if not allowed_artifact(rel):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        files.append({"path": rel, "size": size,
                      "kind": "log" if rel.endswith(".log") else "artifact"})
    files.sort(key=lambda item: artifact_sort(item["path"]))
    return files


def read_artifact(job_dir: Path, rel: str) -> dict:
    if not allowed_artifact(rel):
        raise LookupError("not a scroll")
    path = (job_dir / rel).resolve()
    try:
        path.relative_to(job_dir.resolve())
    except ValueError:
        raise LookupError("not a scroll") from None
    if not path.is_file():
        raise LookupError("no such scroll")
    data = path.read_bytes()
    total = len(data)
    cap = ARTIFACT_CAP["log"] if rel.endswith(".log") else ARTIFACT_CAP["md"]
    truncated = total > cap
    if truncated:
        if rel.endswith(".log"):
            data = data[-cap:]
            header = (f"… showing the last {cap // 1024} KB of a "
                      f"{total // 1024} KB log …\n\n").encode()
            data = header + data
        else:
            data = data[:cap]
    text = data.decode("utf-8", errors="replace")
    return {"path": rel, "size": total, "truncated": truncated, "text": text}


def read_jobs(project: Path) -> list[dict]:
    centuria = project / ".centuria" / "bin" / "centuria"
    res = subprocess.run(
        [str(centuria), "view"], cwd=str(project), capture_output=True,
        text=True, timeout=READ_TIMEOUT,
    )
    if res.returncode != 0:
        detail = (res.stderr or res.stdout).strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "centuria view failed")
    try:
        jobs = json.loads(res.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("centuria view returned invalid JSON") from None
    if not isinstance(jobs, list):
        raise RuntimeError("centuria view returned something other than a list")
    return [{key: job.get(key) for key in JOB_FIELDS} for job in jobs
            if isinstance(job, dict)]


def read_lives(project: Path) -> list[dict]:
    """Every live.json under this project's job folders, freshest first.

    Concurrency > 1 means several jobs can be working at the same time, so
    this is a list, not "the newest one"; the dashboard shows all of them.
    """
    found: list[dict] = []
    for path in (project / ".centuria" / "jobs").glob("*/live.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        started = data.get("started")
        try:
            age = max(0, int(time.time() - datetime.fromisoformat(
                started.replace("Z", "+00:00")).timestamp()))
        except (AttributeError, ValueError):
            age = LIVE_STALE + 1
        roles = data.get("roles")
        if not isinstance(roles, list):
            roles = [data["role"]] if isinstance(data.get("role"), str) else []
        candidate = {
            "roles": [role for role in roles if isinstance(role, str)],
            "round": data.get("round"),
            "started": started,
            "job": path.parent.name,
            "age_seconds": age,
            "stale": age > LIVE_STALE,
        }
        found.append(candidate)
    found.sort(key=lambda item: item["age_seconds"])
    return found


def project_payload(path: Path) -> dict:
    lives: list[dict] = []
    try:
        jobs = read_jobs(path)
        lives = read_lives(path)
        ok, error = True, None
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        jobs, ok, error = [], False, str(exc)
    try:
        cast = parse_cast(path / ".centuria")
    except OSError:
        cast = []
    return {
        "name": path.name,
        "path": str(path),
        "ok": ok,
        "error": error,
        "jobs": jobs,
        "cast": cast,
        "lives": lives,
    }


def find_uncharted(base: Path) -> list[dict]:
    """Git repositories under the root that have no centuria yet.

    Only names and paths: the dashboard shows them so you can station one
    (`legio add <path>`); it never looks inside them.
    """
    found = []
    if not base.is_dir():
        return found
    for child in sorted(base.iterdir()):
        try:
            if (child.is_dir() and not child.name.startswith((".", "~"))
                    and (child / ".git").exists()
                    and not (child / ".centuria" / "config.json").is_file()):
                found.append({"name": child.name, "path": str(child)})
        except OSError:
            continue
    return found


def real_camp(root: str | None) -> dict:
    base = projects_root(root)
    projects = []
    if base.is_dir():
        for config in stationed_configs(base):
            projects.append(project_payload(config.parent.parent))
    return {"generated_at": now_iso(), "demo": False, "projects": projects,
            "uncharted": find_uncharted(base)}


# ---- demo camp -------------------------------------------------------------

def demo_cast() -> list[dict]:
    cast = parse_cast(REPO / ".centuria")
    if len(cast) == 8:
        return cast
    return [{"role": f"role-{i}", "function": "role", "title": f"Role {i}",
             "duty": "a generic duty line", "tier": "medium"} for i in range(8)]


def demo_job(id, issue, title, stage, round=1, pr=None, gate=None,
             reviews=None, active=False, waiting=False, terminal=False,
             human_reason=None, cost=0.0, roster=None):
    return {"id": id, "issue": issue, "title": title, "stage": stage,
            "round": round, "round_limit": 3, "pr": pr, "gate": gate,
            "reviews": reviews or {}, "cost_usd": cost, "active": active,
            "waiting": waiting, "terminal": terminal,
            "human_reason": human_reason, "roster": roster}


def demo_camp() -> dict:
    cast = demo_cast()
    return {
        "generated_at": now_iso(),
        "demo": True,
        "projects": [
            {
                "name": "legio", "path": "", "ok": True, "error": None,
                "jobs": [
                    demo_job("004-camp-ui", 6, "Camp Legio: a cozy camp UI",
                             "build", active=True,
                             roster={"reviewers": {"probator": "medium",
                                                   "medicus": "strong"}}),
                    demo_job("005-status-api", 5, "Serve the camp status as JSON",
                             "spec", active=True),
                    demo_job("006-sketch-the-map", 7, "Sketch the camp map",
                             "build", active=True),
                    demo_job("007-name-the-tents", 8, "Name every tent",
                             "review", active=True,
                             reviews={"probator": "PASS", "mensor": "CHANGES"},
                             roster={"reviewers": {"probator": "medium",
                                                   "mensor": "medium"}}),
                    demo_job("008-count-the-camp", 9, "Count the whole camp",
                             "gate", active=True),
                    demo_job("003-add-ui-to-legio", 4, "Add UI to legio",
                             "needs-human", waiting=True, round=2, pr=9,
                             reviews={"probator": "PASS", "mensor": "PASS"},
                             gate="PASS", human_reason="approved - merge the PR", cost=1.42),
                    demo_job("001-add-a-json-flag", 1, "Add a --json flag to legio hosts",
                             "merged", pr=2, gate="PASS", terminal=True,
                             reviews={"probator": "PASS"}, cost=0.87),
                ],
                "cast": cast,
                "lives": [
                    {"roles": ["fabri"], "round": 1, "started": now_iso(),
                     "job": "004-camp-ui", "age_seconds": 6, "stale": False},
                    {"roles": ["signifer"], "round": 1, "started": now_iso(),
                     "job": "005-status-api", "age_seconds": 19, "stale": False},
                ],
            },
            {
                "name": "seamless", "path": "", "ok": True, "error": None,
                "jobs": [
                    demo_job("001-build-seamless", 1, "Generate the Xcode project",
                             "review", active=True,
                             reviews={"probator": "PASS"}),
                    demo_job("002-onboarding", 2, "Add a first-run onboarding",
                             "needs-info", waiting=True,
                             human_reason="waiting for the author", round=2),
                ],
                "cast": cast,
                "lives": [{"roles": ["medicus", "probator"], "round": 1,
                           "started": now_iso(), "job": "001-build-seamless",
                           "age_seconds": 21, "stale": False}],
            },
            {
                "name": "webapp", "path": "", "ok": True, "error": None,
                "jobs": [
                    demo_job("001-login", 1, "Add a login screen", "spec",
                             waiting=False, active=True),
                ],
                "cast": cast,
                "lives": [],
            },
            {
                "name": "broken", "path": "", "ok": False,
                "error": "centuria view timed out", "jobs": [], "cast": [],
                "lives": [],
            },
        ],
        "uncharted": [{"name": name, "path": f"~/dev/{name}"}
                      for name in ("blog", "dotfiles", "notes-api")],
    }


DEMO_SCROLLS = {
    "004-camp-ui": {
        "issue.md": "# Issue #6: Camp Legio\n\nA local dashboard for the centuriae.\n",
        "spec.md": "SPEC: READY\n\n## Summary\n- Serve the camp as one page.\n"
                   "- Show one tent per project.\n- Put the working role at the desk.\n",
        "build.md": "STATUS: READY\n\n## Work completed\n- camp scene, board, cast.\n"
                    "- stdlib server, read-only.\n",
        "round-1/checks.md": "GATE: PASS\n\npython3 -m unittest discover -s web/tests\n"
                             "Ran 15 tests ... OK\n",
        "round-1/review-probator.md": "VERDICT: PASS\n\nIn scope and tested.\n",
        "agent-1-fabri.log": "$ codex exec ...\n--- stdout ---\nwrote web/, 43 assets, 15 tests\n",
    },
    "003-add-ui-to-legio": {
        "issue.md": "# Issue #4: Add UI to legio\n\nA local read-only page for every centuria.\n",
        "intake.md": "DECISION: ACCEPT\nRISK: low\nSURFACES: ui\nRESCOPED: no\n\n"
                     "Small, self-contained change in web/.\n",
        "spec.md": "SPEC: READY\n\n## Goals\n- serve.py on 127.0.0.1\n"
                   "- GET /api/camp, read-only\n## Non-goals\n- No write endpoints\n",
        "build.md": "STATUS: READY\n\n## Round 2\n- Fixed the two failing tests.\n",
        "round-1/checks.md": "GATE: FAIL\nCOMMIT: 1c07f9e\n\nRan 15 tests, 2 failures\n",
        "round-2/checks.md": "GATE: PASS\nCOMMIT: 4b81d0a\n\nRan 15 tests ... OK\n",
        "round-2/review-probator.md": "VERDICT: PASS\n\nRead-only by construction.\n",
        "round-2/review-mensor.md": "VERDICT: PASS\n\nLabels no longer overlap.\n",
        "decision.md": "APPROVE\n\nChecks and both reviews pass; merge PR #9 when ready.\n",
    },
    "007-name-the-tents": {
        "issue.md": "# Issue #8: Name every tent\n\nEach tent shows its project name.\n",
        "intake.md": "DECISION: ACCEPT\nRISK: low\nSURFACES: ui\nRESCOPED: no\n",
        "spec.md": "SPEC: READY\n\n- A banner over every tent.\n",
        "build.md": "STATUS: READY\n\nBanners added.\n",
        "round-1/checks.md": "GATE: PASS\nCOMMIT: 77aa012\n\nOK\n",
        "round-1/review-probator.md": "VERDICT: PASS\n\nLooks right.\n",
        "round-1/review-mensor.md": "VERDICT: CHANGES\n\nThe banner wraps on narrow tents.\n",
    },
}


def demo_job_payload(name: str, job: str) -> dict:
    if job not in DEMO_SCROLLS:
        raise LookupError("unknown job")
    files = [{"path": rel, "size": len(text.encode()),
              "kind": "log" if rel.endswith(".log") else "artifact"}
             for rel, text in sorted(DEMO_SCROLLS[job].items(),
                                     key=lambda item: artifact_sort(item[0]))]
    return {"project": name, "job": job, "files": files}


# ---- Legatus: the operator's agent ------------------------------------------
#
# The only part of the server that runs a process or writes a file. It runs
# Claude Code non-interactively (`claude -p`) on the operator's own login, in
# the legio checkout, with read-only tools; it never acts on a project. Its
# state (one conversation id + the transcript) lives in .legatus/ in the
# legio checkout, which git ignores.

LEGATUS_MODEL = "claude-opus-5-5"
LEGATUS_TIMEOUT = 600            # seconds per answer
LEGATUS_MAX_CHARS = 8000         # per question
LEGATUS_STATE = REPO / ".legatus"
LEGATUS_ROLE = WEB / "legatus.md"
# read-only: files, and commands that only look
LEGATUS_TOOLS = (
    "Read", "Glob", "Grep",
    "Bash(./legio status:*)", "Bash(./legio inbox:*)", "Bash(./legio ls:*)",
    "Bash(./legio hosts:*)", "Bash(./legio next:*)", "Bash(./legio doctor:*)",
    "Bash(./legio version:*)",
    "Bash(git log:*)", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git show:*)",
    "Bash(gh pr view:*)", "Bash(gh pr list:*)", "Bash(gh pr diff:*)",
    "Bash(gh issue view:*)", "Bash(gh issue list:*)",
)
LEGATUS_DENY = ("Write", "Edit", "NotebookEdit")


class LegatusBusy(Exception):
    pass


def legatus_config() -> dict:
    try:
        cfg = json.loads((REPO / "config.json").read_text()).get("legatus")
    except (OSError, ValueError, AttributeError):
        cfg = None
    return cfg if isinstance(cfg, dict) else {}


class Legatus:
    """One ongoing Claude Code conversation, asked one question at a time."""

    def __init__(self, root: str | None, *, command=None, model: str | None = None,
                 state_dir: Path | None = None, enabled: bool = True,
                 reason: str | None = None):
        self.root = root
        self.command = list(command or ["claude"])
        self.model = model or LEGATUS_MODEL
        self.state_dir = Path(state_dir or LEGATUS_STATE)
        self.enabled = enabled
        self.reason = reason
        self.token = secrets.token_urlsafe(24)   # only a same-origin page can read it
        self.lock = threading.Lock()

    @classmethod
    def off(cls, reason: str) -> "Legatus":
        return cls(None, enabled=False, reason=reason)

    # -- state
    def _read(self, name, default):
        try:
            return json.loads((self.state_dir / name).read_text())
        except (OSError, ValueError):
            return default

    def _write(self, name, data):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_dir / f"{name}.tmp"
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.state_dir / name)

    def session(self) -> dict:
        found = self._read("session.json", None)
        if isinstance(found, dict) and found.get("id"):
            return found
        fresh = {"id": str(uuid.uuid4()), "started": False}
        self._write("session.json", fresh)
        return fresh

    def transcript(self) -> list:
        found = self._read("transcript.json", [])
        return found if isinstance(found, list) else []

    def payload(self) -> dict:
        return {"enabled": self.enabled, "reason": self.reason, "model": self.model,
                "busy": self.lock.locked(), "token": self.token if self.enabled else None,
                "messages": self.transcript()[-200:] if self.enabled else []}

    # -- talking
    def argv(self, session: dict) -> list[str]:
        cmd = [*self.command, "-p", "--output-format", "json", "--model", self.model,
               "--append-system-prompt-file", str(LEGATUS_ROLE),
               "--permission-mode", "default"]
        cmd += ["--resume", session["id"]] if session.get("started") else ["--session-id", session["id"]]
        cmd += ["--add-dir", str(projects_root(self.root))]
        cmd += ["--allowedTools", *LEGATUS_TOOLS]
        cmd += ["--disallowedTools", *LEGATUS_DENY]
        return cmd

    def _run(self, session: dict, prompt: str) -> tuple[bool, str, float | None]:
        try:
            res = subprocess.run(self.argv(session), input=prompt, cwd=str(REPO),
                                 capture_output=True, text=True, timeout=LEGATUS_TIMEOUT)
        except FileNotFoundError:
            return False, f"`{self.command[0]}` is not installed or not on PATH.", None
        except subprocess.TimeoutExpired:
            return False, f"No answer within {LEGATUS_TIMEOUT // 60} minutes.", None
        data = None
        for line in reversed(res.stdout.strip().splitlines()):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
        if isinstance(data, dict) and not data.get("is_error") and isinstance(data.get("result"), str):
            cost = data.get("total_cost_usd")
            return True, data["result"], cost if isinstance(cost, (int, float)) else None
        detail = (data or {}).get("result") if isinstance(data, dict) else None
        if not detail:
            lines = (res.stderr or res.stdout).strip().splitlines()
            detail = lines[-1] if lines else f"claude exited with {res.returncode}"
        return False, str(detail), None

    def ask(self, text: str, context: str = "") -> dict:
        if not self.lock.acquire(blocking=False):
            raise LegatusBusy()
        try:
            session = self.session()
            prompt = (f"Context: {context}\n\n" if context else "") + text
            started = time.time()
            ok, answer, cost = self._run(session, prompt)
            if not ok and session.get("started") and "conversation" in answer.lower():
                session = {"id": str(uuid.uuid4()), "started": False}   # the old one is gone
                ok, answer, cost = self._run(session, prompt)
            if ok:
                session["started"] = True
            self._write("session.json", session)
            reply = {"role": "legatus" if ok else "error", "text": answer,
                     "at": int(time.time() * 1000),
                     "seconds": round(time.time() - started, 1)}
            if cost is not None:
                reply["cost_usd"] = cost
            log = self.transcript()
            log.append({"role": "user", "text": text, "context": context,
                        "at": int(started * 1000)})
            log.append(reply)
            self._write("transcript.json", log[-400:])
            return reply
        finally:
            self.lock.release()

    def reset(self) -> None:
        if not self.lock.acquire(blocking=False):
            raise LegatusBusy()
        try:
            self._write("session.json", {"id": str(uuid.uuid4()), "started": False})
            self._write("transcript.json", [])
        finally:
            self.lock.release()


def make_legatus(root: str | None, demo: bool, wanted: bool, model: str | None) -> Legatus:
    if not wanted:
        return Legatus.off("Legatus is turned off (--no-legatus).")
    if demo:
        return Legatus.off("Legatus is off in demo mode: he would read your real projects.")
    cfg = legatus_config()
    command = cfg.get("command") if isinstance(cfg.get("command"), list) else ["claude"]
    if not shutil.which(command[0]):
        return Legatus.off(f"`{command[0]}` was not found on PATH. Install Claude Code and sign in.")
    return Legatus(root, command=command, model=model or cfg.get("model") or LEGATUS_MODEL)


# ---- actions: operator-confirmed CLI calls -----------------------------------
#
# The dashboard never edits a project itself: each action runs the same CLI the
# operator would type, so the pipeline's own guards (stage checks, locks,
# "already stationed") still apply. Targets must be things the server found
# itself. Merging is deliberately not an action (golden rule 2).

ACTION_TIMEOUT = 120
ACTION_TEXT_MAX = 4000
STATION_HIDDEN_HOSTS = {"fake"}   # golden rule 9: never point fake at a real project


def host_profiles() -> list[dict]:
    out = []
    for path in sorted((REPO / "hosts").glob("*.json")):
        try:
            prof = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        name = prof.get("host", path.stem) if isinstance(prof, dict) else path.stem
        if name in STATION_HIDDEN_HOSTS or not isinstance(prof, dict):
            continue
        out.append({"name": name, "about": prof.get("about", ""),
                    "untested": bool(prof.get("untested"))})
    return out


def find_project(root: str | None, name: str) -> Path | None:
    base = projects_root(root)
    if not base.is_dir():
        return None
    for config in stationed_configs(base):
        if config.parent.parent.name == name:
            return config.parent.parent
    return None


class ActionError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Actions:
    def __init__(self, root: str | None, *, legio=None, enabled: bool = True,
                 reason: str | None = None):
        self.root = root
        self.legio = list(legio or [str(REPO / "legio")])
        self.enabled = enabled
        self.reason = reason
        self.lock = threading.Lock()

    def payload(self) -> dict:
        hosts = host_profiles()
        names = [h["name"] for h in hosts]
        return {"enabled": self.enabled, "reason": self.reason, "hosts": hosts,
                "default_host": "claude-code" if "claude-code" in names else (names[0] if names else None)}

    def plan(self, body: dict) -> tuple[list[str], Path, str | None, str]:
        """Check one request against what the server knows; return argv, cwd, stdin, label."""
        action = body.get("action")
        if action == "station":
            path = str(body.get("path", ""))
            host = str(body.get("host", ""))
            if path not in {u["path"] for u in find_uncharted(projects_root(self.root))}:
                raise ActionError(400, "not_uncharted",
                                  "Only a repo listed under Terra incognita can be stationed.")
            if host not in {h["name"] for h in host_profiles()}:
                raise ActionError(400, "bad_host", f"Unknown host {host!r}.")
            return ([*self.legio, "add", path, "--host", host], REPO, None,
                    f"legio add {path} --host {host}")
        if action in ("say", "reject"):
            name = str(body.get("project", ""))
            job_id = str(body.get("job", ""))
            project = find_project(self.root, name)
            if project is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", job_id):
                raise ActionError(404, "not_found", "Unknown project or job.")
            try:
                jobs = read_jobs(project)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                raise ActionError(502, "read_failed", str(exc)) from None
            job = next((j for j in jobs if j.get("id") == job_id), None)
            if job is None:
                raise ActionError(404, "not_found", "Unknown job.")
            text = str(body.get("text", "")).strip()
            if len(text) > ACTION_TEXT_MAX:
                raise ActionError(400, "bad_text", f"Keep it under {ACTION_TEXT_MAX} characters.")
            if action == "say":
                if job.get("stage") != "needs-human":
                    raise ActionError(409, "wrong_stage",
                                      f"Feedback only goes to a job that needs you (this one is {job.get('stage')}).")
                if not text:
                    raise ActionError(400, "bad_text", "Write the feedback first.")
                verb = "feedback"
            else:
                if job.get("stage") not in ("needs-info", "needs-human"):
                    raise ActionError(409, "wrong_stage",
                                      f"Only a waiting job can be rejected (this one is {job.get('stage')}).")
                text = text or "rejected by the operator"
                verb = "reject"
            bin_job = project / ".centuria" / "bin" / "job"
            return ([str(bin_job), verb, job_id], project, text + "\n",
                    f"legio {'say' if action == 'say' else 'reject'} {name}:{job_id}")
        raise ActionError(400, "bad_action", "Unknown action.")

    def run(self, body: dict) -> dict:
        argv, cwd, stdin, label = self.plan(body)
        if not self.lock.acquire(blocking=False):
            raise ActionError(409, "busy", "Another action is still running.")
        try:
            res = subprocess.run(argv, cwd=str(cwd), input=stdin, capture_output=True,
                                 text=True, timeout=ACTION_TIMEOUT)
        except FileNotFoundError:
            raise ActionError(502, "missing", f"{argv[0]} was not found.") from None
        except subprocess.TimeoutExpired:
            raise ActionError(504, "timeout", f"{label} took longer than {ACTION_TIMEOUT} s.") from None
        finally:
            self.lock.release()
        output = "\n".join(((res.stdout or "") + (res.stderr or "")).strip().splitlines()[-40:])
        return {"ok": res.returncode == 0, "code": res.returncode, "command": label, "output": output}


# ---- http ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "CampLegio/0.1"

    def log_message(self, *_args):
        pass

    def reply(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self) -> bool:
        """DNS rebinding guard: only answer requests addressed to this machine."""
        return bool(re.fullmatch(r"(127\.0\.0\.1|localhost|\[::1\])(:\d+)?",
                                 self.headers.get("Host", "")))

    def do_GET(self):
        if not self.host_ok():
            self.reply(403, b"this dashboard only answers 127.0.0.1 and localhost",
                       "text/plain; charset=utf-8")
            return
        target = urlsplit(self.path)
        if target.path == "/api/actions":
            data = self.server.actions.payload()
            data["token"] = self.server.token
            self.reply(200, json.dumps(data).encode(), "application/json")
            return
        if target.path in ("/api/job", "/api/job/file"):
            self.serve_scroll(target)
            return
        if target.path == "/api/legatus":
            self.reply(200, json.dumps(self.server.legatus.payload()).encode(),
                       "application/json")
            return
        if target.path == "/api/camp":
            try:
                data = demo_camp() if self.server.demo else real_camp(self.server.root)
            except Exception as exc:  # never leak a traceback to the browser
                self.reply(502, json.dumps(
                    {"error": {"code": "camp_read_failed",
                               "message": str(exc)}}).encode(),
                    "application/json")
                return
            self.reply(200, json.dumps(data).encode(), "application/json")
            return
        path = target.path
        if path in ("/", "/index.html"):
            path = "/index.html"
        candidate = (WEB / path.lstrip("/")).resolve()
        if WEB.resolve() not in candidate.parents and candidate != WEB.resolve():
            self.reply(404, b"not found", "text/plain; charset=utf-8")
            return
        if candidate.is_dir() and (candidate / "index.html").is_file():
            if not path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            candidate = candidate / "index.html"
        if not candidate.is_file():
            self.reply(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = TYPES.get(candidate.suffix.lower(), "application/octet-stream")
        self.reply(200, candidate.read_bytes(), ctype)

    def serve_scroll(self, target):
        from urllib.parse import parse_qsl
        query = dict(parse_qsl(target.query, keep_blank_values=True))
        name = query.get("project", "")
        job = query.get("job", "")
        if not name or not job:
            self.reply(400, json.dumps({"error": {
                "code": "bad_query", "message": "project and job are required"}}).encode(),
                "application/json")
            return
        try:
            if self.server.demo:
                payload = demo_job_payload(name, job)
                if target.path == "/api/job/file":
                    rel = query.get("path", "")
                    text = DEMO_SCROLLS[job].get(rel)
                    if text is None:
                        raise LookupError("no such scroll")
                    payload = {"path": rel, "size": len(text.encode()),
                               "truncated": False, "text": text}
            else:
                job_dir = resolve_job_dir(self.server.root, name, job)
                if target.path == "/api/job":
                    payload = {"project": name, "job": job,
                               "files": list_artifacts(job_dir)}
                else:
                    payload = read_artifact(job_dir, query.get("path", ""))
        except LookupError as exc:
            self.reply(404, json.dumps({"error": {
                "code": "not_found", "message": str(exc)}}).encode(),
                "application/json")
            return
        except OSError as exc:
            self.reply(502, json.dumps({"error": {
                "code": "scroll_read_failed", "message": str(exc)}}).encode(),
                "application/json")
            return
        self.reply(200, json.dumps(payload).encode(), "application/json")

    def do_HEAD(self):
        self.do_GET()

    def unsupported(self):
        self.reply(405, b'{"error":{"code":"method_not_allowed"}}',
                   "application/json")

    def fail(self, status: int, code: str, message: str):
        self.reply(status, json.dumps({"error": {"code": code, "message": message}}).encode(),
                   "application/json")

    def read_post(self) -> dict | None:
        """The guard every POST passes: our Host, our Origin, JSON, a sane size, our token."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if not self.host_ok() or (origin is not None and origin != f"http://{host}"):
            self.fail(403, "forbidden", "Only this dashboard's own page may do that.")
            return None
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self.fail(415, "json_only", "Send JSON.")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 4 * LEGATUS_MAX_CHARS:
            self.fail(400, "bad_body", "Empty or too long.")
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self.fail(400, "bad_body", "Not JSON.")
            return None
        if not isinstance(body, dict):
            self.fail(400, "bad_body", "Not a JSON object.")
            return None
        if not secrets.compare_digest(str(body.get("token", "")), self.server.token):
            self.fail(403, "bad_token", "Reload the page and try again.")
            return None
        return body

    def do_POST(self):
        """Only Legatus and the confirmed actions take a POST."""
        path = urlsplit(self.path).path
        if path not in ("/api/legatus/ask", "/api/legatus/reset", "/api/action"):
            self.unsupported()
            return
        body = self.read_post()
        if body is None:
            return
        if path == "/api/action":
            actions = self.server.actions
            if not actions.enabled:
                self.fail(503, "actions_off", actions.reason or "Actions are off.")
                return
            try:
                result = actions.run(body)
            except ActionError as exc:
                self.fail(exc.status, exc.code, exc.message)
                return
            self.reply(200, json.dumps(result).encode(), "application/json")
            return
        legatus = self.server.legatus
        if not legatus.enabled:
            self.fail(503, "legatus_off", legatus.reason or "Legatus is off.")
            return
        try:
            if path == "/api/legatus/reset":
                legatus.reset()
                self.reply(200, json.dumps({"ok": True}).encode(), "application/json")
                return
            text = str(body.get("text", "")).strip()
            if not text or len(text) > LEGATUS_MAX_CHARS:
                self.fail(400, "bad_text", f"Ask something up to {LEGATUS_MAX_CHARS} characters long.")
                return
            context = str(body.get("context", ""))[:300]
            reply = legatus.ask(text, context)
        except LegatusBusy:
            self.fail(409, "busy", "Legatus is still answering the last question.")
            return
        except OSError as exc:
            self.fail(502, "legatus_failed", str(exc))
            return
        self.reply(200, json.dumps({"message": reply}).encode(), "application/json")

    do_PUT = do_PATCH = do_DELETE = unsupported
    do_OPTIONS = do_TRACE = do_CONNECT = unsupported


def build_server(port: int, demo: bool, root: str | None,
                 legatus: Legatus | None = None,
                 actions: Actions | None = None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.demo = demo
    httpd.root = root
    httpd.token = secrets.token_urlsafe(24)   # one per start; only our own page can read it
    httpd.legatus = legatus or Legatus.off("Legatus is not set up on this server.")
    httpd.legatus.token = httpd.token
    httpd.actions = actions or Actions(root, enabled=False, reason="Actions are not set up on this server.")
    return httpd


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--root", default=None,
                        help="projects root (default: config.json projects_root)")
    parser.add_argument("--demo", action="store_true",
                        help="serve a fake camp instead of reading projects")
    parser.add_argument("--no-legatus", action="store_true",
                        help="turn off Legatus (the claude-backed agent panel)")
    parser.add_argument("--no-actions", action="store_true",
                        help="no buttons that change anything (station, feedback, reject)")
    parser.add_argument("--legatus-model", default=None,
                        help=f"model for Legatus (default: config.json legatus.model or {LEGATUS_MODEL})")
    args = parser.parse_args(argv)
    legatus = make_legatus(args.root, args.demo, not args.no_legatus, args.legatus_model)
    if args.demo:
        actions = Actions(args.root, enabled=False, reason="Actions are off in demo mode.")
    elif args.no_actions:
        actions = Actions(args.root, enabled=False, reason="Actions are turned off (--no-actions).")
    else:
        actions = Actions(args.root)
    try:
        httpd = build_server(args.port, args.demo, args.root, legatus, actions)
    except OSError as exc:
        print(f"camp: could not bind 127.0.0.1:{args.port}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    mode = "demo data" if args.demo else f"projects under {projects_root(args.root)}"
    print(f"Camp Legio on http://127.0.0.1:{httpd.server_port}  ({mode})")
    print(f"Legatus: {legatus.model}" if legatus.enabled else f"Legatus: off. {legatus.reason}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
