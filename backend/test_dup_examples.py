# -*- coding: utf-8 -*-
"""Pictures of each week's repeats, ready to post in LINE (dup_examples.py, Fiat 2026-11-11):
each repeat beside the trip it repeats, one sample exact copy per album, a summary card, nothing
made twice, and a row that stopped being a repeat moves its picture aside."""
import io
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-dupex-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

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
        self.files, self.folders, self.where, self.downloads = dict(files), {}, {}, 0

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
        self.downloads += 1
        return self.files[fid]


ALBUM = "2W Karnjana 1748 งาน"
case = {"id": 40214, "ไรเดอร์ผู้ส่ง": ALBUM, "ลิงก์รูป": "https://drive.google.com/file/d/MINE/view",
        "twin_url": "https://drive.google.com/file/d/TWIN/view", "ประเภทการซ้ำ": dr.KIND_SAME_WEEK,
        "ยอด": 34.0, "รหัสการจอง": "A-AWK4QFXGXWOEAV", "วันที่งาน": "2026-11-15"}
copies = [{"ไรเดอร์ผู้ส่ง": ALBUM, "ไฟล์ที่ซ้ำ": f"11268{i}_1.jpg", "ซ้ำกับไฟล์": f"{ALBUM}/11268{i}_0.jpg",
           "ลิงก์รูป": f"https://drive.google.com/file/d/COPY{i}/view"} for i in range(3)]
albums = [[1, ALBUM, None, 1642, 1637, 3, 1, 4, 0.002, "ในอัลบั้มเดียวกัน", None, None, "ซ้ำ"],
          [2, "2W Karnjana ทดสอบ", None, 20, 20, 0, 0, 0, 0.0, "", None, None, "ไม่ซ้ำ"]]

ex = dx.examples([], [case], copies)
check("งานแคปซ้ำ: รูปคู่กัน ใบที่นับแล้วอยู่ซ้าย ใบนี้อยู่ขวา",
      ex[0].pictures[0][0] == "TWIN" and ex[0].pictures[1][0] == "MINE" and ex[0].name.startswith("#40214"), ex[0])
check("ไฟล์ซ้ำเป๊ะ: ตัวอย่างเดียวต่ออัลบั้ม บอกจำนวนทั้งหมด",
      sum(1 for e in ex if len(e.pictures) == 1) == 1 and "3 ไฟล์" in ex[1].sub, ex[1:])

drive = FakeDrive({"MINE": jpeg("red"), "TWIN": jpeg("blue"), "COPY0": jpeg("green", (200, 400))})
log = []
made = dx.write(drive, "R", "2026-W46", [], [case], copies, albums, log=log.append)
folder = f"R/2026-W46 ตัวอย่าง/{ALBUM}"
names = sorted(f["name"] for f in drive.list_images(folder))
check("❗ วางในโฟลเดอร์ของอัลบั้ม: สรุป · งานแคปซ้ำ · ตัวอย่างไฟล์ซ้ำ",
      names == ["#40214 แคปจอ 2 รอบ ฿34.jpg", "00 สรุป.jpg", "ไฟล์เดียวกัน 112680_1.jpg"] and made == 2, names)
pic = Image.open(io.BytesIO(drive.files[f"{folder}/#40214 แคปจอ 2 รอบ ฿34.jpg"]))
check("รูปคู่กว้างพอสองใบ และเป็น JPEG", pic.format == "JPEG" and pic.width > 2 * 300, pic.size)
check("อัลบั้มที่ไม่ซ้ำ ไม่มีโฟลเดอร์ตัวอย่าง", not drive.list_images("R/2026-W46 ตัวอย่าง/2W Karnjana ทดสอบ"))

before = drive.downloads
dx.write(drive, "R", "2026-W46", [], [case], copies, albums, log=log.append)
check("❗ รอบถัดไปไม่โหลดรูปมาทำซ้ำ (ทำเฉพาะสรุป)", drive.downloads == before, drive.downloads - before)

dx.write(drive, "R", "2026-W46", [], [], copies, albums, log=log.append)
check("❗ แถวที่ไม่ซ้ำแล้ว รูปย้ายไป _ไม่ซ้ำแล้ว ไม่ได้ลบ",
      "#40214 แคปจอ 2 รอบ ฿34.jpg" not in [f["name"] for f in drive.list_images(folder)]
      and drive.where[f"{folder}/#40214 แคปจอ 2 รอบ ฿34.jpg"].endswith(dx.OLD_DIR))

broken = dict(case, id=1, twin_url="https://drive.google.com/file/d/GONE/view")
log.clear()
dx.write(drive, "R", "2026-W46", [], [broken], copies, albums, log=log.append)
check("รูปต้นทางหาย: ข้ามใบนั้น บอกใน log ไม่ล้มรอบ", any("ไม่ได้" in m for m in log), log)

dx.FONTS[:] = [("/nope.ttf", "/nope-b.ttf")]
check("ไม่มีฟอนต์ไทย: ข้ามทั้งหมดโดยไม่ล้ม", dx.write(FakeDrive({}), "R", "W", [], [case], [], albums, log=log.append) == 0)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
