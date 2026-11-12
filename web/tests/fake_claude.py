#!/usr/bin/env python3
"""A stand-in for `claude -p --output-format json`, for the Legatus tests.

Echoes the last line of the prompt, logs its argv to $FAKE_CLAUDE_LOG (one
JSON list per call), and fails on purpose when $FAKE_CLAUDE_FAIL is set.
No network, no model.
"""
import json
import os
import sys

argv = sys.argv[1:]
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": argv, "prompt": prompt}) + "\n")
if os.environ.get("FAKE_CLAUDE_FAIL"):
    print(json.dumps({"type": "result", "is_error": True, "result": "the fake claude failed on purpose"}))
    sys.exit(1)
flag = "--resume" if "--resume" in argv else "--session-id"
session = argv[argv.index(flag) + 1]
last = prompt.strip().splitlines()[-1] if prompt.strip() else ""
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "result": f"echo: {last}", "session_id": session, "total_cost_usd": 0.01}))
