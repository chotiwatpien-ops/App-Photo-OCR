# Rider Photo OCR — Improvement Suggestions

*Code review: 2026-08-20 · reviewed backend (main.py, extractor.py, excel_writer.py, db.py, config.py), frontend (ReviewGrid.jsx, NewJobForm.jsx), PoC scripts*

## Executive Summary

แอปโครงสร้างดี มีของสำคัญครบแล้ว (SQLite staging, review UI, retry logic, duplicate guard, Excel-lock handling)
สิ่งที่เหลือมี 2 กลุ่ม: **ความเสี่ยงข้อมูลพัง** (P1) และ **ลดงาน review ของแอดมิน** (P2) — แนะนำทำ P1-1 กับ P2-1 ก่อน

| # | Priority | เรื่อง | Effort | Impact |
|---|----------|--------|--------|--------|
| P1-1 | 🔴 สูง | ย้าย SQLite + รูปออกจาก OneDrive | ~30 นาที | กัน DB corruption |
| P1-2 | 🔴 สูง | Auto-backup Excel ก่อน save ทุกครั้ง | ~20 นาที | กู้ไฟล์ได้เสมอ |
| P2-1 | 🟠 กลาง | Cross-check เลขคณิตจากฟิลด์ในรูป | ~2 ชม. | ลดงาน review ~70-80% |
| P2-2 | 🟠 กลาง | เพิ่ม booking_code เป็น dedup key | ~1.5 ชม. | กันบันทึกซ้ำแบบแม่นยำ |
| P2-3 | 🟡 ต่ำ | Upscale รูปก่อนส่ง Gemini | ~1 ชม. | เพิ่มความแม่นตัวเลขเล็ก |
| P2-4 | 🟡 ต่ำ | Bulk date assignment ใน Review UI | ~1 ชม. | ลดคลิก 60 → 1-3 ครั้ง |
| P3 | 🟢 เมื่อว่าง | Minor fixes (3 จุด) | ~1 ชม. | Robustness |

---

## P1 — Data Integrity (ทำก่อน)

### P1-1 · ย้าย `data/` ออกจาก OneDrive

**ปัญหา:** `config.py` ตั้ง `DATA_DIR = BASE_DIR / "data"` ซึ่งอยู่ใต้ OneDrive
และ `db.py` ใช้ `PRAGMA journal_mode=WAL` — OneDrive sync ไฟล์ `-wal`/`-shm`
กลางคันได้ = สูตร SQLite corruption แบบคลาสสิก แถมรูปทุกใบถูก sync ขึ้น cloud ฟรีๆ

**แก้:** ใช้แนวเดียวกับที่ทำ `node_modules` ไว้แล้ว — แก้ `config.py`:

```python
import os
DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "photo-ocr-data"
```

ย้ายไฟล์เดิม: copy `data/` ไปที่ใหม่ 1 ครั้ง แล้วลบโฟลเดอร์เดิม
(หรือทำ junction แบบ node_modules ก็ได้ ผลเท่ากัน)

### P1-2 · Auto-backup Excel ก่อน save

**ปัญหา:** `append_trips()` save ทับไฟล์เดิมตรงๆ — ถ้า save พังกลางทาง
(OneDrive sync ชน, ปิดเครื่อง) ไฟล์เสียทั้งไฟล์ การที่มีไฟล์
`backup-before-cleanup.xlsx` อยู่แปลว่าเคยต้องกู้มือมาแล้ว

**แก้:** ใน `excel_writer.append_trips()` ก่อน `wb.save()`:

```python
import shutil, datetime
bak = EXCEL_PATH.with_suffix(f".{datetime.datetime.now():%Y%m%d-%H%M%S}.bak")
shutil.copy2(EXCEL_PATH, bak)
# เก็บแค่ 10 ไฟล์ล่าสุด ลบที่เหลือ
for old in sorted(EXCEL_PATH.parent.glob("*.bak"))[:-10]:
    old.unlink()
```

---

## P2 — ลดงาน Review + ความแม่นยำ

### P2-1 · Cross-check เลขคณิตจากฟิลด์ที่มีในรูปอยู่แล้ว ⭐ คุ้มสุด

