# -*- coding: utf-8 -*-
"""Finding the pictures that hold a seat without earning one.

The allocator counts pictures on Drive, not rows in the database, so a folder full of repeats
reads as a rider with no room. What matters here is that only genuinely dead rows are picked —
taking away a picture that is carrying a delivered trip would remove that trip's evidence.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-seats-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import free_dup_seats as fs                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class FakeDrive:
    def __init__(self):
        self.images = {}
        self.tree = {}

    def ensure_folder(self, pid, name):
        fid = f"{pid}/{name}"
        self.tree.setdefault(pid, {})[name] = fid
        self.images.setdefault(fid, [])
        return fid

    def list_images(self, pid):
        if pid == "boom":
            raise RuntimeError("อ่านไม่ได้")
        return list(self.images.get(pid, []))

    def move_file(self, fid, new_parent):
        for pid, imgs in list(self.images.items()):
            keep = [i for i in imgs if i["id"] != fid]
            if len(keep) != len(imgs):
                self.images[pid] = keep
                self.images.setdefault(new_parent, []).extend(
                    [i for i in imgs if i["id"] == fid])


# --- which rows are dead -----------------------------------------------------------------------
TRIPS = {
    1: [{"id": 11, "status": "duplicate"}, {"id": 12, "status": "duplicate"},
        {"id": 13, "status": "done"}],
    2: [{"id": 21, "status": "voided"}, {"id": 22, "status": "done"}],
    3: [{"id": 31, "status": "done"}, {"id": 32, "status": "done"}],
    4: [{"id": 41, "status": "pending"}, {"id": 42, "status": "error"}],
}
JOBS = [{"id": 1, "driver_name": "สัมมา Win", "category": "2 W Saver", "drive_folder_id": "f1"},
        {"id": 2, "driver_name": "อรุณ Win", "category": "2 W Saver", "drive_folder_id": "f2"},
        {"id": 3, "driver_name": "ก Win", "category": "2 W Saver", "drive_folder_id": "f3"},
        {"id": 4, "driver_name": "ข Win", "category": "2 W Saver", "drive_folder_id": "f4"},
        {"id": 5, "driver_name": "ค Win", "category": "2 W Saver", "drive_folder_id": None}]

fs.db.get_job = lambda jid: {"trips": TRIPS.get(jid, [])}
fs.db.drive_ids_for_trips = lambda ids: {i: f"d{i}" for i in ids}

dead = fs.dead_trips(JOBS)
check("เจอ job ที่มีแถวตาย", sorted(dead) == [1, 2])
check("นับเฉพาะแถวที่ตายจริง", [t["id"] for t in dead[1]] == [11, 12]
      and [t["id"] for t in dead[2]] == [21])
check("แถวที่ยังรอผล batch ไม่ใช่แถวตาย — ห้ามแตะ", 4 not in dead)
check("job ที่ทุกแถวใช้ได้ ไม่ถูกแตะ", 3 not in dead)
check("นับเที่ยวจริงถูก", (fs.live_count(1), fs.live_count(2), fs.live_count(4)) == (1, 1, 2))

# --- which files would actually leave ----------------------------------------------------------
d = FakeDrive()
d.images["f1"] = [{"id": "d11", "name": "a.jpg"}, {"id": "d12", "name": "b.jpg"},
                  {"id": "d13", "name": "c.jpg"}]
d.images["f2"] = [{"id": "d22", "name": "e.jpg"}]          # the dead one already moved away
plan = fs.plan_for(d, JOBS, dead)
by_job = {p["job"]["id"]: p for p in plan}
check("เอาออกเฉพาะรูปของแถวที่ตาย", [f["id"] for f in by_job[1]["files"]] == ["d11", "d12"])
check("ไม่แตะรูปของแถวที่ยังใช้ได้", "d13" not in [f["id"] for f in by_job[1]["files"]])
check("รูปที่ถูกย้ายออกไปแล้ว ไม่นับซ้ำ", 2 not in by_job)
check("job ที่ไม่มีโฟลเดอร์บน Drive ข้ามไป", 5 not in by_job)
check("บอกจำนวนรูปในโฟลเดอร์กับเที่ยวจริงมาด้วย",
      (by_job[1]["on_drive"], by_job[1]["live"]) == (3, 1))

# a folder that cannot be read is reported, not guessed at
d2 = FakeDrive()
plan2 = fs.plan_for(d2, [{"id": 1, "driver_name": "ง Win", "category": "2 W Saver",
                          "drive_folder_id": "boom", "folder_name": "x"}], dead)
check("โฟลเดอร์ที่อ่านไม่ได้ ถูกรายงาน ไม่ใช่เดา",
      len(plan2) == 1 and plan2[0]["error"] and plan2[0]["files"] == [])

# --- moving is a move, never a delete ----------------------------------------------------------
d3 = FakeDrive()
d3.images["f1"] = [{"id": "d11", "name": "a.jpg"}, {"id": "d13", "name": "c.jpg"}]
hold = d3.ensure_folder("week", fs.HOLD_DIR)
dest = d3.ensure_folder(hold, "สัมมา Win")
d3.move_file("d11", dest)
check("ย้ายแล้วออกจากโฟลเดอร์ไรเดอร์", [i["id"] for i in d3.images["f1"]] == ["d13"])
check("แล้วไปโผล่ในที่พัก ไม่ได้หายไป", [i["id"] for i in d3.images[dest]] == ["d11"])

# --- how much room actually comes back ---------------------------------------------------------
# The first version summed 'quota minus live trips', which is unused capacity, not room. It went
# negative for a rider whose pictures the quota rebalance had already moved away, and those
# negatives quietly ate everybody else's real gains.
fs.config.EXPECTED_TRIPS_PER_WEEK = 21
full = [{"on_drive": 21, "live": 0, "files": [0] * 18, "job": {"category": "2 W Saver"}}]
check("โฟลเดอร์เต็ม 21 เอาออก 18 คืน 18", fs.seats_freed(full) == 18)
partial = [{"on_drive": 3, "live": 19, "files": [0], "job": {"category": "2 W Saver"}}]
check("โฟลเดอร์ที่รูปถูกย้ายไปแล้ว คืน 1 ไม่ใช่ติดลบ", fs.seats_freed(partial) == 1)
check("รวมกันแล้วต้องไม่หักล้างกันเอง", fs.seats_freed(full + partial) == 19)
over = [{"on_drive": 25, "live": 0, "files": [0] * 25, "job": {"category": "2 W Saver"}}]
check("โฟลเดอร์ที่ล้นโควตา คืนได้ไม่เกิน 21", fs.seats_freed(over) == 21)
check("แยกตามล้อได้", (fs.wheel_of("2 W Saver"), fs.wheel_of("4 W Standard")) == ("2W", "4W"))

check("ชื่อที่พักคือ _ซ้ำ", fs.HOLD_DIR == "_ซ้ำ")
check("นับสถานะตายไว้สองแบบเท่านั้น", set(fs.DEAD) == {"duplicate", "voided"})

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
