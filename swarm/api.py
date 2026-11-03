"""swarm — review one diff with a fixed cast of reviewers.

A run is `diff in, N review files out`. There is no job, no round, no state to
resume: the reviewers are single-shot processes, and the report is the whole
memory of the run. The CLI (`swarm`) is a thin wrapper over review(); embed this
module when you want the same thing from Python.

    from swarm.api import review
    report = review("~/dev/webapp", reviewers=["code-reviewer"], base="origin/main")
    report.overall          # "PASS" | "CHANGES" | "ERROR"
    report.exit_code        # 0 | 1 | 2
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # `python3 swarm/swarm` puts swarm/ itself on sys.path
    from . import hostkit
except ImportError:  # imported flat, as the CLI does
    import hostkit

HERE = Path(__file__).resolve().parent

VERDICT_PASS = "PASS"
VERDICT_CHANGES = "CHANGES"
VERDICT_ERROR = "ERROR"
VERDICT_DRY = "DRY"

EXIT = {VERDICT_PASS: 0, VERDICT_CHANGES: 1, VERDICT_ERROR: 2, VERDICT_DRY: 0}

_FIRST_VERDICT = re.compile(r"^\s*VERDICT:\s*(PASS|CHANGES)\b", re.IGNORECASE)
_MUST_FIX = re.compile(r"^##[ \t]*Must fix[ \t]*$", re.MULTILINE | re.IGNORECASE)
_NEXT_SECTION = re.compile(r"^##[ \t]", re.MULTILINE)
_NUMBERING = re.compile(r"^(?:[-*]|\d+[.)])[ \t]+")


class SwarmError(Exception):
    """Anything that stops a run before or between reviewers are spawned."""


class NothingToReview(SwarmError):
    """The diff is empty: there is nothing to judge."""


# ---- config and hosts ------------------------------------------------------


def load_config(path=None):
    p = Path(path) if path else HERE / "config.json"
    try:
        cfg = json.loads(p.read_text())
    except FileNotFoundError:
        raise SwarmError(f"config file {p} is missing")
    except json.JSONDecodeError as e:
        raise SwarmError(f"{p} is not valid JSON: {e}")
    if not cfg.get("reviewers"):
        raise SwarmError(f"{p} has no 'reviewers' table")
    return cfg


def list_reviewers(cfg=None):
    """-> {name: {"tier": ..., "about": ...}} in config order."""
    return (cfg or load_config()).get("reviewers") or {}


def find_host(name, hosts_dir=None):
    """Host specs are looked up in swarm/hosts first, then legio's shared hosts/.

    swarm/hosts comes first so `fake` (swarm's test harness) shadows legio's
    centuria-shaped one; every real host is borrowed rather than copied, so a
    fix to ../hosts/claude-code.json reaches both tools.
    """
    dirs = []
    if hosts_dir:
        dirs.append(Path(hosts_dir).expanduser())
    dirs += [HERE / "hosts", HERE.parent / "hosts"]
    for d in dirs:
        p = d / f"{name}.json"
        if p.exists():
            return p
    looked = ", ".join(str(d) for d in dirs)
    raise SwarmError(f"no host spec {name!r} (looked in {looked})")


def list_hosts(hosts_dir=None):
    """Every host spec swarm can see, higher-precedence directories winning."""
    dirs = []
    if hosts_dir:
        dirs.append(Path(hosts_dir).expanduser())
    dirs += [HERE / "hosts", HERE.parent / "hosts"]
    found = {}
    for d in reversed(dirs):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                prof = json.loads(p.read_text())
            except json.JSONDecodeError:
                prof = {"host": p.stem, "invalid": True,
                        "about": "not valid JSON"}
            prof["_path"] = str(p)
            found[p.stem] = prof
    return dict(sorted(found.items()))


# ---- the target: repo + diff ----------------------------------------------


def _git(args, cwd):
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    except FileNotFoundError:
        raise SwarmError("git is not on PATH")
    if res.returncode != 0:
        detail = (res.stderr or res.stdout).strip().splitlines()
        raise SwarmError(f"git {' '.join(args)} failed"
                         + (f": {detail[-1]}" if detail else ""))
    return res.stdout


def _gh(args, cwd):
    try:
        res = subprocess.run(["gh", *args], cwd=str(cwd), capture_output=True, text=True)
    except FileNotFoundError:
        raise SwarmError(f"`{args[0]}` needs the GitHub CLI (`gh`) on PATH")
    if res.returncode != 0:
        detail = (res.stderr or res.stdout).strip().splitlines()
        raise SwarmError(f"gh {' '.join(args)} failed"
                         + (f": {detail[-1]}" if detail else ""))
    return res.stdout


def default_base(root, head="HEAD"):
    """The first ref that is both present and behind HEAD, in the order most repos have.

    A repo sitting on `main` with no `origin` must not diff main against itself:
    when a candidate's merge-base *is* the head commit, keep looking.
    """
    head_sha = _git(["rev-parse", f"{head}^{{commit}}"], root).strip()
    for ref in ("origin/main", "origin/HEAD", "main", "master", "HEAD~1"):
        try:
            sha = _git(["merge-base", ref, head], root).strip()
        except SwarmError:
            continue
        if sha != head_sha:
            return ref
    raise SwarmError("cannot find a base commit to diff against; pass --base <ref>")


def _diff_stats(patch):
    files = patch.count("diff --git ")
    added = sum(1 for line in patch.splitlines()
                if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in patch.splitlines()
                  if line.startswith("-") and not line.startswith("---"))
    return files, added, removed


def resolve_target(repo, base=None, head=None, diff=None, pr=None):
    """-> what to review, as a self-contained patch plus the refs it came from.

    Never writes into the repo. Raises NothingToReview when the patch is empty.
    """
    root = Path(repo).expanduser()
    if not root.exists():
        raise SwarmError(f"repo {root} does not exist")
    root = Path(_git(["rev-parse", "--show-toplevel"], root).strip()).resolve()

    context = ""
    if diff:
        if diff == "-":
            patch = sys.stdin.read()
            source = "stdin"
        else:
            p = Path(diff).expanduser()
            if not p.exists():
                raise SwarmError(f"diff file {p} does not exist")
            patch = p.read_text()
            source = str(p)
        base_ref = head_ref = base_sha = head_sha = ""
    elif pr:
        patch = _gh(["pr", "diff", str(pr)], root)
        base_ref = head_ref = base_sha = head_sha = ""
        source = f"PR #{pr}"
        try:
            meta = json.loads(_gh(["pr", "view", str(pr), "--json", "title,body"], root))
            context = (f"# {meta.get('title') or ''}\n\n{meta.get('body') or ''}").strip()
        except (SwarmError, json.JSONDecodeError):
            context = ""
    else:
        base_ref = base or default_base(root)
        head_ref = head or "HEAD"
        base_sha = _git(["merge-base", base_ref, head_ref], root).strip()
        head_sha = _git(["rev-parse", head_ref], root).strip()
        patch = _git(["diff", "--no-color", "--no-ext-diff", base_sha, head_sha], root)
        source = f"{base_ref}..{head_ref}"

    if not patch.strip():
        raise NothingToReview(
            f"{source} is empty — nothing to review. "
            "Point it at a range that has commits (--base/--head), a patch (--diff), "
            "or a PR (--pr).")

    files, added, removed = _diff_stats(patch)
    return {
        "root": str(root), "patch": patch, "source": source, "context": context,
        "base_ref": base_ref, "head_ref": head_ref,
        "base_sha": base_sha, "head_sha": head_sha,
        "files": files, "added": added, "removed": removed,
    }


def _run_id(target):
    when = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sha = target["head_sha"][:7] or hashlib.sha1(
        target["patch"].encode("utf-8", "replace")).hexdigest()[:7]
    return f"{when}-{sha}"


def _ensure_excluded(root, pattern):
    """Keep swarm's output out of `git status` without touching .gitignore.

    Same policy as `legio add`: .git/info/exclude is local to the machine, so no
    tracked file in the project changes and nothing enters git history.
    """
    try:
        excl = Path(_git(["rev-parse", "--git-path", "info/exclude"], root).strip())
    except SwarmError:
        return False
    if not excl.is_absolute():
        excl = Path(root) / excl
    try:
        text = excl.read_text() if excl.exists() else ""
    except OSError:
        return False
    if pattern in text.splitlines():
        return False
    try:
        excl.parent.mkdir(parents=True, exist_ok=True)
        with excl.open("a", encoding="utf-8") as fh:
            if text and not text.endswith("\n"):
                fh.write("\n")
            fh.write(pattern + "\n")
        return True
    except OSError:
        return False


# ---- prompts ---------------------------------------------------------------


def _order(run_id, out_dir, target, name, tier):
    review_file = out_dir / f"review-{name}.md"
    header = "\n".join([
        f"Swarm run: {run_id}",
        f"Repo: {target['root']}",
        f"Reviewer: {name}",
        f"Diff: {target['source']} — {target['files']} file(s), "
        f"+{target['added']} -{target['removed']}",
        f"Patch: {out_dir / 'diff.patch'}",
        f"Review file: {review_file}",
    ] + ([f"Context: {out_dir / 'context.md'}"] if target["context"] else []))
    task = (
        "Review the change described above. There is no build step behind it and\n"
        "nobody will fix findings in this run: judge, write the file, exit.\n\n"
        f"Read the patch at {out_dir / 'diff.patch'} first, then read the files it\n"
        f"touches in {target['root']}.\n"
        "Do not modify, stage, commit or push anything.\n\n"
        f"Write your review to {review_file}. Its first line must be exactly\n"
        "`VERDICT: PASS` or `VERDICT: CHANGES` — nothing before it."
    )
    return {
        "role": name, "tier": tier,
        "role_file": str(HERE / "roles" / f"{name}.md"),
        "repo": target["root"], "run": run_id, "out": str(out_dir),
        "cwd": target["root"], "header": header, "task": task,
    }


def _tier_for(name, cfg, risk, overrides):
    reg = cfg["reviewers"][name]
    tier = (overrides or {}).get(name) or reg.get("tier") or "medium"
    if risk and name == cfg.get("risk_reviewer", "code-reviewer"):
        tier = (cfg.get("risk_tiers") or {}).get(risk) or tier
    return tier


# ---- verdicts --------------------------------------------------------------


def parse_verdict(text):
    """The first non-empty line decides; anything else is not a verdict."""
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _FIRST_VERDICT.match(line)
        return m.group(1).upper() if m else None
    return None


def parse_must_fix(text):
    """Items under `## Must fix`, so one reviewer's blockers can be merged."""
    m = _MUST_FIX.search(text)
    if not m:
        return []
    body = text[m.end():]
    nxt = _NEXT_SECTION.search(body)
    if nxt:
        body = body[:nxt.start()]
    items = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("<!--"):
            continue
        items.append(_NUMBERING.sub("", s))
    return items


def _judge(name, tier, model, out_dir, code, stdout, stderr, timeout_hit):
    review_file = out_dir / f"review-{name}.md"
    log_file = out_dir / f"agent-{name}.log"
    try:
        log_file.write_text(
            f"$ {name}\n\n--- stdout ---\n{stdout}\n\n--- stderr ---\n{stderr}\n",
            encoding="utf-8")
    except OSError:
        pass

    entry = {
        "reviewer": name, "tier": tier, "model": model,
        "verdict": VERDICT_ERROR, "must_fix": [], "error": None,
        "exit_code": code, "review": str(review_file), "log": str(log_file),
    }

    if not review_file.exists():
        last = [l for l in (stderr or stdout or "").strip().splitlines() if l.strip()]
        if timeout_hit:
            entry["error"] = "timed out without writing a review"
        elif code:
            entry["error"] = f"exited {code}: {last[-1] if last else 'no output'}"
        else:
            entry["error"] = "exited 0 but wrote no review file"
        return entry

    text = review_file.read_text(encoding="utf-8", errors="replace")
    verdict = parse_verdict(text)
    if verdict is None:
        first = next((l.strip() for l in text.splitlines() if l.strip()), "")
        entry["error"] = ("the review file's first line is not a verdict"
                          + (f": {first[:80]!r}" if first else ""))
        return entry

    entry["verdict"] = verdict
    entry["must_fix"] = parse_must_fix(text) if verdict == VERDICT_CHANGES else []
    if code:
        entry["error"] = f"wrote a verdict but exited {code}"
    return entry


# ---- the report ------------------------------------------------------------


class Report:
    """What one run produced. The only durable thing swarm has."""

    def __init__(self, run_id, host, target, out_dir, results, warnings,
                 dry=False, plan=None):
        self.run_id = run_id
        self.host = host
        self.target = target
        self.out_dir = Path(out_dir)
        self.results = results
        self.warnings = list(warnings)
        self.dry = dry
        self.plan = plan or []   # built commands, only populated by --dry-run

    @property
    def repo(self):
        return self.target["root"]

    @property
    def verdicts(self):
        return {r["reviewer"]: r["verdict"] for r in self.results}

    @property
    def overall(self):
        if self.dry or not self.results:
            return VERDICT_DRY
        seen = {r["verdict"] for r in self.results}
        for level in (VERDICT_ERROR, VERDICT_CHANGES, VERDICT_PASS):
            if level in seen:
                return level
        return VERDICT_ERROR

    @property
    def exit_code(self):
        return EXIT.get(self.overall, 2)

    def must_fix(self):
        """Every blocker, attributed to the reviewer that found it."""
        return [(r["reviewer"], item)
                for r in self.results for item in r.get("must_fix") or []]

    def rows(self):
        return [(r["reviewer"], r["tier"], r["model"], r["verdict"], r["error"])
                for r in self.results]

    def to_dict(self):
        return {
            "run": self.run_id,
            "repo": self.target["root"],
            "out": str(self.out_dir),
            "dry_run": self.dry,
            "host": self.host,
            "diff": {
                "source": self.target["source"],
                "base": self.target["base_ref"],
                "head": self.target["head_ref"],
                "base_sha": self.target["base_sha"],
                "head_sha": self.target["head_sha"],
                "files": self.target["files"],
                "added": self.target["added"],
                "removed": self.target["removed"],
            },
            "overall": self.overall,
            "exit_code": self.exit_code,
            "reviewers": {r["reviewer"]: {
                "verdict": r["verdict"],
                "tier": r["tier"],
                "model": r["model"],
                "review": r["review"],
                "log": r["log"],
                "exit_code": r["exit_code"],
                "error": r["error"],
                "must_fix": r["must_fix"],
            } for r in self.results},
            "must_fix": [{"reviewer": who, "item": item}
                         for who, item in self.must_fix()],
            "warnings": self.warnings,
        }

    def render_md(self):
        t, d = self.target, self.out_dir
        lines = [
            f"# swarm · {self.run_id}",
            "",
            f"- **repo**: `{t['root']}`",
            f"- **diff**: `{t['source']}` — {t['files']} file(s), "
            f"+{t['added']} -{t['removed']}",
            f"- **host**: `{self.host}`",
            f"- **overall**: **{self.overall}**",
            "",
            "| reviewer | tier | model | verdict |",
            "|---|---|---|---|",
        ]
        for name, tier, model, verdict, error in self.rows():
            cell = verdict if not error else f"{verdict} ({error})"
            lines.append(f"| {name} | {tier} | {model or '-'} | {cell} |")
        lines.append("")

        blockers = self.must_fix()
        lines += ["## Must fix", ""]
        if blockers:
            for who, item in blockers:
                lines.append(f"- **{who}** — {item}")
        else:
            lines.append("- none")
        lines.append("")

        errors = [(r["reviewer"], r["error"]) for r in self.results if r["error"]]
        if errors:
            lines += ["## Notes", ""]
            for who, err in errors:
                lines.append(f"- {who}: {err}")
            lines.append("")

        if self.warnings:
            lines += ["## Warnings", ""] + [f"- {w}" for w in self.warnings] + [""]

        lines += ["## Files", "",
                  f"- patch: `{d / 'diff.patch'}`",
                  f"- report: `{d / 'report.md'}`",
                  f"- json: `{d / 'report.json'}`"]
        for r in self.results:
            lines.append(f"- {r['reviewer']}: `{r['review']}` · `{r['log']}`")
        return "\n".join(lines).rstrip() + "\n"


# ---- the run ---------------------------------------------------------------


def _resolve_names(reviewers, registry):
    if isinstance(reviewers, str):
        reviewers = [reviewers]
    if not reviewers:
        return list(registry)
    names = []
    for n in reviewers:
        if n == "all":
            return list(registry)
        if n not in registry:
            raise SwarmError(f"unknown reviewer {n!r}; choose from "
                             f"{', '.join(registry)} (or `all`)")
        if n not in names:
            names.append(n)
    return names


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def review(repo, reviewers=None, base=None, head=None, diff=None, pr=None, spec=None,
           host=None, hosts_dir=None, risk=None, tiers=None, jobs=None, timeout=None,
           yolo=False, dry_run=False, out=None, cfg=None):
    """Run the reviewers and return a Report. Writes patch, reviews, report.

    Raises SwarmError for anything that stops the run, NothingToReview for an
    empty diff. A reviewer that crashes does not stop its peers: it becomes an
    ERROR row and the others are still collected.
    """
    cfg = cfg or load_config()
    registry = cfg["reviewers"]
    names = _resolve_names(reviewers, registry)
    target = resolve_target(repo, base=base, head=head, diff=diff, pr=pr)

    run_id = _run_id(target)
    root = Path(target["root"])
    out_dir = (Path(out).expanduser() if out
               else root / (cfg.get("out_dir") or ".swarm") / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff.patch").write_text(target["patch"], encoding="utf-8")

    context = []
    if target["context"]:
        context.append(target["context"])
    if spec:
        spec_src = Path(spec).expanduser()
        if not spec_src.exists():
            raise SwarmError(f"spec file {spec_src} does not exist")
        text = spec_src.read_text(encoding="utf-8")
        (out_dir / "spec.md").write_text(text, encoding="utf-8")
        context.append(text)
    if context:
        text = "\n\n---\n\n".join(context)
        (out_dir / "context.md").write_text(
            text if text.endswith("\n") else text + "\n", encoding="utf-8")
        target["context"] = str(out_dir / "context.md")
    else:
        target["context"] = ""

    warnings = []
    patch_lines = target["patch"].count("\n") + 1
    cap = cfg.get("max_diff_lines") or 0
    if cap and patch_lines > cap:
        warnings.append(f"the patch is {patch_lines} lines (max_diff_lines {cap}); "
                        "the reviewers may not read all of it")

    if out_dir.parent == root / (cfg.get("out_dir") or ".swarm"):
        _ensure_excluded(root, (cfg.get("out_dir") or ".swarm") + "/")

    host_name = host or cfg.get("default_host")
    if not host_name:
        raise SwarmError("no --host given and config.json has no default_host")
    prof = hostkit.load_host(find_host(host_name, hosts_dir))

    built = []
    for name in names:
        tier = _tier_for(name, cfg, risk, tiers)
        order = _order(run_id, out_dir, target, name, tier)
        cmd, body, cwd, model = hostkit.build(prof, order, yolo)  # fail fast
        built.append({"name": name, "tier": tier, "order": order,
                      "cmd": cmd, "body": body, "cwd": cwd, "model": model})

    if dry_run:
        return Report(run_id, host_name, target, out_dir, [], warnings,
                      dry=True, plan=built)

    timeout_s = timeout or prof.get("timeout_seconds") or 3600
    width = jobs or len(built) or 1
    results = []
    for chunk in _chunks(built, width):
        running = []
        for item in chunk:
            proc, stdin_body = hostkit.spawn(prof, item["cmd"], item["body"], item["cwd"])
            running.append((item, proc, stdin_body))
        for item, proc, stdin_body in running:
            code, stdout, stderr = hostkit.collect(proc, stdin_body, timeout_s)
            results.append(_judge(item["name"], item["tier"], item["model"], out_dir,
                                  code, stdout, stderr, timeout_hit=code is None))

    report = Report(run_id, host_name, target, out_dir, results, warnings)
    (out_dir / "report.md").write_text(report.render_md(), encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report