**ปัญหา:** ตอนนี้ prompt สั่งให้ **ignore** `ค่าโดยสารของผู้โดยสาร` และ
`ค่าบริการที่แกร็บได้รับ` ทั้งที่มันคือเครื่องมือตรวจฟรี:

```
passenger_total − grab_commission ≈ net_earnings
(ตัวอย่างรูป 17: 136 − 26 = 110 ✓ | รูป 19: 85 − 3 = 82 ✓)
```

แถม net_earnings โผล่ 2 จุดในรูป (panel ซ้าย "คุณได้รับ" + panel ขวา "Total")
แต่การเช็คว่าตรงกันฝากไว้กับ prompt อย่างเดียว ("say so in confidence_note") ซึ่งเชื่อไม่ได้

**แก้:**
1. เพิ่มใน SCHEMA (`extractor.py`): `passenger_total`, `grab_commission`,
   `net_earnings_left_panel` — ทั้งหมด nullable (บางรูป accordion หุบอยู่ ไม่มีข้อมูล)
2. เช็คฝั่ง Python หลัง extract:

```python
def arithmetic_check(d) -> str:   # "pass" | "fail" | "no_data"
    pt, gc, net = d.get("passenger_total"), d.get("grab_commission"), d.get("net_earnings")
    left = d.get("net_earnings_left_panel")
    if left is not None and net is not None and left != net:
        return "fail"                       # สองจอไม่ตรงกัน
    if pt is not None and gc is not None and net is not None:
        return "pass" if abs((pt - gc) - net) <= 1 else "fail"
    return "no_data"
```

3. เก็บผลลง `trips.check_status` แล้วให้ ReviewGrid แสดง:
   ✓ เขียว = ผ่าน (แอดมินข้ามได้เลย) · ⚠️ เหลือง = no_data · 🔴 แดง = fail (ต้องดู)

**ผล:** แอดมินไล่ดูเฉพาะแถวเหลือง/แดง — จากประสบการณ์ pattern แบบนี้
แถวเขียวจะเป็น 70-80% ของทั้งหมด

### P2-2 · booking_code เป็น dedup key จริง

**ปัญหา:** PoC เคย extract `booking_code` (เช่น `A-9LO9AMUGXEO`) แต่ production
schema ตัดทิ้ง — ทั้งที่มันคือ unique ID ต่อเที่ยวที่แท้จริง duplicate guard ปัจจุบัน
(`count_existing_rows` นับ driver+date) หยาบ: รูปซ้ำ 2 ไฟล์ใน job เดียว หรือ
อัปโหลดรูปเดิมข้าม job แล้วกด force = ลง Excel ซ้ำ

**แก้:**
1. เอา `booking_code` กลับเข้า SCHEMA + คอลัมน์ `trips.booking_code`
2. Dedup 2 ชั้น:
   - **ใน job เดียวกัน:** หลัง extract เสร็จ ถ้าซ้ำ → mark แถวหลังเป็น duplicate อัตโนมัติ
   - **ข้าม job:** ตอน commit เช็คกับ `trips WHERE committed=1` ใน SQLite
     (ไม่ต้องพึ่ง Excel) → เตือนระบุชัดว่า "รูป X ซ้ำกับที่บันทึกไปแล้วใน job #Y"
3. (ทางเลือก) เขียนลง Excel คอลัมน์ P ไว้ audit trail

### P2-3 · Upscale รูปก่อนส่ง + retry ให้ฉลาดขึ้น

**ปัญหา:** รูปจริงกว้างแค่ ~360-520px (ผ่าน LINE compression) ตัวเลขเล็กใน
breakdown เสี่ยงอ่านพลาด และ retry loop ปัจจุบันยิงซ้ำด้วย input เดิม +
`temperature=0` → ได้คำตอบเดิมเป๊ะ = เปลือง 2 calls ฟรี

**แก้:** ใน `extract_image()` ก่อนสร้าง `Part.from_bytes`:

```python
from PIL import Image
import io

def preprocess(image_bytes: bytes, scale: int = 2) -> bytes:
    im = Image.open(io.BytesIO(image_bytes))
    if im.width < 800:   # เฉพาะรูปเล็ก
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")   # PNG กัน JPEG artifact ซ้ำสอง
    return buf.getvalue()
```

