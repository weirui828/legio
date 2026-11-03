#!/usr/bin/env python3
"""Tests for swarm. Standard library only: no pytest, no model, no network.

Every test drives the real CLI against a throwaway git repo with the `fake` host,
which writes the review file an agent would write. That covers the whole path —
diff resolution, prompt construction, fan-out, verdict parsing, aggregation, exit
codes, .git/info/exclude — without spending a token.

    python3 -m unittest discover -s swarm/tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SWARM_DIR = Path(__file__).resolve().parents[1]
SWARM = SWARM_DIR / "swarm"
ALL = ["code-reviewer", "security-reviewer", "ux-reviewer", "ui-reviewer",
       "ios-reviewer"]

sys.path.insert(0, str(SWARM_DIR.parent))


def run(args, env=None):
    """Invoke the CLI the way a user would."""
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(SWARM), *args],
                          capture_output=True, text=True, env=e)


class RepoCase(unittest.TestCase):
    """A two-commit repo: the review target for every test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="swarm-test-"))
        self.repo = self.tmp / "project"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "test")
        (self.repo / "a.txt").write_text("one\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "one")
        (self.repo / "a.txt").write_text("two\n")
        self.git("commit", "-qam", "two")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        res = subprocess.run(["git", *args], cwd=self.repo,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    # -- helpers -------------------------------------------------------------

    def run_swarm(self, *args, env=None):
        return run([*args], env=env)

    def runs(self):
        d = self.repo / ".swarm"
        return sorted(p for p in d.iterdir()) if d.is_dir() else []

    def run_dir(self):
        runs = self.runs()
        self.assertEqual(len(runs), 1, f"expected one run dir, got {runs}")
        return runs[0]

    def report_json(self):
        return json.loads((self.run_dir() / "report.json").read_text())

    def review_files(self):
        return sorted(p.name for p in self.run_dir().glob("review-*.md"))

    def status(self):
        return self.git("status", "--porcelain")


class TestRun(RepoCase):
    def test_all_pass(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PASS", res.stdout)
        self.assertEqual(self.review_files(), [f"review-{n}.md" for n in sorted(ALL)])
        data = self.report_json()
        self.assertEqual(data["overall"], "PASS")
        self.assertEqual({k: v["verdict"] for k, v in data["reviewers"].items()},
                         {n: "PASS" for n in ALL})
        self.assertEqual(data["diff"]["files"], 1)
        self.assertTrue((self.run_dir() / "diff.patch").read_text().startswith("diff --git"))

    def test_changes_exit_1_and_blame(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1",
                             env={"SWARM_FAKE_VERDICT": "CHANGES:ui-reviewer"})
        self.assertEqual(res.returncode, 1, res.stderr + res.stdout)
        data = self.report_json()
        self.assertEqual(data["overall"], "CHANGES")
        self.assertEqual(data["reviewers"]["ui-reviewer"]["verdict"], "CHANGES")
        self.assertEqual(data["reviewers"]["code-reviewer"]["verdict"], "PASS")
        self.assertEqual([b["reviewer"] for b in data["must_fix"]], ["ui-reviewer"])
        self.assertIn("fake must-fix for ui-reviewer", data["must_fix"][0]["item"])
        self.assertIn("must fix", res.stdout)

    def test_crashed_reviewer_is_error_not_a_dead_swarm(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1",
                             env={"SWARM_FAKE_FAIL": "security-reviewer"})
        self.assertEqual(res.returncode, 2, res.stderr + res.stdout)
        data = self.report_json()
        self.assertEqual(data["overall"], "ERROR")
        self.assertEqual(data["reviewers"]["security-reviewer"]["verdict"], "ERROR")
        self.assertIn("exited 1", data["reviewers"]["security-reviewer"]["error"])
        # the others still ran and are still reported
        for name in (n for n in ALL if n != "security-reviewer"):
            self.assertEqual(data["reviewers"][name]["verdict"], "PASS")
        self.assertEqual(len(self.review_files()), len(ALL) - 1)

    def test_one_reviewer_only(self):
        res = self.run_swarm("run", "code-reviewer", "on", str(self.repo),
                             "--host", "fake", "--base", "HEAD~1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.review_files(), ["review-code-reviewer.md"])
        self.assertEqual(list(self.report_json()["reviewers"]), ["code-reviewer"])

    def test_jobs_one_still_reviews_everyone(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1", "--jobs", "1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.review_files()), len(ALL))

    def test_json_is_pure_json(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)          # nothing but JSON on stdout
        self.assertEqual(data["exit_code"], 0)
        self.assertEqual(data["repo"], str(self.repo.resolve()))
        self.assertEqual(data["host"], "fake")
        for key in ("run", "out", "diff", "overall", "reviewers", "must_fix"):
            self.assertIn(key, data)

    def test_explicit_tier_override(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1", "--tier", "code-reviewer=strong",
                             "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["reviewers"]["code-reviewer"]["tier"],
                         "strong")

    def test_risk_bumps_code_reviewer_only(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1", "--risk", "low", "--json")
        data = json.loads(res.stdout)
        self.assertEqual(data["reviewers"]["code-reviewer"]["tier"], "light")
        self.assertEqual(data["reviewers"]["security-reviewer"]["tier"], "strong")

    def test_diff_file_mode(self):
        patch = self.tmp / "manual.patch"
        patch.write_text(self.git("diff", "HEAD~1", "HEAD"))
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--diff", str(patch), "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["diff"]["source"], str(patch))
        self.assertEqual(len(self.review_files()), len(ALL))

    def test_spec_becomes_context(self):
        spec = self.tmp / "issue.md"
        spec.write_text("# add two\n\nmake a.txt say two\n")
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1", "--spec", str(spec))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.run_dir() / "context.md").read_text(), spec.read_text())


class TestGuards(RepoCase):
    def test_empty_diff_exits_3(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD", "--head", "HEAD")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("nothing to review", res.stderr.lower())

    def test_unknown_reviewer_exits_2(self):
        res = self.run_swarm("run", "code-reviewr", "on", str(self.repo),
                             "--host", "fake", "--base", "HEAD~1")
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown reviewer", res.stderr)
        self.assertIn("code-reviewer", res.stderr)

    def test_no_repo_named(self):
        res = self.run_swarm("run")
        self.assertEqual(res.returncode, 2)
        self.assertIn("name a repo", res.stderr)

    def test_missing_repo(self):
        res = self.run_swarm("run", "on", str(self.tmp / "nope"), "--host", "fake")
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not exist", res.stderr)

    def test_unknown_host(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "nohost",
                             "--base", "HEAD~1")
        self.assertEqual(res.returncode, 2)
        self.assertIn("no host spec", res.stderr)

    def test_dry_run_spawns_nothing(self):
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                             "--base", "HEAD~1", "--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("would run:", res.stdout)
        self.assertIn("VERDICT: PASS", res.stdout)      # the role file reached the prompt
        self.assertEqual(self.review_files(), [])        # no reviewer ran

    def test_default_base_skips_a_base_equal_to_head(self):
        # The repo is on `main` (or master) with no origin: diffing main..HEAD would
        # be empty, so the default must fall through to HEAD~1 instead.
        res = self.run_swarm("run", "on", str(self.repo), "--host", "fake")
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertEqual(self.report_json()["diff"]["files"], 1)


class TestGitHygiene(RepoCase):
    def test_git_status_stays_clean(self):
        self.run_swarm("run", "on", str(self.repo), "--host", "fake", "--base", "HEAD~1")
        self.assertEqual(self.status(), "")
        self.assertTrue((self.repo / ".swarm").is_dir())

    def test_exclude_written_once(self):
        for _ in range(2):
            res = self.run_swarm("run", "on", str(self.repo), "--host", "fake",
                                 "--base", "HEAD~1")
            self.assertEqual(res.returncode, 0, res.stderr)
        lines = (self.repo / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertEqual(lines.count(".swarm/"), 1)
        self.assertEqual(self.status(), "")


class TestLibrary(unittest.TestCase):
    """The library seam the CLI sits on: import swarm.api and call review()."""

    def test_review_from_python(self):
        tmp = Path(tempfile.mkdtemp(prefix="swarm-lib-"))
        try:
            repo = tmp / "project"
            repo.mkdir()
            env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.c",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.c"}
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "f.txt").write_text("a\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "1"], cwd=repo, check=True, env={**os.environ, **env})
            (repo / "f.txt").write_text("b\n")
            subprocess.run(["git", "commit", "-qam", "2"], cwd=repo, check=True, env={**os.environ, **env})

            from swarm.api import review
            report = review(str(repo), reviewers=["code-reviewer"], base="HEAD~1",
                            host="fake")
            self.assertEqual(report.overall, "PASS")
            self.assertEqual(report.exit_code, 0)
            self.assertEqual(report.verdicts, {"code-reviewer": "PASS"})
            self.assertEqual(len(report.rows()), 1)
            self.assertTrue(report.to_dict()["reviewers"]["code-reviewer"]["review"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCliSurface(unittest.TestCase):
    def test_reviewers_lists_the_cast(self):
        res = run(["reviewers"])
        self.assertEqual(res.returncode, 0, res.stderr)
        for name in ALL:
            self.assertIn(name, res.stdout)

    def test_reviewers_json(self):
        res = run(["reviewers", "--json"])
        data = json.loads(res.stdout)
        self.assertEqual(sorted(data), sorted(ALL))
        self.assertEqual(data["security-reviewer"]["tier"], "strong")

    def test_hosts_sees_borrowed_registry(self):
        res = run(["hosts", "--json"])
        data = json.loads(res.stdout)
        self.assertIn("claude-code", data)          # borrowed from ../hosts
        self.assertIn("fake", data)                 # swarm's own test harness

    def test_version(self):
        res = run(["version"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("swarm", res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
