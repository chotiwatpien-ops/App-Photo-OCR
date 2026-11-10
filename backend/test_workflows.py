# -*- coding: utf-8 -*-
"""Every GitHub workflow has the shape GitHub accepts.

A YAML file can parse and still be refused at startup: on 2026-11-10 an edit to ingest.yml put
the jobs inside the workflow's inputs, the file still loaded as YAML, and every round failed
before it began. These checks are the ones that would have caught it."""
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
TOP = {"name", "run-name", "on", True, "permissions", "env", "defaults", "concurrency", "jobs"}
INPUT_KEYS = {"description", "type", "default", "required", "options"}
JOB_KEYS = {"name", "needs", "if", "runs-on", "timeout-minutes", "steps", "outputs", "concurrency",
            "permissions", "env", "defaults", "strategy", "continue-on-error", "environment",
            "services", "container"}
ok = True


def check(name, cond, got=None):
    global ok
    if not cond:
        print("✗", name, "" if got is None else f"→ {got}")
    ok = ok and cond


files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
for f in files:
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    n = f.name
    check(f"{n}: top-level keys", set(d) <= TOP, set(d) - TOP)
    on = d.get(True, d.get("on")) or {}
    inputs = ((on.get("workflow_dispatch") or {}) if isinstance(on, dict) else {}).get("inputs") or {}
    for k, v in inputs.items():
        check(f"{n}: input '{k}' is an input", isinstance(v, dict) and "description" in v and set(v) <= INPUT_KEYS, v)
    jobs = d.get("jobs") or {}
    check(f"{n}: has jobs", bool(jobs))
    for j, body in jobs.items():
        check(f"{n}: job '{j}' keys", isinstance(body, dict) and set(body) <= JOB_KEYS, body if not isinstance(body, dict) else set(body) - JOB_KEYS)
        if not isinstance(body, dict):
            continue
        check(f"{n}: job '{j}' runs somewhere and has steps", "runs-on" in body and isinstance(body.get("steps"), list))
        needs = body.get("needs")
        for need in ([needs] if isinstance(needs, str) else needs or []):
            check(f"{n}: job '{j}' needs an existing job", need in jobs, need)
        for s in body.get("steps") or []:
            check(f"{n}: job '{j}' step has uses or run", isinstance(s, dict) and ("uses" in s or "run" in s), s)
            if isinstance(s, dict) and "uses" in s and s["uses"].startswith("actions/checkout@"):
                check(f"{n}: checkout on a current version", s["uses"] != "actions/checkout@v4", s["uses"])
        text = yaml.safe_dump(body)
        check(f"{n}: job '{j}' reads no other job's steps", "steps.gate." not in text)

print(f"ตรวจ {len(files)} workflow")
print("ผ่านทั้งหมด ✅" if ok else "✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
