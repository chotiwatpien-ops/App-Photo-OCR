# -*- coding: utf-8 -*-
"""รายงานรูปซ้ำ: คนส่งคือเจ้าของอัลบั้ม ไม่ใช่โฟลเดอร์ที่ระบบเอารูปไปวาง (2026-09-12).

รอบ W37 อัลบั้มของ ป๋อง ถูกอัปโหลดซ้ำ รูป 70 ใบไปลงโฟลเดอร์ของสรธรและธีรพงศ์ ถ้ารายงานบอกชื่อ
ตามโฟลเดอร์ ลูกค้าจะไปตีกลับผิดคน ฐานข้อมูลชั่วคราวเป็น SQLite
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-dup-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import db                                                       # noqa: E402
import duplicate_report as rep                                  # noqa: E402

db.init_db()
ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def job(driver, date_from, folder=None):
    with db.engine.begin() as c:
        return c.execute(db.jobs.insert().values(
            driver_name=driver, sheet="Trips", date_from=date_from, date_to=date_from,
            status="committed", created_at="2026-09-08 10:00:00", category="2 W Saver",
            folder_name=folder).returning(db.jobs.c.id)).scalar()


def trip(job_id, name, **kw):
    values = {"job_id": job_id, "file_name": name, "status": "done", **kw}
    with db.engine.begin() as c:
        return c.execute(db.trips.insert().values(**values).returning(db.trips.c.id)).scalar()


check("คนส่งมาจากชื่ออัลบั้มในชื่อไฟล์ ไม่ใช่โฟลเดอร์ปลายทาง",
      rep.album_of("2W-Win ป๋อง = 71_86659+86658_฿30.jpg", driver_name="สรธร") == "2W-Win ป๋อง = 71")
check("ชื่อที่ LINE ใส่ LINE_ALBUM_ นำหน้า ก็ตัดออกให้",
      rep.album_of("LINE_ALBUM_2W-Win วิน = 150_1+2_฿99.jpg") == "2W-Win วิน = 150")
check("รูปเดี่ยวไม่มีอัลบั้ม ใช้โฟลเดอร์ต้นทางแทน",
      rep.album_of("S__97419329_0.jpg", folder_name="19-ธีรพงศ์ Win") == "19-ธีรพงศ์ Win")
check("ไม่มีอะไรเลยก็ไม่ล่ม", rep.album_of(None) == "ไม่รู้อัลบั้ม")
check("ต้นทางที่ pool จดไว้ ชนะทุกอย่าง",
      rep.album_of("S__97419329_0.jpg", folder_name="19-ธีรพงศ์ Win",
                   source_album="2W-Win ป๋อง = 71") == "2W-Win ป๋อง = 71")

# เทียบ 'ส่งใต้ชื่อคนอื่น' ได้ต่อเมื่อรู้ตัวคนส่งทั้งสองฝั่ง ไม่งั้นเป็นการเอาอัลบั้มไปชนโฟลเดอร์
_sure = {"ไรเดอร์ผู้ส่ง": "ป๋อง", "ของไรเดอร์": "เอก", "ผู้ส่งแน่ชัด": True, "ต้นฉบับแน่ชัด": True}
check("รู้ทั้งสองฝั่งและคนละคน → ใช่", rep.sent_by_someone_else(_sure))
check("คนเดียวกัน → ไม่ใช่", not rep.sent_by_someone_else(dict(_sure, ของไรเดอร์="ป๋อง")))
check("ฝั่งต้นฉบับรู้แค่ชื่อโฟลเดอร์ → ไม่นับ ไม่เดา",
      not rep.sent_by_someone_else(dict(_sure, ต้นฉบับแน่ชัด=False)))
check("ฝั่งผู้ส่งรู้แค่ชื่อโฟลเดอร์ → ไม่นับ",
      not rep.sent_by_someone_else(dict(_sure, ผู้ส่งแน่ชัด=False)))

check("โน้ตครึ่งล่างบอกประเภทได้",
      rep.kind_of({"note": "ครึ่งล่างของงานที่อนุมัติแล้ว (a.jpg) — รูปเกิน ลบได้"}, None) == rep.KIND_BOTTOM)
check("hash เดียวกัน = ไฟล์เดิมส่งซ้ำ",
      rep.kind_of({"image_hash": "aa"}, {"image_hash": "aa"}) == rep.KIND_SAME_FILE)
check("ต้นฉบับอยู่คนละสัปดาห์ = ซ้ำข้ามสัปดาห์",
      rep.kind_of({"date_from": "2026-09-07"}, {"date_from": "2026-08-31"}) == rep.KIND_OTHER_WEEK)
check("ต้นฉบับสัปดาห์เดียวกัน = ซ้ำในสัปดาห์",
      rep.kind_of({"date_from": "2026-09-07"}, {"date_from": "2026-09-07"}) == rep.KIND_SAME_WEEK)

# ป๋องส่งอัลบั้มซ้ำ: ใบแรกไปลงโฟลเดอร์สรธรและอนุมัติแล้ว ใบหลังไปลงธีรพงศ์และถูกพักเป็นซ้ำ
j_first, j_second = job("สรธร", "2026-09-07"), job("ธีรพงศ์", "2026-09-07")
first = trip(j_first, "2W-Win ป๋อง = 71_86659+86658_฿30.jpg", committed=1, booking_code="A" * 20,
             net_earnings=30.0, customer_image="WK37-สรธร3.jpg", image_hash="h1")
trip(j_second, "2W-Win ป๋อง = 71_86659+86658_฿30.jpg", status="duplicate", booking_code="A" * 20,
     net_earnings=30.0, duplicate_of=first, image_hash="h1",
     note="ทิ้งอัตโนมัติ: ซ้ำกับ ... ที่อนุมัติแล้ว")
# รหัสเดียวกันแต่ยอดไม่ตรง ยังอยู่ในคิว ต้องให้คนตัดสิน ห้ามส่งไปตีกลับ
j_third = job("ชยพล", "2026-09-07")
trip(j_third, "2W-Win เอก = 306_87733+877321_฿53.jpg", booking_code="B" * 20, net_earnings=53.0,
     duplicate_of=first)

_rows, _twins = rep.load("2026-09-07", "2026-09-13")
_cases, _undecided = rep.build(_rows, _twins)
check("เคสที่พร้อมตีกลับมี 1 ใบ", len(_cases) == 1)
check("เคสที่ต้องให้คนตัดสินไม่ปนเข้าไป", len(_undecided) == 1)
check("ตีกลับไปที่ ป๋อง ไม่ใช่ ธีรพงศ์ ที่ระบบเอารูปไปวาง",
      _cases[0]["ไรเดอร์ผู้ส่ง"] == "2W-Win ป๋อง = 71" and _cases[0]["โฟลเดอร์ที่ระบบวาง"] == "ธีรพงศ์")
check("บอกได้ว่าซ้ำกับไฟล์ไหน และรูปที่ส่งลูกค้าชื่ออะไร",
      _cases[0]["ซ้ำกับไฟล์"] == "2W-Win ป๋อง = 71_86659+86658_฿30.jpg"
      and _cases[0]["รูปที่ส่งลูกค้า"] == "WK37-สรธร3.jpg")
check("ไฟล์ไบต์เดียวกัน ระบุประเภทว่าไฟล์เดิมส่งซ้ำ",
      _cases[0]["ประเภทการซ้ำ"] == rep.KIND_SAME_FILE)
check("สรุปรวมรายผู้ส่งได้", rep.summary(_cases)["2W-Win ป๋อง = 71"]["ใบซ้ำ"] == 1)

_x = rep.write_xlsx(os.path.join(WORK, "dup.xlsx"), _cases, _undecided)
from openpyxl import load_workbook                              # noqa: E402
_wb = load_workbook(_x)
check("ไฟล์ Excel มีสามชีต", _wb.sheetnames == ["สรุปรายผู้ส่ง", "รายใบ", "ค้างตัดสิน"])
check("ชีตรายใบมีช่องไว้กรอกผลการตีกลับ",
      {"สถานะเคส", "ผู้ตีกลับ", "คำตอบผู้ส่ง"} <= {c.value for c in _wb["รายใบ"][1]})
check("รันทั้งสคริปต์แล้วไม่ error", rep.main(["--from", "2026-09-07", "--to", "2026-09-13"]) == 0)

# วางลง Drive แยกจากไฟล์หลักที่ส่งลูกค้า — Ops 2026-09-13
check("ชื่อไฟล์บอกสัปดาห์ ไม่ใช่วันที่", rep.report_name("2026-09-07") == "รูปซ้ำ_2026-W37.xlsx")


class _FakeDrive:
    def __init__(self):
        self.folders, self.files = {}, {}

    def ensure_folder(self, parent, name):
        return self.folders.setdefault((parent, name), f"{parent}/{name}")

    def upload_xlsx(self, parent, name, data):
        self.files[(parent, name)] = data            # ชื่อเดิมในโฟลเดอร์เดิม = ทับ
        return f"id:{name}"


_d = _FakeDrive()
_data = rep.build_xlsx(_cases, _undecided)
_folder, _fid = rep.upload_to_drive(_d, "EXPORTS", "2026-09-07", _data)
check("วางไว้ในโฟลเดอร์ของตัวเองใต้ Exports ไม่ใช่ปนกับไฟล์หลัก",
      _folder == f"EXPORTS/{rep.DRIVE_DIR}" and ("EXPORTS", "Rider Trips.xlsx") not in _d.files)
check("ไฟล์ที่วางคือ Excel ที่เปิดได้จริง",
      load_workbook(__import__("io").BytesIO(_d.files[(_folder, "รูปซ้ำ_2026-W37.xlsx")])).sheetnames
      == ["สรุปรายผู้ส่ง", "รายใบ", "ค้างตัดสิน"])
rep.upload_to_drive(_d, "EXPORTS", "2026-09-07", _data)
check("รันซ้ำแล้วทับฉบับเดิม ไม่สร้างไฟล์ชื่อซ้ำเพิ่ม", len(_d.files) == 1)

shutil.rmtree(WORK, ignore_errors=True)
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
