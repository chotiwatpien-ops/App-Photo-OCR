# -*- coding: utf-8 -*-
"""A second look at the same week opens only the pictures it has to, and finds what a full look finds.

recut_date_bar swept W47 five times (57 + 32 + 86 + 113 + 84 minutes); every sweep downloaded and
read all 4,411 pictures again, the last one to find nothing. A picture found free of a date bar is
now remembered by its bytes and by the version of the checker, and the next sweep asks Drive for
its checksum only.

Which picture is opened and which is skipped does not depend on what the OCR reads, so
recut_date_bar.recut is replaced here by a stand-in that counts its calls and answers from a table
(bytes that 'carry a date bar' -> the bytes after the cut). No OCR runs in this file. from_original
is tested on real pictures, with PIL only."""
import contextlib
import hashlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WORK = tempfile.mkdtemp(prefix="pocr-recut-")
os.environ["PHOTO_OCR_DATA"] = WORK
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from PIL import Image                                           # noqa: E402
from sqlalchemy import insert                                   # noqa: E402

import config                                                   # noqa: E402
import db                                                       # noqa: E402
import pairing                                                  # noqa: E402
import recut_date_bar as rdb                                    # noqa: E402
from drive_client import LocalDrive                             # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


def pic(shade, h=60, top=None):
    im = Image.new("RGB", (40, h), (shade, shade, shade))
    if top:
        im.paste((0, 0, 0), (0, 0, 40, top))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def md5(data):
    return hashlib.md5(data).hexdigest()


class Watched(LocalDrive):
    """LocalDrive that takes a Drive-style id (a name under root) and notes what was fetched and written."""

    def __init__(self, root):
        super().__init__(root)
        self.fetched, self.written = [], []

    def _at(self, file_id):
        return str(self.root / file_id)

    def md5(self, file_id):
        return super().md5(self._at(file_id))

    def download(self, file_id):
        self.fetched.append(Path(file_id).name)
        return super().download(self._at(file_id))

    def replace_content(self, file_id, data, mime):
        self.written.append(Path(file_id).name)
        super().replace_content(self._at(file_id), data, mime)

    def create_file(self, parent_id, name, data, mime):
        self.written.append(name)
        return super().create_file(parent_id, name, data, mime)

    def upload_file(self, parent_id, name, data, mime):
        self.written.append(name)
        return super().upload_file(parent_id, name, data, mime)


W = ("2026-11-16", "2026-11-22")
ROOT = Path(WORK) / "drive"
ROOT.mkdir()
EXPORTS = ROOT / "Exports"
config.DRIVE_EXPORTS_FOLDER_ID = str(EXPORTS)
drive = Watched(ROOT)
job = db.create_job("ก Win", "Trips", *W, category="2 W Saver")

BAR = {}            # md5 of bytes that 'carry a date bar' -> the bytes after the cut
OCR_DOWN = set()    # md5 of bytes on which the OCR itself fails
looked = []


def fake_recut(data):
    h = md5(data)
    looked.append(h)
    if h in OCR_DOWN:
        try:                                  # date_bar_cut swallows a failed read the same way
            pairing._read_text(None)
        except Exception:  # noqa: BLE001
            return None
    return BAR.get(h)


rdb.recut = fake_recut


def add(n, data):
    (ROOT / f"p{n}.jpg").write_bytes(data)
    with db.engine.begin() as c:
        return c.execute(insert(db.trips).values(
            job_id=job, file_name=f"p{n}.jpg", status="done", committed=1, trip_date="2026-11-17",
            source_url=f"https://drive.google.com/file/d/p{n}.jpg/view",
            customer_image=f"c{n}.jpg")).inserted_primary_key[0]


def tree():
    return sorted((str(p.relative_to(ROOT)), p.read_bytes() if p.is_file() else None) for p in ROOT.rglob("*"))


def sweep(*extra):
    """(bars reported, the per-rider lines under it, pictures fetched, everything printed)"""
    drive.fetched.clear()
    drive.written.clear()
    looked.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = rdb.main(["--week", W[0], *extra], drive=drive)
    text = out.getvalue()
    head, _, tail = text.partition("มีแถบวันที่ ")
    bars = int(re.match(r"[\d,]+", tail).group().replace(",", ""))
    riders = [ln for ln in tail.splitlines()[1:] if ln.startswith("  ") and "—" in ln]
    assert code == 0, text
    return bars, riders, sorted(drive.fetched), text


