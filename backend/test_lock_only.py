# -*- coding: utf-8 -*-
"""close_week --mode lock: a week that is dropped, not delivered, is locked and nothing else runs."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-lock-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import close_week                                               # noqa: E402
import db                                                       # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


ran = []
close_week.Runner.go = lambda self: ran.append(1) or 0
rc1 = close_week.main(["--from", "2026-09-28", "--to", "2026-10-04", "--mode", "lock"])
rc2 = close_week.main(["--from", "2026-09-28", "--to", "2026-10-04", "--mode", "lock"])
check("ล็อกสัปดาห์แล้ว", "2026-09-28" in db.closed_weeks())
check("ไม่ได้รันขั้นปิดสัปดาห์ (ไม่ย้าย ไม่ยกงาน ไม่ออกไฟล์)", ran == [])
check("กดซ้ำได้ ไม่ error", rc1 == 0 and rc2 == 0)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
