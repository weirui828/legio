#!/usr/bin/env python3
"""Standard-library checks for `legio hosts --json`."""

import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGIO = ROOT / "legio"


def run_legio(*args, cwd=ROOT, script=LEGIO):
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd,
                          capture_output=True, text=True)


class HostsJsonTest(unittest.TestCase):
    def test_shape_matches_hosts_directory(self):
        res = run_legio("hosts", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")
        data = json.loads(res.stdout)
        expected = []
        for path in sorted((ROOT / "hosts").glob("*.json")):
            prof = json.loads(path.read_text())
            expected.append({
                "host": prof["host"] if "host" in prof else path.stem,
                "model_tiers": prof["model_tiers"] if "model_tiers" in prof else {},
                "untested": bool(prof["untested"]) if "untested" in prof else False,
            })
        self.assertEqual(data, expected)
        for item in data:
            self.assertEqual(set(item), {"host", "model_tiers", "untested"})
            self.assertIs(type(item["untested"]), bool)

    def test_parse_accepts_json_before_or_after_subcommand(self):
        parse = runpy.run_path(str(LEGIO))["parse"]
        for argv in (["hosts", "--json"], ["--json", "hosts"]):
            opts, rest = parse(argv)
            self.assertIs(opts["json"], True, argv)
            self.assertEqual(rest, ["hosts"], argv)
        opts, rest = parse(["hosts"])
        self.assertIs(opts["json"], False)
        self.assertEqual(rest, ["hosts"])

    def test_discover_skips_tilde_folders(self):
        discover = runpy.run_path(str(LEGIO))["discover"]
        with tempfile.TemporaryDirectory() as raw:
            for name in ("alpha", "~archived"):
                folder = Path(raw) / name / ".centuria"
                folder.mkdir(parents=True)
                (folder / "config.json").write_text("{}")
            self.assertEqual([p.name for p in discover(raw)], ["alpha"])

    def test_invalid_file_warns_and_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy2(LEGIO, tmp / "legio")
            shutil.copytree(ROOT / "hosts", tmp / "hosts")
            (tmp / "hosts" / "zz-invalid.json").write_text("{ broken")
            res = run_legio("hosts", "--json", cwd=tmp, script=tmp / "legio")
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(res.stdout)
            self.assertNotIn("zz-invalid", [item["host"] for item in data])
            warnings = res.stderr.splitlines()
            self.assertEqual(len(warnings), 1, res.stderr)
            self.assertRegex(warnings[0], r"^legio: warning:.*zz-invalid\.json")
            table = run_legio("hosts", cwd=tmp, script=tmp / "legio")
            self.assertRegex(table.stdout, r"(?m)^zz-invalid\s+INVALID JSON")

    def test_missing_fields_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy2(LEGIO, tmp / "legio")
            shutil.copytree(ROOT / "hosts", tmp / "hosts")
            (tmp / "hosts" / "zz-empty.json").write_text("{}")
            res = run_legio("hosts", "--json", cwd=tmp, script=tmp / "legio")
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(json.loads(res.stdout)[-1], {
                "host": "zz-empty",
                "model_tiers": {},
                "untested": False,
            })


if __name__ == "__main__":
    unittest.main()
