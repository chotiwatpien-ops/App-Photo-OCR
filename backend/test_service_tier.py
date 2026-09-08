# -*- coding: utf-8 -*-
"""Saver or Standard comes from the chip on the slip; the group only says the wheel.

A job is one group for the whole week, and the workbook took its Service Type from that — so
a rider whose job was opened under 2 W Standard had every Saver slip come out 'Standard Bike'
(37 riders, ~870 rows, 2026-09-09). The passenger fare is computed from the type, so those
rows were also 14% too dear.
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-tier-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import pipeline                                                 # noqa: E402
import service_audit as sa                                      # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


ns = pipeline.normalize_service
check("ชิปบอก Saver, job อยู่กลุ่ม Standard → Saver Bike พร้อมหมายเหตุ",
      ns("Saver Bike", "2 W Standard") == ("Saver Bike", "ประเภทตามชิปบนสลิป: Saver Bike (job อยู่กลุ่ม 2 W Standard)"))
check("ชิปบอก Standard, job อยู่กลุ่ม Saver → Standard Bike",
      ns("Standard Bike", "2 W Saver")[0] == "Standard Bike")
check("ชิปกับกลุ่มตรงกัน → ไม่มีหมายเหตุ", ns("Saver Bike", "2 W Saver") == ("Saver Bike", None))
check("ล้อยังมาจากกลุ่ม: ชิป JustGrab ในกลุ่มรถยนต์ → Standard Car",
      ns("Standard (JustGrab)", "4 W Standard") == ("Standard Car", None))
check("รถผิดล้อยังบันทึกตามรูปเหมือนเดิม",
      ns("Saver Car", "2 W Saver") == ("Saver Car", "บันทึกตามรูป: Saver Car (โฟลเดอร์อยู่กลุ่ม 2 W Saver)"))
check("AI อ่านชิปไม่ได้ → ใช้กลุ่ม", ns(None, "2 W Saver") == ("Saver Bike", None))
check("ครึ่งล่างไม่มีชิป (trust_tier=False) → ใช้กลุ่ม แม้ AI จะเดามา",
      ns("Standard Bike", "2 W Saver", trust_tier=False) == ("Saver Bike", None))
check("job ไม่มีกลุ่ม → ใช้ที่ AI อ่านล้วน ๆ", ns("Saver Bike", None) == ("Saver Bike", None))

# the audit's verdict per row
check("แถว Standard Bike ในโฟลเดอร์ 2 W Saver → ต้องแก้เป็น Saver Bike",
      sa.verdict("Standard Bike", "2 W Saver") == ("flip", "Saver Bike"))
check("แถว Saver Bike ในโฟลเดอร์ 2 W Saver → ตรง", sa.verdict("Saver Bike", "2 W Saver") == ("ok", None))
check("รถยนต์ก็เทียบได้", sa.verdict("Saver Car", "4 W Standard") == ("flip", "Standard Car"))
check("โฟลเดอร์ไม่บอกอะไร (None) → ไม่ตัดสิน", sa.verdict("Saver Bike", None) == ("unknown", None))
check("แถวไม่มีประเภท → ไม่ตัดสิน", sa.verdict(None, "2 W Saver") == ("unknown", None))


class FakeDrive:
    def __init__(self, meta):
        self.meta = meta

    def file_meta(self, fid):
        return self.meta[fid]


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def trips_of_job(self, jid):
        return self.rows.get(jid, [])


sa.db = FakeDB({1: [{"id": 11, "file_name": "a", "service_type": "Standard Bike", "status": "done", "committed": 1, "note": None},
                    {"id": 12, "file_name": "b", "service_type": "Saver Bike", "status": "done", "committed": 1, "note": None}],
                2: [{"id": 21, "file_name": "c", "service_type": "Standard Car", "status": "done", "committed": 1, "note": None}]})
d = FakeDrive({"f1": {"id": "f1", "name": "05-สุทธิ Win", "parents": ["g-saver"]},
               "g-saver": {"id": "g-saver", "name": "2 W Saver", "parents": ["wk"]},
               "f2": {"id": "f2", "name": "01-ฉ Taxi", "parents": ["g-car"]},
               "g-car": {"id": "g-car", "name": "4 W Standard", "parents": ["wk"]}})
res = sa.audit(d, [{"id": 1, "driver_name": "สุทธิ Win", "category": "2 W Standard", "drive_folder_id": "f1"},
                   {"id": 2, "driver_name": "ฉ Taxi", "category": "4 W Standard", "drive_folder_id": "f2"},
                   {"id": 3, "driver_name": "ไม่มีโฟลเดอร์", "category": None, "drive_folder_id": None}], log=lambda *_: None)
(j1, g1, r1, fl1), (j2, g2, r2, fl2), (j3, g3, r3, fl3) = res
check("job ที่จดว่า Standard แต่โฟลเดอร์อยู่ Saver: เจอ 1 แถวที่ต้องแก้ (อีกแถวตรงอยู่แล้ว)",
      g1 == "2 W Saver" and len(fl1) == 1 and fl1[0][0]["id"] == 11 and fl1[0][1] == "Saver Bike")
check("job ที่ตรงกันไม่มีอะไรต้องแก้", g2 == "4 W Standard" and fl2 == [])
check("job ที่ไม่มีโฟลเดอร์: ไม่ตัดสิน ไม่พัง", g3 is None and fl3 == [])

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
