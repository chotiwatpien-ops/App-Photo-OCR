# Rider Photo OCR

แอปอ่านข้อมูลงานไรเดอร์จาก screenshot แอป Grab Driver แล้วบันทึกลง Excel
ไฟล์ **`Rider Trips.xlsx`** (ชีทเดียว แอปสร้างเองอัตโนมัติถ้ายังไม่มี) — ใช้ Gemini 3.7 Flash อ่านรูป (thinking ต่ำ)

**ฟอร์แมต Excel = Template ของทีม** (`Template Riders Project 2026.xlsx`) ทุกที่ที่ออกไฟล์ (Export / ไฟล์รายสัปดาห์บน Drive / ไฟล์ในเครื่อง):

- **Sheet1** — 17 คอลัมน์ A–Q ตาม template เป๊ะ (หัวน้ำเงิน Calibri 9, วันที่ `d-mmm-yy`, สูตร J `=K+M+N`, Q `=P-J`)
  Pick-up/Drop-off Location เป็น**โซน**: Downtown · North-DMK · East-SVB · West-Nont · South-Rama2
  (แปลงจากเขต/จังหวัดที่ AI อ่านได้ — ตารางโซนแก้ได้ใน `backend/zones.py`)
- **Analysis** — ชีทที่ 2 เก็บข้อมูลเสริมต่อเที่ยว: booking code, สัปดาห์, โซน+เขต+จังหวัด+ที่อยู่เต็ม,
  surge, ประเภทคิว, จุดแวะ, ค่าธรรมเนียม, เงินคืน, ผลตรวจ, ใครอนุมัติ (auto/person), ชื่อไฟล์ต้นฉบับ

เปลี่ยนตำแหน่งไฟล์ได้ด้วย env var `PHOTO_OCR_EXCEL`

## วิธีใช้