ORIG = {n: pic(40 + 20 * n) for n in range(1, 6)}
ids = {n: add(n, ORIG[n]) for n in ORIG}
CUT3 = pic(100, h=50)
BAR[md5(ORIG[3])] = CUT3
ALL = [f"p{n}.jpg" for n in range(1, 6)]

before = tree()
bars1, riders1, fetched, _ = sweep()
check("รอบแรก: เปิดดูทุกรูป", fetched == ALL and len(looked) == 5, fetched)
check("รอบแรก: พบแถบวันที่ 1 รูป", bars1 == 1 and "c3.jpg" in riders1[0], (bars1, riders1))
check("❗ รายงานอย่างเดียวไม่เขียนอะไรลง Drive", drive.written == [] and tree() == before, drive.written)

bars2, riders2, fetched, text = sweep()
check("❗ รอบสอง: ไม่โหลดรูปที่ตรวจแล้วว่าไม่มีแถบ — โหลดแค่รูปที่มีแถบ", fetched == ["p3.jpg"], fetched)
check("❗ รูปที่มีแถบถูกเปิดดูใหม่ทุกรอบ ไม่ข้ามจากความจำ", looked == [md5(ORIG[3])], looked)
check("รอบสองรายงานเหมือนรอบแรก", (bars2, riders2) == (bars1, riders1), (bars2, riders2))
check("บรรทัดสรุปบอกว่าข้ามกี่รูป", "ข้าม 4 รูป" in text, text)
check("รอบสองก็ไม่เขียนอะไรลง Drive", drive.written == [] and tree() == before, drive.written)

(ROOT / "p2.jpg").write_bytes(pic(210))
_, _, fetched, _ = sweep()
check("❗ รูปที่ไบต์เปลี่ยนไปถูกเปิดดูใหม่", fetched == ["p2.jpg", "p3.jpg"], fetched)
barred = pic(220)
BAR[md5(barred)] = pic(221, h=50)
(ROOT / "p2.jpg").write_bytes(barred)
bars, _, fetched, _ = sweep()
check("❗ รูปเดิมที่เคยสะอาด ถ้าไบต์ใหม่มีแถบ ก็เจอ", bars == 2 and "p2.jpg" in fetched, (bars, fetched))
(ROOT / "p2.jpg").write_bytes(ORIG[2])
bars, _, fetched, _ = sweep()
check("ไบต์กลับเป็นชุดที่เคยตรวจแล้ว: ข้ามได้อีก", bars == 1 and fetched == ["p3.jpg"], (bars, fetched))

rdb.CHECKER += 1
_, _, fetched, _ = sweep()
check("❗ ตัวตรวจรุ่นใหม่ (CHECKER) ไม่ใช้ความจำของรุ่นเก่า", fetched == ALL, fetched)
rdb.CHECKER -= 1
reader, pairing.READER = pairing.READER, "r99"
bars, _, fetched, _ = sweep()
check("❗ ตัวอ่านรุ่นใหม่ (READER) ก็ไม่ใช้ความจำของรุ่นเก่า", fetched == ALL and bars == 1, (bars, fetched))
pairing.READER = "r" + "9" * 7
try:
    rdb.clean_key("0" * 32)
    check("คีย์ที่ยาวเกิน 40 ตัวต้องหยุด ไม่ตัดให้สั้น", False)
except AssertionError:
    check("คีย์ที่ยาวเกิน 40 ตัวต้องหยุด ไม่ตัดให้สั้น", True)
pairing.READER = reader
check("คีย์ของรุ่นปัจจุบันลงคอลัมน์ 40 ตัวได้", len(rdb.clean_key("0" * 32)) <= 40, rdb.clean_key("0" * 32))
_, _, fetched, _ = sweep()
check("กลับมารุ่นเดิม: ความจำเดิมยังใช้ได้", fetched == ["p3.jpg"], fetched)

rdb.PROGRESS_EVERY = 2
rdb.CHECKER += 5
_, _, _, text = sweep()
check("ระหว่างตรวจมีบรรทัดบอกความคืบหน้า", len(re.findall(r"เปิดดูแล้ว [\d,]+/5", text)) == 2, text)
rdb.CHECKER -= 5

