#!/usr/bin/env python3
"""Tests for the Camp Legio server. Stdlib only, no network, no model.

    python3 -m unittest discover -s web/tests -v

Every test builds throwaway projects in a temporary root; the only thing that
runs is a fake `centuria view`.
"""

import http.client
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
REPO = WEB.parent
sys.path.insert(0, str(WEB))

ROLES = ("tesserarius", "signifer", "fabri", "probator", "medicus", "mensor",
         "librator", "primus-pilus")


def load_serve():
    spec = importlib.util.spec_from_file_location("camp_serve", WEB / "serve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SERVE = load_serve()


def a_job(**overrides):
    job = {"id": "001-example", "issue": 3, "title": "Example job",
           "stage": "build", "round": 1, "round_limit": 3, "pr": None,
           "gate": None, "reviews": {}, "cost_usd": 1.5, "active": True,
           "waiting": False, "terminal": False, "human_reason": None}
    job.update(overrides)
    return job


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def project(self, name, jobs=None, fail=False, live=None, view=None):
        base = self.root / name
        centuria = base / ".centuria"
        (centuria / "bin").mkdir(parents=True)
        (centuria / "roles").mkdir()
        (centuria / "config.json").write_text("{}")
        for role in ROLES:
            (centuria / "roles" / f"{role}.md").write_text(
                f"---\nrole: {role}\nfunction: {role}-function\n"
                f"model_tier: strong\ntools: read\n---\n\n# {role} · Role\n\n"
                f"> **{role} — this line is the job:**\n"
                f"> do the {role} duty.\n")
        (base / "view.json").write_text(json.dumps(
            jobs if jobs is not None else [a_job()], indent=2))
        if fail:
            (base / "fail").write_text("1")
        if live is not None:
            jobdir = centuria / "jobs" / live["job"]
            jobdir.mkdir(parents=True)
            (jobdir / "live.json").write_text(json.dumps({
                "roles": live["roles"], "round": live.get("round", 1),
                "started": live["started"], "pid": 1}))
        cli = centuria / "bin" / "centuria"
        cli.write_text(
            f"#!{sys.executable}\n"
            "import json, pathlib, sys\n"
            "root = pathlib.Path(__file__).resolve().parents[2]\n"
            "if (root / 'fail').exists():\n"
            "    print('centuria view exploded', file=sys.stderr)\n"
            "    sys.exit(2)\n"
            "print((root / 'view.json').read_text())\n")
        cli.chmod(0o755)
        return base

    def payload(self, name, **kwargs):
        project = self.project(name, **kwargs)
        return SERVE.project_payload(project)


class CastAndLive(Fixture):
    def test_cast_is_eight_roles_in_pipeline_order(self):
        project = self.project("alpha")
        cast = SERVE.parse_cast(project / ".centuria")
        self.assertEqual([entry["role"] for entry in cast], list(ROLES))
        self.assertTrue(all(cast[i]["duty"] for i in range(8)))
        self.assertEqual(cast[0]["function"], "tesserarius-function")

    def test_every_concurrent_live_is_returned_freshest_first(self):
        from datetime import datetime, timezone
        fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        project = self.project("alpha", live={"job": "001-example",
                                             "roles": ["fabri", "medicus"],
                                             "started": fresh})
        # a second job working at the same time
        second = project / ".centuria" / "jobs" / "002-other"
        second.mkdir()
        (second / "live.json").write_text(json.dumps({
            "roles": ["signifer"], "round": 2,
            "started": "2020-01-01T00:00:00Z", "pid": 2}))
        lives = SERVE.read_lives(project)
        self.assertEqual(len(lives), 2)
        self.assertEqual(lives[0]["job"], "001-example")
        self.assertFalse(lives[0]["stale"])
        self.assertEqual(lives[1]["job"], "002-other")
        self.assertTrue(lives[1]["stale"])

    def test_missing_live_is_an_empty_list(self):
        self.assertEqual(SERVE.read_lives(self.project("alpha")), [])


class Payload(Fixture):
    def test_jobs_are_allowlisted(self):
        roster = {"reviewers": {"probator": "medium"}}
        jobs = [a_job(secret="hunter2", worktree="/private/tmp", prompts=["hi"],
                      roster=roster)]
        payload = self.payload("alpha", jobs=jobs)
        self.assertTrue(payload["ok"])
        self.assertEqual(set(payload["jobs"][0]), set(SERVE.JOB_FIELDS))
        self.assertEqual(payload["jobs"][0]["roster"], roster)
        self.assertNotIn("hunter2", json.dumps(payload))
        self.assertNotIn("worktree", payload["jobs"][0])

    def test_unreadable_project_is_an_error_not_a_crash(self):
        payload = self.payload("alpha", fail=True)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["jobs"], [])
        self.assertIn("centuria view", payload["error"])

    def test_lives_ride_along(self):
        payload = self.payload(
            "alpha", live={"job": "001-example", "roles": ["fabri"],
                           "started": "2026-11-03T10:00:00Z"})
        self.assertEqual(len(payload["lives"]), 1)
        self.assertEqual(payload["lives"][0]["roles"], ["fabri"])


