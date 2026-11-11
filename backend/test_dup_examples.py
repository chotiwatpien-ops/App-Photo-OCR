# -*- coding: utf-8 -*-
"""The duplicate report the customer forwards to the admins (dup_examples.py, Fiat 2026-11-11):
for every repeated picture, which picture it repeats, in which album, sent by which admin, with
the two side by side, and a first sheet listing them all with a link to each picture."""
import io
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-dupex-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from openpyxl import load_workbook                              # noqa: E402
from PIL import Image                                           # noqa: E402

import duplicate_report as dr                                   # noqa: E402
import dup_examples as dx                                       # noqa: E402

ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def jpeg(color, size=(300, 600)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


class FakeDrive:
    def __init__(self, files):
        self.files, self.folders, self.where, self.downloads = dict(files), {}, {}, []

    def ensure_folder(self, parent, name):
        return self.folders.setdefault((parent, name), f"{parent}/{name}")

    def list_images(self, folder):
        return [{"id": f, "name": f.rsplit("/", 1)[1]} for f, p in self.where.items() if p == folder]

    def upload_file(self, folder, name, data, mime):
        fid = f"{folder}/{name}"
        self.files[fid], self.where[fid] = data, folder
        return fid

    def move_file(self, fid, folder):
        self.where[fid] = folder

    def download(self, fid):
        self.downloads.append(fid)
        return self.files[fid]


A, B = "2W Karnjana 1748 งาน", "4W-Taxi Meen ชุด 2"
check("ส่งโดย = แอดมินที่ชื่ออัลบั้มบอก", dx.sender(A) == "Karnjana" and dx.sender(B) == "Meen")

case = {"id": 40214, "ไรเดอร์ผู้ส่ง": A, "ไฟล์ที่ซ้ำ": f"{A}_117062+117061_฿34.jpg",
        "ลิงก์รูป": "https://drive.google.com/file/d/MINE/view", "twin_url": "https://drive.google.com/file/d/TWIN/view",
        "ซ้ำกับไฟล์": f"{A}_117068+117067_฿34.jpg", "ของไรเดอร์": A, "รูปที่ส่งลูกค้า": "005215112601.jpg",
        "ประเภทการซ้ำ": dr.KIND_SAME_WEEK, "ยอด": 34.0, "รหัสการจอง": "A-AWK4QFXGXWOEAV"}
copies = [{"ไรเดอร์ผู้ส่ง": A, "ไฟล์ที่ซ้ำ": "112687_1.jpg", "ซ้ำกับไฟล์": f"{A}/112687_0.jpg",
           "ลิงก์รูป": "https://drive.google.com/file/d/COPY/view"},
          {"ไรเดอร์ผู้ส่ง": A, "ไฟล์ที่ซ้ำ": "9_1.jpg", "ซ้ำกับไฟล์": f"{B}/9_0.jpg",
           "ลิงก์รูป": "https://drive.google.com/file/d/COPY9/view"}]
half_ids = {(A, "112687_0.jpg"): "ORIG", (B, "9_0.jpg"): "ORIG9"}
albums = [[1, A, None, 1642, 1637, 2, 1, 3, 0.002, "", None, None, "ซ้ำ", 3288, 3286, 1643, 1643, None, 1642, 5, 1748, 104],
          [2, "2W Karnjana ทดสอบ", None, 20, 20, 0, 0, 0, 0.0, "", None, None, "ไม่ซ้ำ", 40, 40, 20, 20, None, 20, None, None, None]]

found = dx.entries([], [case], copies, half_ids)
read = next(e for e in found if e.kind == "แคปจอ 2 รอบ")
copy = next(e for e in found if e.file == "112687_1.jpg")
cross = next(e for e in found if e.file == "9_1.jpg")
check("❗ งานแคปซ้ำ: บอกรูปที่ซ้ำและต้นฉบับเป็นเลขรูปใน LINE",
      read.file == "รูป 117062 + 117061" and read.orig_file == "รูป 117068 + 117067" and read.orig_id == "TWIN", read)
check("ต้นฉบับบอกชื่อในไฟล์ลูกค้า", read.counted_as == "005215112601.jpg")
check("❗ ไฟล์ซ้ำ: เจอรูปต้นฉบับมาวางเทียบ", copy.orig_file == "112687_0.jpg" and copy.orig_id == "ORIG", copy)
check("❗ ซ้ำข้ามอัลบั้ม: บอกอัลบั้มต้นฉบับ (คนละแอดมิน)", cross.orig_album == B and dx.sender(cross.orig_album) == "Meen")

files = {"MINE": jpeg("red"), "TWIN": jpeg("blue"), "COPY": jpeg("green"), "ORIG": jpeg("green"),
         "COPY9": jpeg("grey")}                                   # ORIG9 is gone from Drive
drive = FakeDrive(files)
log = []
links = dx.write(drive, "R", "2026-W46", found, albums, log=log.append)
folder = f"R/2026-W46 ตัวอย่าง/{A}"
names = sorted(f["name"] for f in drive.list_images(folder))
check("❗ รูปเปรียบเทียบรายการละ 1 รูป + การ์ดสรุป",
      set(names) == {"00 สรุป.jpg", "ไฟล์ซ้ำ 112687_1 (ต้นฉบับ 112687_0).jpg", "ไฟล์ซ้ำ 9_1 (ต้นฉบับ 9_0).jpg",
                     "แคปจอ 2 รอบ #40214 ฿34.jpg"}, names)
check("ทุกรายการได้ลิงก์รูป", set(links) == {e.name for e in found}, links)
pic = Image.open(io.BytesIO(drive.files[links[copy.name]]))
check("รูปเปรียบเทียบวางสองรูปคู่กัน", pic.width > 2 * 300, pic.size)
check("ต้นฉบับหายจาก Drive: ยังทำรูปได้ ฝั่งต้นฉบับว่าง", cross.name in links)

drive.downloads.clear()
dx.write(drive, "R", "2026-W46", found, albums, log=log.append)
check("❗ รอบถัดไปไม่โหลดรูปมาทำซ้ำ", drive.downloads == [], drive.downloads)

dx.write(drive, "R", "2026-W46", [e for e in found if e is not read], albums, log=log.append)
check("❗ รายการที่ไม่ซ้ำแล้ว รูปย้ายไป _เก่า ไม่ได้ลบ",
      drive.where[links[read.name]].endswith(dx.OLD_DIR))

rows = dr.admin_rows(found, links)
wb = load_workbook(io.BytesIO(dr.build_xlsx([], [], [], [list(r) for r in albums], rows)))
ws = wb[wb.sheetnames[0]]
head = [c.value for c in ws[1]]
check("❗ ชีทแรกคือ 'ส่งแอดมิน'", wb.sheetnames[0] == "ส่งแอดมิน" and head == dr.ADMIN_COLS, wb.sheetnames)
first = {head[i]: ws.cell(2, i + 1) for i in range(len(head))}
check("❗ แต่ละแถวบอก: ซ้ำกับรูปไหน อัลบั้มไหน ใครส่ง พร้อมลิงก์รูปเปรียบเทียบ",
      first["ส่งโดย"].value == "Karnjana" and first["ซ้ำกับรูป"].value and first["อัลบั้มของต้นฉบับ"].value
      and first["รูปเปรียบเทียบ"].hyperlink is not None and first["รูปเปรียบเทียบ"].value == "เปิดรูป",
      {k: v.value for k, v in first.items()})
check("รายงานจากหน้าเว็บ (ไม่มีชีทส่งแอดมิน) ยังเริ่มที่รายอัลบั้ม",
      load_workbook(io.BytesIO(dr.build_xlsx([], [], [], [list(r) for r in albums]))).sheetnames[0] == "รายอัลบั้ม")

lost = dx.entries([], [], copies[:1], {})[0]
check("❗ หาต้นฉบับไม่เจอ: ชื่อบอกไว้ และเจอทีหลังได้ชื่อใหม่ จึงทำรูปใหม่",
      lost.name == "ไฟล์ซ้ำ 112687_1 (ไม่พบรูปต้นฉบับ 112687_0).jpg" and lost.name != copy.name, lost.name)

import db                                                       # noqa: E402
db.init_db()
db.record_pool_run("move", "Week 9-15 Nov", {}, "", {"started_at": "2026-11-11 00:16:25", "duplicates": [
    {"week": "Week 9-15 Nov", "album": A, "file": f"{A}/112687_1.jpg", "same_as": f"{A}/112687_0.jpg",
     "same_as_id": "ORIG", "id": "COPY"}]})
check("❗ หา id ต้นฉบับจากบันทึกการจับคู่ (same_as_id)", dr.half_ids("2026-11-09") == {(A, "112687_0.jpg"): "ORIG"},
      dr.half_ids("2026-11-09"))

dx.FONTS[:] = [("/nope.ttf", "/nope-b.ttf")]
check("ไม่มีฟอนต์ไทย: ไม่ทำรูป ไม่ล้ม", dx.write(FakeDrive({}), "R", "W", found, albums, log=log.append) == {})

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