_, _, fetched, _ = sweep("--apply")
kept = EXPORTS / rdb.BACKUP_DIR / "2026-W47" / f"{ids[3]}_p3.jpg"
check("ทำจริง: เปิดแค่รูปที่มีแถบ แล้วตัด", fetched == ["p3.jpg"] and (ROOT / "p3.jpg").read_bytes() == CUT3, fetched)
check("ทำจริง: ของเดิมเก็บไว้ก่อน และรูปส่งลูกค้าถูกทำใหม่",
      kept.read_bytes() == ORIG[3] and (EXPORTS / "2026-W47" / "2 W Saver" / "c3.jpg").is_file(), drive.written)
bars, _, fetched, _ = sweep()
check("❗ รูปที่เพิ่งตัดถูกเปิดดูจริงอีกรอบก่อนจะจำ", bars == 0 and fetched == ["p3.jpg"], (bars, fetched))
bars, _, fetched, text = sweep()
check("รอบถัดไป: ไม่ต้องโหลดสักรูป", bars == 0 and fetched == [] and "ข้าม 5 รูป" in text, (bars, fetched))

out = io.StringIO()
with contextlib.redirect_stdout(out):
    code = rdb.restore(W[0], ["c3.jpg:0"], True, drive=drive)
check("--restore ทำงานบน Drive ที่ส่งเข้ามา: คืนต้นฉบับ", code == 0 and (ROOT / "p3.jpg").read_bytes() == ORIG[3],
      out.getvalue())
bars, _, fetched, _ = sweep()
check("หลังคืนต้นฉบับ รอบถัดไปเจอแถบอีก", bars == 1 and fetched == ["p3.jpg"], (bars, fetched))

real_read = pairing._read_text


def ocr_down(_img):
    raise RuntimeError("OCR ล่ม")


flaky = pic(30)
add(6, flaky)
OCR_DOWN.add(md5(flaky))
pairing._read_text = ocr_down
_, _, fetched, text = sweep()
check("รูปที่ OCR ล่มตอนอ่าน: ถูกเปิดดู และรายงานว่า OCR อ่านไม่ได้", "p6.jpg" in fetched and "OCR" in text, text)
_, _, fetched, _ = sweep()
check("❗ รูปที่ OCR ล่มตอนอ่าน ไม่ถูกจำว่าไม่มีแถบ", fetched == ["p3.jpg", "p6.jpg"], fetched)
OCR_DOWN.clear()
sweep()
_, _, fetched, _ = sweep()
check("OCR กลับมาอ่านได้: ตรวจจริงหนึ่งรอบแล้วจึงจำ", fetched == ["p3.jpg"], fetched)
check("ตัวอ่านของ pairing กลับเป็นตัวเดิมหลังตรวจ", pairing._read_text is ocr_down)
pairing._read_text = real_read

with db.engine.begin() as c:
    c.execute(insert(db.trips).values(job_id=job, file_name="gone.jpg", status="done", committed=1,
                                      source_url="https://drive.google.com/file/d/gone.jpg/view"))
bars, _, fetched, text = sweep()
check("รูปที่หายไปจาก Drive: รายงานว่าอ่านไม่ได้ รูปอื่นยังข้ามตามปกติ",
      bars == 1 and "อ่านไม่ได้ 1 รูป" in text and "p1.jpg" not in fetched, text)

tall, short = pic(250, h=90, top=30), pic(250, h=60)
check("from_original: ใช้สำเนาที่สูงที่สุด และ :0 คืนตามเดิมทุกไบต์", rdb.from_original([short, tall], 0) == tall)
made = Image.open(io.BytesIO(rdb.from_original([short, tall], 30))).convert("L")
check("from_original: :N ตัดบนออก N แถวพอดี",
      made.size == (40, 60) and made.getextrema()[0] > 200, (made.size, made.getextrema()))
check("from_original: ไม่มีสำเนาเก็บไว้ = ไม่มีอะไรให้ทำ", rdb.from_original([], 0) is None)

print("\nผ่านทั้งหมด ✅" if ok else "\n✗ มีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