class Discovery(Fixture):
    def test_real_camp_finds_immediate_children(self):
        self.project("alpha")
        self.project("beta")
        camp = SERVE.real_camp(str(self.root))
        self.assertFalse(camp["demo"])
        self.assertEqual([p["name"] for p in camp["projects"]], ["alpha", "beta"])
        self.assertTrue(all(p["ok"] for p in camp["projects"]))

    def test_empty_root_is_an_empty_camp(self):
        camp = SERVE.real_camp(str(self.root))
        self.assertEqual(camp["projects"], [])
        self.assertEqual(camp["uncharted"], [])

    def test_uncharted_lists_git_repos_without_a_centuria(self):
        self.project("alpha")
        (self.root / "alpha" / ".git").mkdir()
        (self.root / "plain" / ".git").mkdir(parents=True)
        (self.root / "notes").mkdir()
        (self.root / ".hidden" / ".git").mkdir(parents=True)
        camp = SERVE.real_camp(str(self.root))
        self.assertEqual([u["name"] for u in camp["uncharted"]], ["plain"])
        self.assertEqual(camp["uncharted"][0]["path"], str(self.root / "plain"))


class Demo(unittest.TestCase):
    def test_demo_camp_shape(self):
        camp = SERVE.demo_camp()
        self.assertTrue(camp["demo"])
        self.assertGreaterEqual(len(camp["projects"]), 4)
        for project in camp["projects"]:
            self.assertIn("ok", project)
            self.assertIn("jobs", project)
            self.assertIn("cast", project)
        legio = camp["projects"][0]
        self.assertEqual([live["job"] for live in legio["lives"]],
                         ["004-camp-ui", "005-status-api"])
        self.assertEqual(legio["lives"][0]["roles"], ["fabri"])
        self.assertEqual(len(legio["cast"]), 8)
        broken = camp["projects"][-1]
        self.assertFalse(broken["ok"])
        self.assertTrue(camp["uncharted"])


