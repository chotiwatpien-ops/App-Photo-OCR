# -*- coding: utf-8 -*-
"""Run every backend test script and say which failed.

Each test_*.py is a standalone script that exits 0 when it passes. They run from the repository
root on their own throwaway SQLite (PHOTO_OCR_DATA), never on the real database, and never read
the developer's photo_ocr_config.json, so a local run and a CI run test the same thing.

    python backend/run_tests.py                 # all of them
    python backend/run_tests.py zone driver     # only files whose name contains one of these
    python backend/run_tests.py --jobs 4 --exclude test_pairing.py
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 600


def run_one(path, env):
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, str(path.relative_to(ROOT))], cwd=ROOT, env=env,
                           capture_output=True, timeout=TIMEOUT)
        code, out = p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        code, out = -1, ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace") + f"\nTIMEOUT {TIMEOUT}s"
    return path.name, code, out, time.time() - t0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help="run only test files whose name contains one of these")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="skip test files whose name contains one of these (test_pairing reads the "
                         "local sample albums when present and takes 10+ minutes)")
    a = ap.parse_args()
    files = sorted((ROOT / "backend").glob("test_*.py"))
    if a.only:
        files = [f for f in files if any(o in f.name for o in a.only)]
    files = [f for f in files if not any(x in f.name for x in a.exclude)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PHOTO_OCR_CONFIG=str(Path(tempfile.gettempdir()) / "photo-ocr-tests-no-config.json"))
    for k in ("DATABASE_URL", "RENDER", "GEMINI_API_KEY", "APP_PASSWORD"):
        env.pop(k, None)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        results = list(ex.map(lambda f: run_one(f, env), files))
    failed = [r for r in results if r[1] != 0]
    for name, code, out, secs in failed:
        print(f"\n===== ✗ {name} (exit {code}, {secs:.0f}s) =====")
        print(out[-4000:])
    print(f"\n{len(results) - len(failed)}/{len(results)} ผ่าน · {time.time() - t0:.0f}s")
    for name, *_ in failed:
        print(f"  ✗ {name}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