1. ดับเบิลคลิก `start_app.bat` (เบราว์เซอร์เปิด http://127.0.0.1:8600 อัตโนมัติ)
2. กรอกชื่อไรเดอร์ + ช่วงวันที่ของสัปดาห์
3. ลากรูปทั้งโฟลเดอร์มาวาง → กด "เริ่มอ่านข้อมูล"
4. รอ AI อ่าน (~2 วินาที/รูป) แล้วตรวจในตาราง Review:
   - คอลัมน์ **ตรวจ**: ✓ เขียว = เลขในรูปตรวจทานกันเองแล้วตรงกัน (ข้ามได้)
     · ✗ แดง = เลขขัดแย้งกัน ต้องดู · ? เหลือง = ข้อมูลไม่พอตรวจ ดูด้วยตา
     · "ซ้ำ" = booking code ซ้ำกับรูปอื่นใน job ให้ลบออก
   - **วันที่ไม่มีในรูป** — กด "📆 กระจายทั้งสัปดาห์เท่าๆ กัน" ระบบแบ่งงานลง จ–อา ตามลำดับรูป (21 งาน = วันละ 3)
     หรือใช้แถบ "ใส่วันที่ทีเดียว" เลือกวันเอง · ตัว ingest จาก Drive กระจายให้อัตโนมัติ (ยกเว้นรูปในโฟลเดอร์วันที่)
     ตารางเรียงตามเวลาบนจอมือถือ รูปวันเดียวกันจะเกาะกลุ่มกัน
   - คลิกรูปเพื่อขยายเทียบกับข้อมูล แก้ตัวเลขได้ทุกช่อง — งานที่รวมจาก 2 รูปจะมีเลข "2" บนรูปย่อ และ modal โชว์ทั้งสองใบ
   - ปุ่ม **🖼 รูปส่งลูกค้า (zip)** = รูปรวม (บน+ล่างต่อกัน) ตั้งชื่อ `ชื่อไรเดอร์1.jpg, 2, 3…` — โหลดก่อนอนุมัติ
     (หลังอนุมัติระบบลบรูปออกจากฐานข้อมูล) · โหมดเครื่องตัวเองจะเซฟให้เองที่ `Rider Images/<สัปดาห์>/<ไรเดอร์>/` ตอนกดบันทึก
5. กด "บันทึกลง Excel" — เขียนต่อท้าย `Rider Trips.xlsx` เรียงตามวันที่+เวลา
   (**ต้องปิดไฟล์ใน Excel ก่อน** ไม่งั้นระบบจะเตือน)
   - กันบันทึกซ้ำ 3 ชั้น: รูปซ้ำใน job / booking code ที่เคยบันทึกแล้ว / ไรเดอร์+วันที่ซ้ำในไฟล์

## หน้าจอในเว็บ (Phase C)

| เมนู | มีอะไร |
|---|---|
| **งาน** | อัปโหลดมือ + รายการ job ล่าสุด + ปุ่ม ⬇ Excel ต่อ job + Export ตามตัวกรอง |
| **คิวตรวจ (N)** | แถวที่ระบบไม่กล้าอนุมัติเองจากทุก job รวมที่เดียว พร้อมเหตุผล (ซ้ำใน job / เคยอนุมัติแล้ว job #X / เลขขัดกัน / ข้อมูลไม่พอ / ไม่มีวันที่) · ดูรูป · อนุมัติ / ลบ ทีละแถว · กดเปิด job เพื่อแก้ตัวเลข |
| **ข้อมูลทั้งหมด** | ทุกแถว กรองไรเดอร์/วันที่/สถานะ · ค้นหา booking code / ชื่อไฟล์ / ที่อยู่ · แบ่งหน้า 50 · Excel ตามตัวกรอง |
| **Dashboard** | KPI (เที่ยว / อนุมัติ / รอคน / รายได้ / กม. / surge / เงินสด) · ตารางรายสัปดาห์ · รายไรเดอร์เรียงตามรายได้ · ประวัติ ingest ล่าสุด |

## โครงสร้าง

```
backend/          FastAPI (Python) — API + Gemini + เขียน Excel
  main.py         endpoints
  extractor.py    Gemini vision + JSON schema + validation/retry
  excel_writer.py build_workbook (export) + append (local mode)
  db.py           SQLAlchemy — SQLite ในเครื่อง / Postgres บน cloud
  pipeline.py     รูป → Gemini → ตรวจ → DB (ใช้ร่วมกันระหว่างเว็บกับ ingest)
  ingest.py       ดูดรูปจาก Drive รายสัปดาห์ + auto-approve + Excel กลับ Drive
  drive_client.py Google Drive API (+ โหมดโฟลเดอร์ local ไว้ทดสอบ)
  stitch.py       ต่อรูปบน+ล่างเป็นใบเดียว + ตั้งชื่อส่งลูกค้า
  zones.py        ตารางเขต → โซน (Downtown / North-DMK / …)
.github/workflows/ingest.yml   ตั้งเวลาบน GitHub Actions
  config.py       env vars + photo_ocr_config.json
render.yaml       Render Blueprint (free web service)
frontend/         React + Vite + Tailwind → build เป็น frontend/dist
%LOCALAPPDATA%\photo-ocr-data\   รูปที่อัปโหลด + ฐานข้อมูล (นอก OneDrive กัน corruption)
start_app.bat     เปิดแอป
```

## API key

ลำดับการหา key: env `GEMINI_API_KEY` → `photo_ocr_config.json` (`{"api_key": "..."}`) → key ของ Voice QA app

## Deploy ขึ้น Render (ฟรี) + Neon (ฟรี)

โค้ดตัวเดียวรันได้ทั้งเครื่องตัวเอง (SQLite + เขียน Excel ต่อท้ายไฟล์) และ cloud
(Postgres + login + Export) โดยสลับด้วย env var:

| env var | ค่า | ความหมาย |
|---|---|---|
| `DATABASE_URL` | `postgresql://...` จาก Neon | ใช้ Postgres แทน SQLite (และถือว่าเป็น cloud mode) |
| `GEMINI_API_KEY` | key | |
| `APP_PASSWORD` | รหัสผ่านทีม | เปิดหน้า login (ไม่ตั้ง = ไม่ต้อง login ใช้เฉพาะในเครื่อง) |
| `SECRET_KEY` | สุ่มยาวๆ | เซ็น cookie (Render สร้างให้เองใน render.yaml) |
| `GEMINI_MODEL` | `gemini-3.7-flash` | |

ขั้นตอน:
1. push โค้ดขึ้น GitHub (repo private) — `frontend/dist` ถูก commit ไว้แล้ว Render ไม่ต้องมี Node
2. Neon → New Project → copy connection string
3. Render → New → **Blueprint** → เลือก repo → Render อ่าน `render.yaml` เอง → ใส่ `DATABASE_URL`, `GEMINI_API_KEY`, `APP_PASSWORD`
4. เปิด URL ที่ได้ → หน้า login → ใช้งานได้เหมือนในเครื่อง แต่ปุ่ม "อนุมัติ" จะไม่เขียนไฟล์ ให้กด "⬇ Excel" ดาวน์โหลดแทน

## Phase B — ดูดรูปจาก Google Drive อัตโนมัติทุกสัปดาห์

`backend/ingest.py` รันบน GitHub Actions (ฟรี) ทุกวันจันทร์ 06:00 หรือกดรันเองที่แท็บ Actions

**โครงโฟลเดอร์ใน Drive** (แชร์โฟลเดอร์ Inbox และ Exports ให้ service account):

```
RiderPhotos/
├── Inbox/
│   └── 2026-W34/                     ← สัปดาห์ ISO → วันที่ = วันจันทร์ของสัปดาห์
│       └── กิตติพงศ์ สินประเสริฐ/     ← ชื่อไรเดอร์ = ชื่อโฟลเดอร์
│           ├── IMG_001.jpg
│           └── 2026-08-04/           ← (ไม่บังคับ) โฟลเดอร์วันที่ → ใช้วันที่นี้แทน
│               └── IMG_002.jpg
└── Exports/                          ← ระบบเขียนให้ ห้ามแก้
    ├── Rider Trips 2026-W34.xlsx     ← Excel ของสัปดาห์ (ฟอร์แมต template)
    └── 2026-W34/
        └── กิตติพงศ์ สินประเสริฐ/     ← รูปส่งลูกค้า: รูปบน+ล่างต่อกันเป็นใบเดียว
            ├── กิตติพงศ์ สินประเสริฐ1.jpg      ชื่อไรเดอร์ + เลขรัน เรียงตามวันที่/ลำดับรูป
            └── กิตติพงศ์ สินประเสริฐ2.jpg
```

**รูป 2 ใบต่องาน (ครึ่งบน/ครึ่งล่าง) ไม่ต้องรวมก่อน** — ระบบจับคู่เอง: AI บอกว่ารูปเป็น
ครึ่งบน (เส้นทาง/booking code) หรือครึ่งล่าง (ยอดผู้โดยสาร/ค่าธรรมเนียม) แล้วจับคู่รูปที่อยู่ติดกันในโฟลเดอร์
ที่มียอด "คุณได้รับ" เท่ากัน รวมเป็น 1 งาน (ยึดเส้นทาง/การจ่ายเงิน/บริการจากครึ่งบน ยอดผู้โดยสาร/ค่าธรรมเนียมจากครึ่งล่าง)
ลำดับบน-ล่างสลับกันได้ ชื่อไฟล์อะไรก็ได้ · ทดสอบ 42 รูป → 21 งาน ครบ 100%

สิ่งที่ ingest ทำ: หาไฟล์ใหม่ (จำด้วย Drive file id — รันซ้ำได้) → Gemini → ตรวจเลข/ซ้ำ →
แถวที่ผ่านทุกอย่าง **อนุมัติอัตโนมัติ** (badge "✓ auto") · แถวติดธงรอคนในเว็บ →
เขียน Excel ของสัปดาห์นั้น (ทุกไรเดอร์ เฉพาะที่อนุมัติ) ลง Exports

**ตั้งค่าครั้งเดียว (Google Cloud):**
1. console.cloud.google.com → New Project → APIs & Services → Enable **Google Drive API**
2. IAM & Admin → Service Accounts → Create → Keys → Add key (JSON) → ดาวน์โหลด
3. ใน Drive: แชร์โฟลเดอร์ `Inbox` (Viewer) และ `Exports` (Editor) ให้อีเมล service account
   (`xxx@yyy.iam.gserviceaccount.com`) · copy folder id จาก URL ของแต่ละโฟลเดอร์
4. GitHub repo → Settings → Secrets and variables → Actions → เพิ่ม secrets:
   `DATABASE_URL`, `GEMINI_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON` (วางเนื้อไฟล์ JSON ทั้งก้อน),
   `DRIVE_INBOX_FOLDER_ID`, `DRIVE_EXPORTS_FOLDER_ID`
5. แท็บ Actions → "Weekly ingest" → Run workflow → ติ๊ก dry_run ครั้งแรกเพื่อดูว่าเจอไฟล์อะไร

ทดสอบในเครื่องโดยไม่ต้องมี Drive: `python backend/ingest.py --source local:<โฟลเดอร์ที่มีโครงเหมือน Inbox>`

หมายเหตุ cloud mode: รูปเก็บใน DB เฉพาะระหว่าง review และถูกลบทันทีที่อนุมัติ
(ข้อมูลตัวเลขยังอยู่ครบ) เพื่อให้ DB อยู่ใน free tier ได้ · free web service หลับเมื่อไม่มีคนใช้ 15 นาที เปิดครั้งแรกรอ ~30–50 วิ

## แก้โค้ด frontend

ต้องมี Node (portable อยู่ที่ `%LOCALAPPDATA%\node-portable`):

```
cd frontend
npm run build
```

`node_modules` เป็น junction ชี้ไป `%LOCALAPPDATA%\photo-ocr-app` เพื่อไม่ให้ OneDrive sync

## โมเดลและค่าใช้จ่าย (audit 5 รอบ × 19 รูป ต่อแบบ — แม่น 100% ทั้งสามแบบ)

| ตั้งค่าใน `photo_ocr_config.json` | ฿/รูป | 5,000 รูป/สัปดาห์ | หมายเหตุ |
|---|---|---|---|
| `{"model": "gemini-3.7-flash"}` (default) | ~0.09 | ~฿450 | เร็วสุด เขตนิ่งสุด · ราคาแนะนำตัวถึง 31 ธ.ค. 2026 |
| `{"model": "gemini-2.5-flash"}` (thinking ปิดอัตโนมัติ) | ~0.03 | ~฿145 | ถูกสุด |
| 2.5 Flash ปล่อย thinking (`"thinking_budget": null`) | ~0.13 | ~฿640 | อย่าใช้ — เผา thinking ~1,000 tokens/รูป |

ทุก trip เก็บ `model`, `tok_in`, `tok_out`, `tok_think` ไว้ใน DB เพื่อดูต้นทุนจริงย้อนหลังได้
