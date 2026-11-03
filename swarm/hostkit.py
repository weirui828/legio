"""Host adapters: turn a role file plus a task into a real agent process.

This is the same three-step contract centuria/bin/run uses — build a command line
from a host JSON, spawn it, collect it — with the job machinery removed. swarm has
no sessions: one run is one shot per reviewer, and nothing is resumed.

A host profile is the JSON files in ../hosts (shared with legio) plus swarm/hosts.
The fields that matter here:

  command      binary plus fixed flags (tokens may use {repo} {role} {model} ...)
  yolo         flags added only with --yolo
  role.mode    "system" -> the role file becomes a separate system prompt
               "concat" -> the role file is merged into the prompt
  prompt.via   "stdin" or "arg"
  cwd.mode     "process" (Popen cwd) or "flag" (e.g. codex's -C)
  model.flag   how to name a model
  model_tiers  tier -> concrete model, host-specific
  env          variables to inject: {"value": ...} or {"shell": ...}
  timeout_seconds
"""

import json
import subprocess
from pathlib import Path


class HostError(Exception):
    """The host spec is missing, malformed, or the binary is not installed."""


def load_host(path):
    p = Path(path).expanduser()
    if not p.exists():
        raise HostError(f"host spec {p} does not exist")
    try:
        prof = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise HostError(f"{p} is not valid JSON: {e}")
    for key in ("command", "role", "prompt"):
        if key not in prof:
            raise HostError(f"{p} is missing {key!r}")
    prof["_path"] = p
    return prof


def expand(tokens, subs):
    """Fill {placeholders} in a token list; leave unknown ones alone.

    Unknown placeholders are left verbatim on purpose: a host file written for a
    newer swarm should degrade visibly, not crash in the middle of a run.
    """
    out = []
    for tok in tokens:
        try:
            out.append(str(tok).format(**subs))
        except (KeyError, IndexError):
            out.append(str(tok))
    return out


def build(prof, order, yolo=False):
    """-> (cmd, body, cwd, model).

    `order` carries: role, tier, role_file, repo, run, out, cwd, header, task.
    The body always starts with the header, never with the role file's `---`
    frontmatter: a prompt passed as argv that begins with a dash is parsed as an
    option by most CLI argument parsers (dsh answered `unknown option` and echoed
    the whole prompt back).
    """
    rf = Path(order["role_file"]).expanduser()
    if not rf.exists():
        raise HostError(f"role file {rf} is missing")

    tiers = prof.get("model_tiers") or {}
    model = tiers.get(order["tier"]) or tiers.get("medium") or ""
    cwd = Path(order["cwd"]).expanduser()
    subs = {
        "role_file": str(rf),
        "cwd": str(cwd),
        "model": model,
        "repo": str(order["repo"]),
        "run": order["run"],
        "out": str(order["out"]),
        "role": order["role"],
        "reviewer": order["role"],
        "host_dir": str(Path(prof["_path"]).parent),
    }

    cmd = expand(prof["command"], subs)
    if yolo:
        cmd += expand(prof.get("yolo") or [], subs)
    if (prof.get("cwd") or {}).get("mode") == "flag":
        cmd += expand(prof["cwd"].get("flag") or [], subs)
    if (prof.get("model") or {}).get("flag"):
        cmd += expand(prof["model"]["flag"], subs)

    role_text = rf.read_text().rstrip()
    role_cfg = prof["role"]
    if role_cfg.get("mode") == "system":
        cmd += expand(role_cfg.get("flag") or [], subs)
        body = order["header"] + "\n\n" + order["task"]
    else:
        body = (order["header"] + "\n\n" + role_text + "\n\n---\n\n" + order["task"])
    return cmd, body, cwd, model


def build_env(prof):
    """Resolve the host's `env` block into the child environment.

    Each entry is either {"value": "..."} or {"shell": "..."}. The shell form lets
    a secret live in the OS keychain and be read at spawn time, so it never sits
    in a dotfile, an env export, or this repo's JSON.
    """
    import os

    env = os.environ.copy()
    for key, spec in (prof.get("env") or {}).items():
        if isinstance(spec, str):
            value = spec
        elif isinstance(spec, dict) and "value" in spec:
            value = str(spec["value"])
        elif isinstance(spec, dict) and "shell" in spec:
            try:
                res = subprocess.run(spec["shell"], shell=True, capture_output=True,
                                     text=True, timeout=spec.get("timeout", 15))
            except subprocess.TimeoutExpired:
                raise HostError(f"env {key}: `{spec['shell']}` timed out "
                                f"(is the keychain item there? it may be waiting for approval)")
            if res.returncode != 0:
                raise HostError(f"env {key}: `{spec['shell']}` failed: "
                                f"{(res.stderr or res.stdout).strip()}")
            value = res.stdout.strip()
        else:
            raise HostError(f"env {key}: needs 'value' or 'shell'")
        if not value:
            raise HostError(f"env {key}: resolved to an empty string")
        env[key] = value
    return env


def spawn(prof, cmd, body, cwd):
    """Start an agent without waiting; pair it with collect()."""
    via = (prof.get("prompt") or {}).get("via", "stdin")
    full = cmd + [body] if via == "arg" else cmd
    kwargs = {
        "cwd": str(cwd),
        "env": build_env(prof),
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE if via != "arg" else subprocess.DEVNULL,
    }
    try:
        proc = subprocess.Popen(full, **kwargs)
    except FileNotFoundError:
        raise HostError(f"{cmd[0]} is not on PATH")
    return proc, (body if via != "arg" else None)


def collect(proc, stdin_body, timeout):
    """-> (returncode, stdout, stderr). A timeout is a failure, not a crash."""
    try:
        out, err = proc.communicate(stdin_body, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return None, out or "", (err or "") + f"\n[timed out after {timeout}s]"
    return proc.returncode, out or "", err or ""
