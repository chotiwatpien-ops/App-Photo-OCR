# -*- coding: utf-8 -*-
"""Pictures of each week's repeats, ready to post in LINE (dup_examples.py, Fiat 2026-11-11):
each read repeat beside the trip it repeats, every exact copy on pages of 20 named under each
picture (never the unpaired half pictures: those may be the pairing's own miss), a summary card, a pair not made twice, and a picture that
is no longer wanted moved aside."""
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


ALBUM = "2W Karnjana 1748 งาน"
case = {"id": 40214, "ไรเดอร์ผู้ส่ง": ALBUM, "ลิงก์รูป": "https://drive.google.com/file/d/MINE/view",
        "twin_url": "https://drive.google.com/file/d/TWIN/view", "ประเภทการซ้ำ": dr.KIND_SAME_WEEK,
        "ยอด": 34.0, "รหัสการจอง": "A-AWK4QFXGXWOEAV", "วันที่งาน": "2026-11-15"}
copies = [{"ไรเดอร์ผู้ส่ง": ALBUM, "ไฟล์ที่ซ้ำ": f"1126{i:02d}_1.jpg", "ซ้ำกับไฟล์": f"{ALBUM}/1126{i:02d}_0.jpg",
           "ลิงก์รูป": f"https://drive.google.com/file/d/COPY{i}/view"} for i in range(25)]
albums = [[1, ALBUM, None, 1642, 1637, 25, 1, 26, 0.02, "ในอัลบั้มเดียวกัน", 3, None, "ซ้ำ"],
          [2, "2W Karnjana ทดสอบ", None, 20, 20, 0, 0, 0, 0.0, "", None, None, "ไม่ซ้ำ"]]
files = {"MINE": jpeg("red"), "TWIN": jpeg("blue")}
files.update({f"COPY{i}": jpeg("green", (200, 400)) for i in range(25)})

ex = dx.examples([], [case], copies)
pair = [e for e in ex if not e.redo]
pages = [e for e in ex if e.redo]
check("งานแคปซ้ำ: รูปคู่กัน ใบที่นับแล้วอยู่ซ้าย ใบนี้อยู่ขวา",
      pair[0].pictures[0][0] == "TWIN" and pair[0].pictures[1][0] == "MINE", pair)
check("❗ ไฟล์ซ้ำครบทุกไฟล์ หน้าละ 20: 25 ไฟล์ = 2 หน้า",
      [e.name for e in pages if e.name.startswith("ไฟล์ซ้ำ")] == ["ไฟล์ซ้ำ หน้า 1 จาก 2.jpg", "ไฟล์ซ้ำ หน้า 2 จาก 2.jpg"]
      and sum(len(e.pictures) for e in pages if e.name.startswith("ไฟล์ซ้ำ")) == 25)
check("แต่ละรูปบอกว่าซ้ำกับไฟล์ไหน", pages[0].pictures[0][1] == "112600_1.jpg = 112600_0.jpg", pages[0].pictures[0])
check("ไม่มีหน้ารูปที่หาคู่ไม่ได้ (อาจเป็นระบบจับคู่พลาดเอง)", all("หาคู่" not in e.name for e in ex))

drive = FakeDrive(files)
log = []
made = dx.write(drive, "R", "2026-W46", [], [case], copies, albums, log=log.append)
folder = f"R/2026-W46 ตัวอย่าง/{ALBUM}"
names = sorted(f["name"] for f in drive.list_images(folder))
check("❗ วางในโฟลเดอร์ของอัลบั้ม: สรุป · คู่แคปซ้ำ · หน้าไฟล์ซ้ำ 2 หน้า",
      names == ["#40214 แคปจอ 2 รอบ ฿34.jpg", "00 สรุป.jpg",
                "ไฟล์ซ้ำ หน้า 1 จาก 2.jpg", "ไฟล์ซ้ำ หน้า 2 จาก 2.jpg"] and made == 3, names)
page = Image.open(io.BytesIO(drive.files[f"{folder}/ไฟล์ซ้ำ หน้า 1 จาก 2.jpg"]))
check("หน้าเป็น JPEG 5 คอลัมน์ 4 แถว", page.format == "JPEG" and page.width > 5 * 230 and page.height > 4 * 460, page.size)
check("อัลบั้มที่ไม่มีอะไรซ้ำ ไม่มีโฟลเดอร์", not drive.list_images("R/2026-W46 ตัวอย่าง/2W Karnjana ทดสอบ"))

drive.downloads.clear()
dx.write(drive, "R", "2026-W46", [], [case], copies, albums, log=log.append)
check("❗ รอบถัดไปไม่โหลดรูปคู่มาทำซ้ำ (ทำแค่หน้ารวมใหม่)", "MINE" not in drive.downloads and "TWIN" not in drive.downloads)

dx.write(drive, "R", "2026-W46", [], [], copies[:20], albums, log=log.append)
here = [f["name"] for f in drive.list_images(folder)]
check("❗ ของที่ไม่ต้องการแล้ว (แถวไม่ซ้ำแล้ว · หน้าที่หายไป) ย้ายไป _เก่า ไม่ได้ลบ",
      "#40214 แคปจอ 2 รอบ ฿34.jpg" not in here and "ไฟล์ซ้ำ หน้า 1 จาก 1.jpg" in here
      and drive.where[f"{folder}/ไฟล์ซ้ำ หน้า 2 จาก 2.jpg"].endswith(dx.OLD_DIR), here)

gone = dict(case, id=1, twin_url="https://drive.google.com/file/d/GONE/view")
broken = FakeDrive({"MINE": jpeg("red")})
log.clear()
dx.write(broken, "R", "2026-W46", [], [gone], [], albums, log=log.append)
check("รูปต้นทางหาย: ข้ามคู่นั้น บอกใน log ไม่ล้มรอบ", any("ไม่ได้" in m for m in log), log)

dx.FONTS[:] = [("/nope.ttf", "/nope-b.ttf")]
check("ไม่มีฟอนต์ไทย: ข้ามทั้งหมดโดยไม่ล้ม", dx.write(FakeDrive({}), "R", "W", [], [case], [], albums, log=log.append) == 0)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
