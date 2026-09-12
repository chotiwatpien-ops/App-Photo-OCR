# -*- coding: utf-8 -*-
"""เก็บกวาดรูปซ้ำออกจากโฟลเดอร์ไรเดอร์ท้ายรอบ + กู้คืนแล้วรูปต้องกลับ (2026-09-13).

เดิมเป็นปุ่มที่ต้องมีคนนึกได้ว่าต้องกด W37 จึงสะสมรูปซ้ำไว้ 475 ใบใน 52 โฟลเดอร์ ไรเดอร์ที่ถือ
รูปซ้ำ 21 ใบโดยมีงานจริงใบเดียวยังถูกนับว่าเต็ม งานใหม่เลยไม่มีที่ลง ตอนนี้รอบ ingest ทำเองท้ายรอบ
แต่มีเพดานกันกวาดพลาด และการกู้คืนต้องดึงรูปกลับมาด้วย

Drive เป็นของปลอมทั้งหมด ไม่มีอะไรออกเน็ต
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-seats-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import free_dup_seats as fds                                    # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class FakeDrive:
    """โฟลเดอร์เป็น dict: id -> [รูป] · จำการย้ายไว้ให้ตรวจได้"""

    def __init__(self, folders):
        self.folders = folders
        self.moves = []
        self.made = {}

    def list_images(self, fid):
        return list(self.folders.get(fid, []))

    def ensure_folder(self, parent, name):
        fid = f"{parent}/{name}"
        self.made[fid] = name
        self.folders.setdefault(fid, [])
        return fid

    def move_file(self, file_id, dest):
        self.moves.append((file_id, dest))
        for fid, imgs in self.folders.items():
            keep = [i for i in imgs if i["id"] != file_id]
            if len(keep) != len(imgs):
                moved = next(i for i in imgs if i["id"] == file_id)
                self.folders[fid] = keep
                self.folders.setdefault(dest, []).append(moved)
                return True
        return False


def job(driver, folder_id, date_from="2026-09-07"):
    with db.engine.begin() as c:
        return c.execute(db.jobs.insert().values(
            driver_name=driver, sheet="Trips", date_from=date_from, date_to="2026-09-13",
            status="committed", created_at="2026-09-08 10:00:00", category="2 W Saver",
            folder_name=driver, drive_folder_id=folder_id).returning(db.jobs.c.id)).scalar()


def trip(job_id, name, status, drive_id):
    with db.engine.begin() as c:
        tid = c.execute(db.trips.insert().values(job_id=job_id, file_name=name, status=status)
                        .returning(db.trips.c.id)).scalar()
        c.execute(db.ingested_files.insert().values(drive_id=drive_id, name=name, job_id=job_id,
                                                    trip_id=tid, ingested_at="2026-09-08 10:00:00"))
    return tid


JOB_FOLDER = "folder-ป๋อง"
jid = job("ป๋อง", JOB_FOLDER)
dead_ids = [trip(jid, f"ซ้ำ{i}.jpg", "duplicate", f"d{i}") for i in range(3)]
live_id = trip(jid, "จริง.jpg", "done", "live1")
imgs = [{"id": f"d{i}", "name": f"ซ้ำ{i}.jpg"} for i in range(3)] + [{"id": "live1", "name": "จริง.jpg"}]
jobs = [dict(j) for js in db.jobs_by_week().values() for j in js]

drive = FakeDrive({JOB_FOLDER: list(imgs), "inbox": []})
res = fds.sweep(drive, jobs, "2026-09-07", "2026-09-13", apply=False)
check("นับรูปซ้ำในโฟลเดอร์ได้ถูก", res["files"] == 3)
check("โหมดรายงานไม่ย้ายอะไร", res["moved"] == 0 and len(drive.folders[JOB_FOLDER]) == 4)

# เพดาน: เกินแล้วต้องไม่ย้าย และต้องบอกว่าเกิน
drive2 = FakeDrive({JOB_FOLDER: list(imgs), "inbox": []})
said = []
res2 = fds.sweep(drive2, jobs, "2026-09-07", "2026-09-13", apply=True, cap=2, log=said.append)
check("เกินเพดานแล้วไม่ย้ายสักใบ", res2["over_cap"] and res2["moved"] == 0
      and len(drive2.folders[JOB_FOLDER]) == 4)
check("บอกเหตุผลที่ไม่ย้ายไว้ใน log", any("เกินเพดาน" in s for s in said))
check("ค่าเริ่มต้นของเพดานคือ 150 ใบต่อรอบ", fds.SWEEP_CAP == 150 and config.CLEAN_DUP_SEATS_MAX == 150)

# รอบอัตโนมัติกวาดเฉพาะสัปดาห์ที่ยังไม่ถูกกดปิด — กฎเต็มอยู่ใน test_week_close.py
check("สัปดาห์ที่ยังไม่มีใครกดปิด = กวาดได้",
      fds.week_is_open("2026-09-07", "2026-09-13", closed=set(), today="2026-09-13"))
check("สัปดาห์ที่กดปิดแล้ว = ไม่แตะ",
      not fds.week_is_open("2026-08-31", "2026-09-06", closed={"2026-08-31"}, today="2026-09-13"))
check("รอบ ingest เปิดใช้การเก็บกวาดเป็นค่าเริ่มต้น", config.CLEAN_DUP_SEATS is True)

# ใต้เพดาน: ย้ายรูปซ้ำออก เหลือแต่รูปของงานจริง
drive3 = FakeDrive({JOB_FOLDER: list(imgs), "inbox": []})


class FakeWeek:
    name = "Week 7-13 Sep"


import rebalance_quota                                          # noqa: E402
_orig_week = rebalance_quota.week_folder
rebalance_quota.week_folder = lambda *a, **k: {"id": "inbox", "name": "Week 7-13 Sep"}
res3 = fds.sweep(drive3, jobs, "2026-09-07", "2026-09-13", apply=True, cap=150, log=lambda *a: None)
check("ย้ายรูปซ้ำออกครบ 3 ใบ", res3["moved"] == 3)
check("รูปของงานจริงยังอยู่ในโฟลเดอร์ไรเดอร์",
      [i["id"] for i in drive3.folders[JOB_FOLDER]] == ["live1"])
check("รูปซ้ำไปอยู่ใต้ _ซ้ำ/<ไรเดอร์>", all(dest.endswith(f"{fds.HOLD_DIR}/ป๋อง")
                                              for _fid, dest in drive3.moves))

# กู้คืน: แถวกลับเข้าคิว และรูปต้องกลับเข้าโฟลเดอร์ไรเดอร์ด้วย
check("กู้คืนแถวได้", db.restore_discarded(dead_ids[0]))
check("กู้คืนแล้วรูปกลับเข้าโฟลเดอร์ไรเดอร์", fds.return_picture(dead_ids[0], drive=drive3)
      and "d0" in [i["id"] for i in drive3.folders[JOB_FOLDER]])
check("รูปที่ยังซ้ำอยู่ไม่ถูกดึงกลับมาด้วย",
      sorted(i["id"] for i in drive3.folders[JOB_FOLDER]) == ["d0", "live1"])
check("Drive ล่มตอนย้ายกลับ ไม่ทำให้การกู้คืนพัง",
      fds.return_picture(dead_ids[1], drive=object(), log=lambda *a: None) is False)
check("แถวที่ไม่มีอยู่จริง ไม่ทำให้ล่ม", fds.return_picture(99999, drive=drive3) is False)

rebalance_quota.week_folder = _orig_week
shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
