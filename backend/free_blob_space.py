# -*- coding: utf-8 -*-
"""คืนพื้นที่ฐานข้อมูล โดยปล่อยรูปของแถวที่ไม่มีใครต้องดูแล้ว — ไม่ลบแถว ไม่แตะ Drive

ฐานข้อมูลไม่ใช่ที่เก็บรูป Drive ต่างหากที่เป็น รูปถูกเก็บลงแถวไว้ชั่วคราวเพื่อให้คนเปิดดูสลิป
ก่อนตัดสินใจ แล้วถูกล้างทิ้งทันทีที่อนุมัติ (`db.approve_trip` และตัวอนุมัติอัตโนมัติ) แต่แถวที่
**ไม่มีวันถูกอนุมัติ** — ถูกพักเป็นรูปซ้ำ ถูก void หรืออ่านไม่สำเร็จ — ไม่มีใครล้างให้ รูปจึงค้าง
อยู่ตลอดไป และนั่นคือน้ำหนักส่วนใหญ่ของฐานข้อมูล

เรื่องนี้กลายเป็นเรื่องด่วนเพราะแพลน Free ของ Neon ให้พื้นที่ 0.5 GB ต่อโปรเจกต์ และเมื่อเต็ม
คำสั่งที่เพิ่มข้อมูลจะล้มเหลว — แปลว่ารอบ ingest เขียนแถวใหม่ไม่ได้อีกเลย

ปลอดภัยเพราะอะไร: แถวยังจำ `source_url` ของไฟล์ตัวเองบน Drive และ `/api/trips/{id}/image`
ดึงรูปกลับมาจาก Drive ได้เมื่อในฐานข้อมูลไม่มี (ดู `main._picture_from_drive`) ถ้าแถวไหน
ไม่มี source_url ให้ตามรอย เครื่องมือนี้จะไม่แตะมันเด็ดขาด

ไม่แตะ: แถวที่ยังอ่านไม่เสร็จ (`pending`) และแถวที่รออยู่ในคิวตรวจ (`done` ที่ยังไม่อนุมัติ)
เพราะคนกำลังจะเปิดดูรูปนั้นเดี๋ยวนี้

    python free_blob_space.py              # รายงานอย่างเดียว
    python free_blob_space.py --apply      # ล้างจริง
"""
import argparse
import sys

from sqlalchemy import func, or_, select, update

import db

# สถานะที่แปลว่า "แถวนี้จบแล้ว ไม่มีใครต้องเปิดรูปดูเพื่อตัดสินใจอีก"
DONE_WITH = ("duplicate", "voided", "error")
MB = 1024 * 1024


def _size(c, where):
    """(จำนวนแถว, ไบต์รวมของรูป) ของแถวที่ยังถือรูปอยู่ตามเงื่อนไขนี้"""
    r = c.execute(select(func.count(), func.coalesce(func.sum(func.length(db.trips.c.image_blob)), 0))
                  .where(db.trips.c.image_blob.isnot(None), where)).first()
    return int(r[0] or 0), int(r[1] or 0)


def survey():
    """รูปที่ค้างอยู่ในฐานข้อมูล แยกตามสถานะ พร้อมบอกว่าส่วนไหนตามรอยกลับไป Drive ได้"""
    t = db.trips.c
    out = {"by_status": [], "total_rows": 0, "total_bytes": 0,
           "free_rows": 0, "free_bytes": 0, "stuck_rows": 0, "stuck_bytes": 0}
    with db.engine.begin() as c:
        for st in [*DONE_WITH, "merged", "done", "pending"]:
            rows, size = _size(c, t.status == st)
            if rows:
                out["by_status"].append({"status": st, "rows": rows, "mb": size / MB})
            out["total_rows"] += rows
            out["total_bytes"] += size
        out["free_rows"], out["free_bytes"] = _size(c, _clearable())
        out["stuck_rows"], out["stuck_bytes"] = _size(c, _clearable(recoverable=False))
    return out


def _clearable(recoverable=True):
    """เงื่อนไขของแถวที่ล้างรูปได้ — และถ้า recoverable=False คือแถวที่เข้าเกณฑ์ทุกอย่าง
    ยกเว้นตามรอยกลับ Drive ไม่ได้ ซึ่งเป็นกลุ่มที่ต้องปล่อยไว้"""
    t = db.trips.c
    ended = or_(t.status.in_(DONE_WITH), t.committed == 1)
    return ended & (t.source_url.isnot(None) if recoverable else t.source_url.is_(None))


def run(apply=False, log=print):
    t = db.trips.c
    s = survey()
    log(f"รูปที่ยังเก็บอยู่ในฐานข้อมูล {s['total_rows']:,} แถว · {s['total_bytes'] / MB:,.1f} MB")
    for row in s["by_status"]:
        keep = " ← ยังต้องใช้" if row["status"] in ("done", "pending") else ""
        log(f"   {row['status']:<10}{row['rows']:>8,} แถว{row['mb']:>10,.1f} MB{keep}")
    log(f"\nล้างได้ {s['free_rows']:,} แถว · คืนพื้นที่ {s['free_bytes'] / MB:,.1f} MB")
    if s["stuck_rows"]:
        log(f"ปล่อยไว้ {s['stuck_rows']:,} แถว ({s['stuck_bytes'] / MB:,.1f} MB) — "
            f"ไม่มี source_url ให้ตามรอยกลับไป Drive")
    if not apply:
        log("\n(รายงานอย่างเดียว — ยังไม่ได้แตะอะไร · ใส่ --apply เพื่อล้างจริง)")
        return s
    if not s["free_rows"]:
        log("ไม่มีอะไรต้องล้าง")
        return s
    with db.engine.begin() as c:
        # ครึ่งล่างที่ถูกพับเข้ากับแถวหลัก เก็บรูปของตัวเองไว้ให้ part=2 — ล้างพร้อมพ่อแม่ของมัน
        parents = select(db.trips.c.id).where(_clearable())
        kids = c.execute(update(db.trips)
                         .where(t.merged_into.in_(parents), t.image_blob.isnot(None),
                                t.source_url.isnot(None))
                         .values(image_blob=None)).rowcount
        n = c.execute(update(db.trips).where(_clearable(), t.image_blob.isnot(None))
                      .values(image_blob=None)).rowcount
    log(f"\nล้างแล้ว {n:,} แถว (+ ครึ่งล่างที่พับไว้อีก {kids:,} แถว) · "
        f"คืนพื้นที่ราว {s['free_bytes'] / MB:,.1f} MB")
    log("รูปต้นฉบับยังอยู่บน Drive ครบ — หน้าเว็บดึงกลับมาแสดงได้เองเมื่อมีคนเปิดดู")
    log("หมายเหตุ: Postgres คืนพื้นที่ให้ตารางใช้ซ้ำทันที แต่ตัวเลขที่ Neon รายงานจะลดลง"
        " หลัง autovacuum ทำงาน")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="ปล่อยรูปของแถวที่จบแล้ว คืนพื้นที่ฐานข้อมูล (ไม่ลบแถว)")
    ap.add_argument("--apply", action="store_true", help="ทำจริง (ไม่ใส่ = รายงานอย่างเดียว)")
    a = ap.parse_args(argv)
    db.init_db()
    run(apply=a.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
