#!/usr/bin/env python3
"""The runner's live heartbeat: who is at the desk right now.

`bin/run` writes `.centuria/jobs/<id>/live.json` around each agent call and
removes it afterwards; the dashboard reads it. A stale file (killed process) is
handled by the reader's 10-minute rule, so the writer must stay best-effort.

    python3 -m unittest tests.test_live_heartbeat -v
"""

import json
import runpy
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "centuria" / "bin" / "run"


class LiveHeartbeat(unittest.TestCase):
    def setUp(self):
        if not (REPO / ".centuria" / "config.json").exists():
            self.skipTest("this checkout has no stationed centuria")
        module = runpy.run_path(str(RUN), run_name="not_main")
        self.live_start = module["live_start"]
        self.live_end = module["live_end"]
        self.globals = self.live_start.__globals__
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.centuria = Path(self.tmp.name) / ".centuria"
        (self.centuria / "jobs" / "001-example").mkdir(parents=True)
        self.globals["CENTURIA"] = self.centuria
        self.path = self.centuria / "jobs" / "001-example" / "live.json"

    def test_written_then_removed(self):
        order = {"id": "001-example", "round": 2}
        self.live_start(order, ["fabri", "medicus"])
        data = json.loads(self.path.read_text())
        self.assertEqual(data["roles"], ["fabri", "medicus"])
        self.assertEqual(data["round"], 2)
        self.assertTrue(data["started"].endswith("Z"))
        self.assertIsInstance(data["pid"], int)
        self.live_end(order)
        self.assertFalse(self.path.exists())

    def test_end_without_a_file_is_harmless(self):
        self.live_end({"id": "001-example"})  # must not raise

    def test_a_missing_job_folder_is_harmless(self):
        self.live_start({"id": "does-not-exist", "round": 0}, ["fabri"])
        self.assertFalse((self.centuria / "jobs" / "does-not-exist"
                          / "live.json").exists())


if __name__ == "__main__":
    unittest.main()
