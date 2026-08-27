# -*- coding: utf-8 -*-
"""End-to-end batch round on a throwaway database: submit, wait, collect, pair, approve.

Real images pulled from Drive and a real batch job — only the database and the Drive uploads
are fakes, so what is being tested is the actual submit/collect path the round will use.
"""
import os
import sys
import tempfile
import time

os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-batch-")
os.environ.pop("DATABASE_URL", None)          # local sqlite, never production
sys.path.insert(0, "backend")
sys.stdout.reconfigure(encoding="utf-8")

PROD = ("postgresql+psycopg://neondb_owner:npg_XvkWCE5z9SYA@ep-calm-bread-b3zclnuw.c-4."
        "ap-southeast-1.aws.neon.tech/neondb?sslmode=require&connect_timeout=15")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import ingest                                                   # noqa: E402
from drive_client import DriveClient                            # noqa: E402
from sqlalchemy import create_engine, func, select, text        # noqa: E402

assert "sqlite" in config.DATABASE_URL, f"ต้องเป็น sqlite เท่านั้น ได้ {config.DATABASE_URL}"
db.init_db()

# --- borrow a few real half-screenshot pairs from production (read only) ---
prod = create_engine(PROD)
with prod.begin() as c:
    rows = c.execute(text("""
        SELECT t.file_name, f.drive_id
        FROM trips t JOIN ingested_files f ON f.trip_id = t.id
        WHERE t.status IN ('done','merged') AND t.job_id = (
            SELECT job_id FROM trips WHERE status='merged' GROUP BY job_id
            HAVING count(*) >= 3 LIMIT 1)
        ORDER BY t.file_name LIMIT 6""")).all()
print(f"ยืมรูปจริงมา {len(rows)} ใบ: {[r[0] for r in rows]}")

drive_real = DriveClient(config.GOOGLE_SERVICE_ACCOUNT, config.DRIVE_OAUTH_TOKEN)
images = [(r[0], drive_real.download(r[1])) for r in rows]

job_id = db.create_job("ทดสอบ batch", "S", "2026-08-17", "2026-08-23", category="4 W Standard")
trip_ids = [db.create_trip(job_id, name, data, "image/jpeg") for name, data in images]
print(f"สร้าง job #{job_id} · trip {trip_ids}")


class FakeDrive:
    """Drive stands in for the parts a collect touches — uploads go nowhere."""

    def ensure_folder(self, parent, name):
        return "folder"

    def upload_file(self, *a, **k):
        return "file"

    def upload_xlsx(self, *a, **k):
        return "xlsx"

    def download(self, drive_id):
        raise RuntimeError("ไม่ควรต้องโหลดซ้ำในเทสต์นี้")


import batch_client                                             # noqa: E402
items = [(tid, *db.get_trip_image(tid)) for tid in trip_ids]
t0 = time.time()
jobs = batch_client.submit(items, display_name="test-round")
for b in jobs:
    db.record_batch(b["name"], b["model"], b["trips"], run_id=None)
print(f"ส่ง batch {len(jobs)} ก้อน: {[b['name'][-10:] for b in jobs]}")

with db.engine.begin() as c:
    held = c.execute(select(func.count()).select_from(db.trips)
                     .where(db.trips.c.batch_name.isnot(None))).scalar()
    stuck = db.stuck_pending_trips()
print(f"แถวที่ batch ถืออยู่ {held} · ตัวกู้ 'pending ค้าง' เห็น {len(stuck)} แถว "
      f"({'ถูกต้อง — ไม่ไปอ่านซ้ำ' if not stuck else '✗ จะอ่านซ้ำเสียเงินสองรอบ'})")

print("รอผล batch …")
state = batch_client.wait(jobs[0]["name"], timeout=1500, every=20)
print(f"  สถานะ {state} · {time.time() - t0:.0f} วินาทีนับจากส่ง")

got, errs, touched, issues = ingest.collect_batches(FakeDrive(), "exports")
print(f"\nเก็บผล: อ่านสำเร็จ {got} · error {errs} · job ที่แตะ {touched}")

with db.engine.begin() as c:
    t = db.trips.c
    for r in c.execute(select(t.id, t.file_name, t.status, t.kind, t.committed, t.check_status,
                              t.net_earnings, t.base_fare, t.merged_into, t.model, t.batch_name,
                              t.tok_in, t.tok_out)
                       .where(t.job_id == job_id).order_by(t.id)).mappings():
        print(f"  #{r['id']} {r['file_name'][:24]:26s} {r['status']:7s} kind={str(r['kind']):6s} "
              f"merged→{str(r['merged_into'] or '-'):5s} check={str(r['check_status']):5s} "
              f"net={r['net_earnings']} base={r['base_fare']} committed={r['committed']} "
              f"tok={r['tok_in']}/{r['tok_out']} batch={r['batch_name'] or '-'}")
    open_left = db.open_batches()
print(f"\nbatch ที่ยังค้าง: {len(open_left)} (ควรเป็น 0)")
print("ผลของโมเดลถูกบันทึกเป็น model:",
      {r[0] for r in db.engine.begin().__enter__().execute(select(db.trips.c.model))
       if r[0]} if False else "ดูในตารางด้านบน")