รอบแรกส่ง 2x · ถ้าเจอ suspect fields รอบ retry ส่ง 3x (เปลี่ยน input จริง ไม่ใช่ยิงซ้ำเฉยๆ)

**Bonus แก้ที่ต้นทาง:** ถ้าให้ไรเดอร์ส่งรูปผ่าน LINE แบบ **"ไฟล์"** แทน "รูปภาพ"
จะได้ 1080px เต็ม — ประโยคเดียว คุ้มกว่าโค้ดทั้งหมดในข้อนี้

### P2-4 · Bulk date assignment

**ปัญหา:** วันที่ไม่มีในรูป ต้องเลือก dropdown ทีละแถว — job สัปดาห์ละ 60 รูป = 60 คลิก

**แก้ใน ReviewGrid:** เพิ่มแถบบน table: dropdown วันที่ + ปุ่ม
"ใส่วันที่นี้ให้ทุกแถวที่ยังว่าง" (หรือ checkbox เลือกหลายแถว) และ sort ตาราง
ตาม `screen_time` ให้รูปวันเดียวกันเกาะกลุ่มกัน เลือกเป็นช่วงได้ง่าย

---

## P3 — Minor (ทำเมื่อว่าง)

1. **`main.py` commit():** duplicate guard ห่อ `except: existing = 0` —
   ถ้าอ่าน Excel พลาด guard หายเงียบ → เพิ่ม `import logging; logging.warning(...)`
2. **`ReviewGrid.jsx` numCell:** ใช้ `defaultValue` + `onBlur` — ถ้า patch fail
   หรือ job refresh ค่าบนจอค้าง → เปลี่ยนเป็น controlled component หรือใส่ `key={t[field]}`
3. **`extractor.py`:** `screen_time` มีแค่ HH:MM ไม่มีวันที่ — ใช้เรียงลำดับได้
   แต่ห้ามใช้เดาวันที่ (คนขับ capture ตอนกลางคืนหลังจบงานหลายเที่ยว)

---

## ลำดับที่แนะนำ (ปรับ 2026-08-20 หลังตัดสินใจ deploy ขึ้น Render)

เป้าหมายเปลี่ยนเป็นใช้งานจากภายนอกผ่าน Render → ลำดับใหม่:

```
Phase 1 — ทำบนเครื่องก่อน (ไม่ขึ้นกับ platform):        ✅ ทำแล้ว
  P2-1 arithmetic check → P2-2 booking_code dedup
  → P2-4 bulk date + sort by time → P3 minor fixes
  → P1-1 แบบเร็ว (ย้าย DATA_DIR ไป LocalAppData)

Phase 2 — Cloud migration (ยังไม่เริ่ม):
  1. Login ง่ายๆ (blocker อันดับหนึ่ง — บน Render ใครมี URL ก็เข้าได้)
  2. SQLite → Postgres  ⚠️ Render free Postgres หมดอายุ 30 วันแล้วลบข้อมูล
     → ใช้ Neon หรือ Supabase (free ถาวร) แล้วให้ Render ต่อออกไป
  3. รูปเก็บเป็น BLOB ใน Postgres (รูปละ ~30KB ไม่ต้องจ่าย storage เพิ่ม)
  4. Excel เปลี่ยนจากเขียนไฟล์ shared → ปุ่ม Export .xlsx
     (เซิร์ฟเวอร์ Render มองไม่เห็น OneDrive)
  5. Deploy + ตั้ง GEMINI_API_KEY เป็น env var

นอกโค้ด:  บอกไรเดอร์ส่งรูปแบบ "ไฟล์" ใน LINE — ทำได้เลยวันนี้

ตัดทิ้ง:
  P1-2 (auto-backup Excel) — ตกไปเองเมื่อเปลี่ยนเป็น Export model
  P2-3 (upscale รูป) — ทดสอบแล้ว 19/19 ถูกที่ความละเอียดปัจจุบัน
     เพิ่ม token cost เพื่อแก้ปัญหาที่ยังไม่เกิด รอเจอ error จริงค่อยทำ
```
