# -*- coding: utf-8 -*-
"""--exports-only can be pointed at one week; the workbooks are still written from every row
(2026-09-11).

The sweep used to visit every job of every week. Asked to repair W36, run #171 rebuilt 1,139
pictures across W33-W35 under new names, changing the picture column of rows already delivered;
run #183 spent 29 minutes to make two. Local folders stand in for Drive, a throwaway SQLite for
the database.
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-exweek-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from io import BytesIO                                           # noqa: E402

from PIL import Image                                            # noqa: E402

import db                                                        # noqa: E402
import ingest                                                    # noqa: E402
from drive_client import LocalDrive                              # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


# --- reading the argument ---------------------------------------------------------------------
check("เว้นว่าง = ทุกสัปดาห์", ingest.parse_weeks("") is None and ingest.parse_weeks(None) is None)
check("รับรูปแบบ 2026-W37", ingest.parse_weeks("2026-W37") == {"2026-W37"})
check("เลขสัปดาห์หลักเดียวเติมศูนย์", ingest.parse_weeks("2026-W7") == {"2026-W07"})
check("รับวันที่ในสัปดาห์", ingest.parse_weeks("2026-09-07") == {"2026-W37"})
check("รับหลายค่า คั่นด้วยจุลภาค",
      ingest.parse_weeks("2026-W36, 2026-09-07") == {"2026-W36", "2026-W37"})

# --- the sweep itself -------------------------------------------------------------------------
ROOT = os.path.join(WORK, "drive")
EXPORTS = os.path.join(ROOT, "Exports")
os.makedirs(EXPORTS)
drive = LocalDrive(ROOT)


def jpeg(seed):
    buf = BytesIO()
    Image.new("RGB", (720, 1560), (10 * seed, 200, 120)).save(buf, "JPEG")
    return buf.getvalue()


def make(week_from, week_to, rider, n, seed, date):
    jid = db.find_job(rider, week_from, week_to, category="2 W Saver")
    if not jid:
        jid = db.create_job(rider, "Trips", week_from, week_to, category="2 W Saver")
    tid = db.create_trip(jid, f"{rider}{n}.jpg", jpeg(seed), "image/jpeg")
    db.update_trip(tid, {"status": "done", "kind": "full", "net_earnings": 10.0 + seed,
                         "base_fare": 10.0 + seed, "check_status": "pass", "trip_date": date})
    return jid


make("2026-08-31", "2026-09-06", "เก่า", 1, 1, "2026-09-01")
make("2026-09-07", "2026-09-13", "ใหม่", 1, 2, "2026-09-08")

errs, _ = ingest.export_only(drive, EXPORTS, with_xlsx=False, weeks={"2026-W37"})
check("ไม่มี error", errs == 0)
check("สร้างรูปเฉพาะสัปดาห์ที่สั่ง", sorted(os.listdir(EXPORTS)) == ["2026-W37"])
check("รูปของสัปดาห์นั้นถูกสร้างจริง",
      os.listdir(os.path.join(EXPORTS, "2026-W37", "2 W Saver")) == ["WK37-ใหม่1.jpg"])

errs, _ = ingest.export_only(drive, EXPORTS, with_xlsx=False, weeks=None)
check("ไม่ใส่ตัวกรอง = กวาดทุกสัปดาห์เหมือนเดิม", sorted(os.listdir(EXPORTS)) == ["2026-W36", "2026-W37"])
check("สัปดาห์เก่าได้รูปตอนนี้",
      os.listdir(os.path.join(EXPORTS, "2026-W36", "2 W Saver")) == ["WK36-เก่า1.jpg"])

# a week with no jobs asks for nothing and breaks nothing
errs, _ = ingest.export_only(drive, EXPORTS, with_xlsx=False, weeks={"2026-W40"})
check("สั่งสัปดาห์ที่ไม่มีงาน = ไม่ทำอะไร ไม่พัง", errs == 0 and sorted(os.listdir(EXPORTS)) == ["2026-W36", "2026-W37"])

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
