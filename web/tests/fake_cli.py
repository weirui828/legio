#!/usr/bin/env python3
"""A stand-in for `legio` and `.centuria/bin/job` in the dashboard action tests.

Logs {argv, stdin, cwd} to $FAKE_CLI_LOG (one JSON object per call), prints a
line, and exits with $FAKE_CLI_EXIT (default 0). Touches nothing else.
"""
import json
import os
import sys

stdin = "" if sys.stdin.isatty() else sys.stdin.read()
log = os.environ.get("FAKE_CLI_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd()}) + "\n")
print("fake cli: " + " ".join(sys.argv[1:]))
sys.exit(int(os.environ.get("FAKE_CLI_EXIT", "0")))