class Http(Fixture):
    def setUp(self):
        super().setUp()
        self.project("alpha")
        self.project("broken", fail=True)
        job = self.root / "alpha" / ".centuria" / "jobs" / "001-example"
        (job / "round-1").mkdir(parents=True)
        (job / "spec.md").write_text("SPEC: READY\n\n- do the thing\n")
        (job / "build.md").write_text("STATUS: READY\n")
        (job / "round-1" / "checks.md").write_text("GATE: PASS\n")
        (job / "agent-1-fabri.log").write_text("$ run\n--- stdout ---\nok\n")
        (job / "job.json").write_text("{}")
        big = job / "agent-2-fabri.log"
        big.write_text("x" * 80_000 + "\nTHE TAIL\n")
        self.httpd = SERVE.build_server(0, demo=False, root=str(self.root))
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def request(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            conn.close()

    def test_api_camp(self):
        status, ctype, body = self.request("/api/camp")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")
        data = json.loads(body)
        self.assertEqual([p["name"] for p in data["projects"]], ["alpha", "broken"])
        self.assertTrue(data["projects"][0]["ok"])
        self.assertFalse(data["projects"][1]["ok"])

    def test_static_pages(self):
        for path, ctype in (("/", "text/html"), ("/styles.css", "text/css"),
                            ("/app.js", "text/javascript"),
                            ("/assets/manifest.json", "application/json")):
            status, actual, _ = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(actual.startswith(ctype), (path, actual))

    def test_principia_skin_is_served(self):
        for path, ctype in (("/principia/", "text/html"),
                            ("/principia/app.js", "text/javascript"),
                            ("/principia/styles.css", "text/css")):
            status, actual, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(actual.startswith(ctype), (path, actual))
        _, _, page = self.request("/principia/")
        self.assertIn(b"Legio Principia", page)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/principia")
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 301)
            self.assertEqual(response.getheader("Location"), "/principia/")
        finally:
            conn.close()

    def test_the_camp_defaults_to_principia(self):
        _, _, page = self.request("/")
        self.assertIn(b"location.replace('principia/')", page)
        self.assertIn(b"skin=camp", page)

    def test_scrolls_are_listed_and_read(self):
        status, _, body = self.request("/api/job?project=alpha&job=001-example")
        self.assertEqual(status, 200)
        listing = json.loads(body)
        paths = [item["path"] for item in listing["files"]]
        self.assertIn("spec.md", paths)
        self.assertIn("round-1/checks.md", paths)
        self.assertIn("agent-1-fabri.log", paths)
        self.assertNotIn("job.json", paths)

        status, _, body = self.request(
            "/api/job/file?project=alpha&job=001-example&path=spec.md")
        self.assertEqual(status, 200)
        self.assertIn("SPEC: READY", json.loads(body)["text"])

    def test_big_logs_come_back_as_a_tail(self):
        status, _, body = self.request(
            "/api/job/file?project=alpha&job=001-example&path=agent-2-fabri.log")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["truncated"])
        self.assertIn("THE TAIL", payload["text"])
        self.assertLess(len(payload["text"]), 70_000)

    def test_scroll_paths_are_whitelisted(self):
        for path in ("job.json", "../job.json", "round-1/../../job.json",
                     "agent-9-ghost.log"):
            status, _, _ = self.request(
                f"/api/job/file?project=alpha&job=001-example&path={path}")
            self.assertEqual(status, 404, path)
        for query, expected in (("project=alpha&job=nope", 404),
                                ("project=nope&job=001-example", 404),
                                ("project=alpha", 400),
                                ("job=001-example", 400)):
            status, _, _ = self.request(f"/api/job?{query}")
            self.assertEqual(status, expected, query)

    def test_writes_are_refused(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            status, _, _ = self.request("/api/camp", method)
            self.assertEqual(status, 405, method)

    def test_demo_scrolls(self):
        payload = SERVE.demo_job_payload("legio", "004-camp-ui")
        paths = [item["path"] for item in payload["files"]]
        self.assertIn("spec.md", paths)
        self.assertIn("agent-1-fabri.log", paths)
        with self.assertRaises(LookupError):
            SERVE.demo_job_payload("legio", "nope")

    def test_path_traversal_is_refused(self):
        for path in ("/../serve.py", "/..%2Fserve.py", "/assets/../../serve.py"):
            status, _, _ = self.request(path)
            self.assertNotEqual(status, 200, path)


class LegatusHttp(Fixture):
    """Legatus talks to a fake `claude`: no network, no model, no cost."""

    def setUp(self):
        super().setUp()
        self.project("alpha")
        self.log = self.root / "claude-calls.jsonl"
        os.environ["FAKE_CLAUDE_LOG"] = str(self.log)
        self.addCleanup(os.environ.pop, "FAKE_CLAUDE_LOG", None)
        self.addCleanup(os.environ.pop, "FAKE_CLAUDE_FAIL", None)
        self.legatus = SERVE.Legatus(
            str(self.root), command=[sys.executable, str(WEB / "tests" / "fake_claude.py")],
            state_dir=self.root / ".legatus")
        self.httpd = SERVE.build_server(0, demo=False, root=str(self.root), legatus=self.legatus)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def post(self, path, body, origin="same", ctype="application/json"):
        headers = {"Content-Type": ctype}
        if origin == "same":
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
        elif origin:
            headers["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request("POST", path, body=json.dumps(body), headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_payload_names_the_model_and_hands_out_a_token(self):
        status, data = self.get("/api/legatus")
        self.assertEqual(status, 200)
        self.assertTrue(data["enabled"])
        self.assertEqual(data["model"], "claude-opus-5-5")
        self.assertTrue(data["token"])
        self.assertEqual(data["messages"], [])

    def test_ask_starts_then_resumes_one_conversation(self):
        token = self.get("/api/legatus")[1]["token"]
        status, data = self.post("/api/legatus/ask", {"token": token, "text": "what needs me?",
                                                      "context": "the operator is looking at alpha"})
        self.assertEqual(status, 200)
        self.assertEqual(data["message"]["role"], "legatus")
        self.assertEqual(data["message"]["text"], "echo: what needs me?")
        self.post("/api/legatus/ask", {"token": token, "text": "and now?"})
        first, second = self.calls()
        self.assertEqual(first["argv"][:4], ["-p", "--output-format", "json", "--model"])
        self.assertIn("claude-opus-5-5", first["argv"])
        self.assertIn("--session-id", first["argv"])
        self.assertIn("--resume", second["argv"])
        session = first["argv"][first["argv"].index("--session-id") + 1]
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], session)
        self.assertTrue(first["prompt"].startswith("Context: the operator is looking at alpha"))
        for argv in (first["argv"], second["argv"]):
            self.assertIn("--allowedTools", argv)
            self.assertIn("--disallowedTools", argv)
            self.assertIn("Write", argv[argv.index("--disallowedTools"):])
            self.assertNotIn("--dangerously-skip-permissions", argv)
        messages = self.get("/api/legatus")[1]["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "legatus", "user", "legatus"])

    def test_only_this_page_may_ask(self):
        token = self.get("/api/legatus")[1]["token"]
        status, _ = self.post("/api/legatus/ask", {"token": token, "text": "hi"},
                              origin="http://evil.example")
        self.assertEqual(status, 403)
        status, _ = self.post("/api/legatus/ask", {"token": "wrong", "text": "hi"})
        self.assertEqual(status, 403)
        status, _ = self.post("/api/legatus/ask", {"token": token, "text": "hi"}, ctype="text/plain")
        self.assertEqual(status, 415)
        status, _ = self.post("/api/camp", {"token": token})
        self.assertEqual(status, 405)
        self.assertFalse(self.log.exists())

    def test_reset_starts_a_new_conversation(self):
        token = self.get("/api/legatus")[1]["token"]
        self.post("/api/legatus/ask", {"token": token, "text": "hi"})
        before = self.legatus.session()["id"]
        status, _ = self.post("/api/legatus/reset", {"token": token})
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/api/legatus")[1]["messages"], [])
        self.assertNotEqual(self.legatus.session()["id"], before)
        self.post("/api/legatus/ask", {"token": token, "text": "again"})
        self.assertIn("--session-id", self.calls()[-1]["argv"])

    def test_a_failed_answer_is_shown_not_hidden(self):
        os.environ["FAKE_CLAUDE_FAIL"] = "1"
        token = self.get("/api/legatus")[1]["token"]
        status, data = self.post("/api/legatus/ask", {"token": token, "text": "hi"})
        self.assertEqual(status, 200)
        self.assertEqual(data["message"]["role"], "error")
        self.assertIn("failed on purpose", data["message"]["text"])
        self.assertFalse(self.legatus.session()["started"])

    def test_off_unless_set_up_and_always_off_in_demo(self):
        plain = SERVE.build_server(0, demo=False, root=str(self.root))
        try:
            self.assertFalse(plain.legatus.payload()["enabled"])
            self.assertIsNone(plain.legatus.payload()["token"])
        finally:
            plain.server_close()
        self.assertFalse(SERVE.make_legatus(str(self.root), True, True, None).enabled)
        self.assertFalse(SERVE.make_legatus(str(self.root), False, False, None).enabled)


class Assets(unittest.TestCase):
    def test_manifest_and_files_exist(self):
        assets = WEB / "assets"
        manifest = json.loads((assets / "manifest.json").read_text())
        self.assertGreater(len(manifest), 30)
        for name, entry in manifest.items():
            if name.startswith("_"):
                continue
            self.assertTrue((assets / entry["file"]).is_file(), entry["file"])
            self.assertGreater(entry["w"], 0)
            self.assertGreater(entry["h"], 0)

    def test_the_cast_and_backgrounds_are_there(self):
        manifest = json.loads((WEB / "assets" / "manifest.json").read_text())
        for role in ROLES:
            self.assertIn(f"role-{role}", manifest)
            self.assertIn(f"role-{role}-working", manifest)
        for name in ("camp-ground", "tent-interior", "tent", "tent-warped",
                     "board", "note", "desk"):
            self.assertIn(name, manifest)


if __name__ == "__main__":
    unittest.main()
