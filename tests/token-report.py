#!/usr/bin/env python3
"""Per-role cost report for one job, read from this host's session logs.

Usage: tests/token-report.py <job-id> [--sessions DIR]

This is a development tool, not part of the pipeline: it reads the agent host's own
transcripts to answer "what did this job cost, and where". It only knows how to read the
DeepSeek Harness session format (~/.dsh/sessions/<workspace>/session-*/session.v4.jsonl.zstd),
so it is host-specific by nature.

Columns:
  sess   agent processes (one per role per round)
  steps  model requests inside those processes - the thing that grows cost quadratically
  in/out tokens reported by the host
  cache  tokens re-read from the prompt cache
  check  steps that actually executed checks.sh or a test runner
"""

import json
import pathlib
import re
import subprocess
import sys

ROLES = ("tesserarius", "signifer", "fabri", "probator", "medicus", "mensor",
         "librator", "primus-pilus")
RUN = re.compile(r"(^|[;&|\s])(bash\s+\S*checks\.sh|sh\s+\S*checks\.sh|\./\S*checks\.sh"
                 r"|pytest\b|python3?\s+-m\s+(pytest|unittest)|npm\s+(test|run)"
                 r"|pnpm\s+(test|run))")


def read_session(path):
    try:
        return subprocess.run(["zstd", "-dc", str(path)],
                              capture_output=True, check=True).stdout.decode("utf-8", "ignore")
    except (OSError, subprocess.CalledProcessError):
        return ""


def analyse(job_id, sessions, needle):
    per = {}
    for path in sessions.glob("session-*/session.v4.jsonl.zstd"):
        raw = read_session(path)
        if needle not in raw:
            continue
        role = next((r for r in ROLES if f"role: {r}" in raw), "(unknown)")
        step, checks = 0, 0
        out_tok = in_tok = cache = 0
        for line in raw.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("type")
            if kind == "step/start":
                step += 1
            elif kind == "tool/call":
                if rec["data"]["name"] == "bash":
                    cmd = json.loads(rec["data"]["arguments"]).get("command", "")
                    if RUN.search(cmd):
                        checks += 1
            elif kind == "assistant/message":
                usage = rec["data"].get("usage") or {}
                out_tok += usage.get("outputTokens", 0)
                in_tok += usage.get("inputTokens", 0)
                cache += usage.get("cacheReadTokens", 0)
        t = per.setdefault(role, {"sess": 0, "steps": 0, "checks": 0,
                                  "in": 0, "out": 0, "cache": 0})
        t["sess"] += 1
        t["steps"] += step
        t["checks"] += checks
        t["in"] += in_tok
        t["out"] += out_tok
        t["cache"] += cache
    return per


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    job_id = argv[0]
    root = pathlib.Path(argv[argv.index("--sessions") + 1]
                        if "--sessions" in argv else pathlib.Path.home() / ".dsh/sessions")
    # Only this repo's sessions: a session in another workspace (including the
    # orchestrator's own conversation) may mention the same job id and would
    # otherwise be billed to it.
    repo_name = pathlib.Path(__file__).resolve().parents[1].name
    glob = argv[argv.index("--workspace") + 1] if "--workspace" in argv else f"*{repo_name}*"
    sessions = root
    needle = f"Job: {job_id}."
    per = {}
    for ws in sorted(root.glob(glob)):
        for role, t in analyse(job_id, ws, needle).items():
            agg = per.setdefault(role, {k: 0 for k in t})
            for k in t:
                agg[k] += t[k]
    if not per:
        print(f"no agent sessions for {job_id!r} under {root}/{glob}", file=sys.stderr)
        return 1
    print(f"job {job_id}")
    print(f"{'role':<14}{'sess':>6}{'steps':>7}{'check':>7}{'in':>10}{'out':>9}{'cache':>11}{'total':>11}")
    tot = dict.fromkeys(("sess", "steps", "checks", "in", "out", "cache"), 0)
    for role, t in sorted(per.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"] + kv[1]["cache"])):
        total = t["in"] + t["out"] + t["cache"]
        print(f"{role:<14}{t['sess']:>6}{t['steps']:>7}{t['checks']:>7}"
              f"{t['in']:>10}{t['out']:>9}{t['cache']:>11}{total:>11}")
        for k in tot:
            tot[k] += t[k]
    total = tot["in"] + tot["out"] + tot["cache"]
    print(f"{'TOTAL':<14}{tot['sess']:>6}{tot['steps']:>7}{tot['checks']:>7}"
          f"{tot['in']:>10}{tot['out']:>9}{tot['cache']:>11}{total:>11}")
    print("\nThe bill is not proportional to the token total: cache reads usually cost a"
          "\nfraction of fresh input, and output costs more per token. Multiply each column"
          "\nby your host's price to get money.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
