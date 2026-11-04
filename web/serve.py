#!/usr/bin/env python3
"""Camp Legio — a local, read-only dashboard for legio's centuriae.

    python3 web/serve.py                 # real data from the discovered projects
    python3 web/serve.py --demo          # a fake camp, for design work
    python3 web/serve.py --port 8766 --root ~/dev

Serves web/ as static files and `GET /api/camp` as JSON. Strictly read-only:
it never writes to a project, never runs an agent and never transitions a job.
Standard library only; the only thing it shells out to is `centuria view`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
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
    "reviews", "cost_usd", "active", "waiting", "terminal", "human_reason",
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


def real_camp(root: str | None) -> dict:
    base = projects_root(root)
    projects = []
    if base.is_dir():
        for config in sorted(base.glob("*/.centuria/config.json")):
            projects.append(project_payload(config.parent.parent))
    return {"generated_at": now_iso(), "demo": False, "projects": projects}


# ---- demo camp -------------------------------------------------------------

def demo_cast() -> list[dict]:
    cast = parse_cast(REPO / ".centuria")
    if len(cast) == 8:
        return cast
    return [{"role": f"role-{i}", "function": "role", "title": f"Role {i}",
             "duty": "a generic duty line", "tier": "medium"} for i in range(8)]


def demo_job(id, issue, title, stage, round=1, pr=None, gate=None,
             reviews=None, active=False, waiting=False, terminal=False,
             human_reason=None, cost=0.0):
    return {"id": id, "issue": issue, "title": title, "stage": stage,
            "round": round, "round_limit": 3, "pr": pr, "gate": gate,
            "reviews": reviews or {}, "cost_usd": cost, "active": active,
            "waiting": waiting, "terminal": terminal,
            "human_reason": human_reason}


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
                             "build", active=True),
                    demo_job("005-status-api", 5, "Serve the camp status as JSON",
                             "spec", active=True),
                    demo_job("006-sketch-the-map", 7, "Sketch the camp map",
                             "build", active=True),
                    demo_job("007-name-the-tents", 8, "Name every tent",
                             "review", active=True),
                    demo_job("008-count-the-camp", 9, "Count the whole camp",
                             "gate", active=True),
                    demo_job("003-add-ui-to-legio", 4, "Add UI to legio",
                             "needs-human", waiting=True,
                             reviews={"probator": "PASS", "mensor": "CHANGES"},
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
    }


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

    def do_GET(self):
        target = urlsplit(self.path)
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
        if not candidate.is_file():
            self.reply(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = TYPES.get(candidate.suffix.lower(), "application/octet-stream")
        self.reply(200, candidate.read_bytes(), ctype)

    def do_HEAD(self):
        self.do_GET()

    def unsupported(self):
        self.reply(405, b'{"error":{"code":"method_not_allowed"}}',
                   "application/json")

    do_POST = do_PUT = do_PATCH = do_DELETE = unsupported
    do_OPTIONS = do_TRACE = do_CONNECT = unsupported


def build_server(port: int, demo: bool, root: str | None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.demo = demo
    httpd.root = root
    return httpd


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--root", default=None,
                        help="projects root (default: config.json projects_root)")
    parser.add_argument("--demo", action="store_true",
                        help="serve a fake camp instead of reading projects")
    args = parser.parse_args(argv)
    try:
        httpd = build_server(args.port, args.demo, args.root)
    except OSError as exc:
        print(f"camp: could not bind 127.0.0.1:{args.port}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    mode = "demo data" if args.demo else f"projects under {projects_root(args.root)}"
    print(f"Camp Legio on http://127.0.0.1:{httpd.server_port}  ({mode})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
