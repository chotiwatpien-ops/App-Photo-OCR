# -*- coding: utf-8 -*-
"""Every package the pool's OCR runs on has one fixed version.

A runner installs these fresh on every round. Left open, a new onnxruntime, opencv, numpy or Pillow
release changes what the pool reads from the same picture, and nothing in the repository shows it."""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def packages(file_name):
    lines = [ln.split("#")[0].strip() for ln in (HERE / file_name).read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln]


pairing = packages("requirements-pairing.txt")
loose = [p for p in pairing if not re.fullmatch(r"[A-Za-z0-9_.\-]+==[0-9][0-9A-Za-z.]*", p)]
check("ทุกบรรทัดใน requirements-pairing.txt ระบุรุ่นตายตัว (==)", not loose, loose)
names = {p.split("==")[0].lower().replace("_", "-") for p in pairing}
for need in ("rapidocr-onnxruntime", "onnxruntime", "opencv-python", "numpy"):
    check(f"{need} อยู่ในรายการที่ล็อกรุ่น", need in names, sorted(names))
pillow = [p for p in packages("requirements.txt") if p.lower().startswith("pillow")]
check("Pillow ใน requirements.txt ระบุรุ่นตายตัว", len(pillow) == 1 and "==" in pillow[0], pillow)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
