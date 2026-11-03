#!/usr/bin/env python3
"""Test harness agent: writes the artifact an agent would write, then exits.

Reads the prompt on stdin, works out the job folder and the role from it, and
does the minimum needed for the state machine to move. It never talks to a
model, so it is only good for testing the pipeline itself.
"""
import re
import subprocess
import sys
from pathlib import Path

prompt = sys.stdin.read()
fold = re.search(r"Job folder: (\S+?)/\.\s", prompt)
role_m = re.search(r"^role: (\S+)$", prompt, re.M)
if not fold or not role_m:
    print("fake-agent: could not find 'Job folder:' or 'role:' in the prompt",
          file=sys.stderr)
    sys.exit(2)

job_dir = Path(fold.group(1))
role = role_m.group(1)
worktree = Path.cwd()

def write(name, text):
    (job_dir / name).write_text(text)

if role == "tesserarius":
    write("intake.md",
          "DECISION: ACCEPT\nRISK: low\nSURFACES: none\nRESCOPED: no\n\n"
          "## Summary\n- fake intake\n")
elif role == "signifer":
    write("spec.md", "SPEC: READY\n\n## Summary\n- fake spec\n")
elif role == "fabri":
    (worktree / "fake-change.txt").write_text("changed by fake-agent\n")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "fake build"], check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD"], check=True)
    write("build.md", "STATUS: READY\n\n## Summary\n- fake build\n")
elif role in {"probator", "medicus", "mensor", "librator"}:
    rounds = sorted(job_dir.glob("round-*"))
    target = rounds[-1] if rounds else job_dir
    (target / f"review-{role}.md").write_text("VERDICT: PASS\n\n## Summary\n- fake review\n")
elif role == "primus-pilus":
    write("decision.md", "APPROVE\n\n## Summary\n- fake approval\n\n## Why\n- fake\n")
else:
    print(f"fake-agent: unknown role {role}", file=sys.stderr)
    sys.exit(2)
print(f"fake-agent: did {role}")
