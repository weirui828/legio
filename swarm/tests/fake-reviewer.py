#!/usr/bin/env python3
"""Test harness reviewer: writes the review file an agent would write, then exits.

Reads the swarm prompt on stdin, finds the `Review file:` line in the header and
writes a verdict there. It never talks to a model, so it is only good for testing
swarm itself.

Environment knobs (read from the parent, so they work through any host spec):
  SWARM_FAKE_VERDICT=CHANGES            every reviewer returns CHANGES
  SWARM_FAKE_VERDICT=CHANGES:ui-reviewer only that reviewer returns CHANGES
  SWARM_FAKE_FAIL=security-reviewer     that reviewer exits non-zero and writes nothing
  SWARM_FAKE_FAIL=all                   every reviewer exits non-zero
"""

import os
import re
import sys
from pathlib import Path

prompt = sys.stdin.read()

path_m = re.search(r"^Review file: (\S+)$", prompt, re.MULTILINE)
who_m = re.search(r"^Reviewer: (\S+)$", prompt, re.MULTILINE)
if not path_m or not who_m:
    print("fake-reviewer: prompt has no 'Review file:'/'Reviewer:' header line",
          file=sys.stderr)
    sys.exit(2)

path = Path(path_m.group(1))
who = who_m.group(1)

if os.environ.get("SWARM_FAKE_FAIL", "") in ("all", who):
    print(f"fake-reviewer: {who} refuses to review (SWARM_FAKE_FAIL)", file=sys.stderr)
    sys.exit(1)

wanted = os.environ.get("SWARM_FAKE_VERDICT", "PASS").strip().lower()
verdict = "CHANGES" if wanted in ("changes", f"changes:{who.lower()}") else "PASS"

if verdict == "CHANGES":
    text = (f"VERDICT: CHANGES\n\n## Must fix\n"
            f"1. fake.py:1 — fake must-fix for {who}, injected by SWARM_FAKE_VERDICT\n\n"
            f"## Summary\n- fake review of {who}\n")
else:
    text = f"VERDICT: PASS\n\n## Summary\n- fake review of {who}\n"

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text)
print(f"fake-reviewer: wrote {path}")
