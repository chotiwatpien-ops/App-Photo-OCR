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


# คอลัมน์ข้อความของ trips ที่มีโอกาสเป็นตัวกินที่ตัวจริง
_TEXTY = ["pickup_text", "dropoff_text", "note", "file_name", "source_url", "customer_image",
          "booking_code", "error", "image_hash", "batch_name", "image_mime", "model"]


def disk(log=print):
    """อะไรกินพื้นที่จริงบ้าง — ตาราง ดัชนี ซากจากการ update และคอลัมน์ที่อ้วนที่สุด

    รูปที่ปล่อยได้เป็นแค่ส่วนเดียวของน้ำหนัก และการเดาว่าส่วนที่เหลือคืออะไรเคยพลาดมาแล้วหนึ่งครั้ง
    (ประเมินรูปไว้ 330 MB ของจริง 54.5 MB) — ถามฐานข้อมูลตรงๆ ดีกว่า"""
    if db.engine.dialect.name != "postgresql":
        log("(ข้ามการวัดพื้นที่ — ใช้ได้กับ Postgres เท่านั้น)")
        return
    from sqlalchemy import text
    with db.engine.begin() as c:
        total = c.execute(text("SELECT pg_database_size(current_database())")).scalar()
        log("")
        log(f"ขนาดฐานข้อมูลทั้งก้อน: {total / MB:,.1f} MB")
        rows = c.execute(text("""
            SELECT c.relname,
                   pg_total_relation_size(c.oid) AS total,
                   pg_relation_size(c.oid)       AS heap,
                   pg_indexes_size(c.oid)        AS idx,
                   COALESCE(s.n_live_tup, 0), COALESCE(s.n_dead_tup, 0),
                   COALESCE(to_char(GREATEST(s.last_autovacuum, s.last_vacuum),
                                    'MM-DD HH24:MI'), 'ยังไม่เคย')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC""")).all()
        log("")
        log(f"{'ตาราง':<22}{'รวม':>10}{'ข้อมูล':>10}{'รูป/ยาว':>10}{'ดัชนี':>10}"
            f"{'แถวเป็น':>10}{'ซาก':>9}  เก็บกวาดล่าสุด")
        for name, tot, heap, idx, live, dead, vac in rows:
            toast = max(0, tot - heap - idx)
            log(f"{name[:21]:<22}{tot / MB:>9,.1f}{heap / MB:>10,.1f}{toast / MB:>10,.1f}"
                f"{idx / MB:>10,.1f}{live:>10,}{dead:>9,}  {vac}")
        cols = ", ".join(f"COALESCE(SUM(pg_column_size({n})), 0)" for n in _TEXTY)
        sizes = c.execute(text(f"SELECT {cols} FROM trips")).first()
        log("")
        log("คอลัมน์ข้อความของ trips ที่กินที่มากสุด:")
        for name, size in sorted(zip(_TEXTY, sizes), key=lambda x: -x[1])[:6]:
            log(f"   {name:<18}{size / MB:>8,.1f} MB")


# ตารางที่ยอมให้เขียนใหม่ได้ — กันชื่อตารางแปลกปลอมหลุดเข้าไปใน SQL
VACUUMABLE = ("trips", "pool_ocr_cache", "ingested_files")


def _table_size(c, table):
    from sqlalchemy import text
    return c.execute(text("SELECT pg_total_relation_size(:t)"), {"t": table}).scalar() or 0


def vacuum(table="trips", log=print, force=False):
    """เขียนตารางใหม่ทั้งก้อนโดยไม่เอาซากมาด้วย แล้วคืนพื้นที่ให้ระบบจริงๆ

    ปล่อยรูปเฉยๆ ไม่ทำให้ฐานข้อมูลเล็กลง: Postgres ไม่แก้แถวเดิมในที่เดิม ทุก UPDATE ทิ้งเวอร์ชันเก่า
    ไว้ให้ autovacuum ซึ่งทำเครื่องหมายว่า "ใช้ซ้ำได้" แต่ไม่คืนไฟล์ให้ระบบ ตาราง trips จึงกิน
    357 MB ทั้งที่ข้อมูลจริงมี 28.7 MB กับรูปเป็นๆ อีก 54.5 MB — ที่เหลือคือซากของรูปที่ถูกล้าง
    ตอนอนุมัติ 25,670 ครั้ง

    VACUUM FULL ล็อกทั้งตารางระหว่างทำ อ่านก็ไม่ได้ เขียนก็ไม่ได้ จึงห้ามทับรอบ ingest ที่กำลังรัน"""
    from sqlalchemy import text
    if db.engine.dialect.name != "postgresql":
        log("(ข้ามการเขียนตารางใหม่ — ใช้ได้กับ Postgres เท่านั้น)")
        return False
    if table not in VACUUMABLE:
        log(f"✗ ไม่ยอมแตะตาราง {table!r} — รู้จักแค่ {', '.join(VACUUMABLE)}")
        return False
    runs = db.list_ingest_runs(1)
    if runs and not runs[0].get("finished_at") and not force:
        log(f"✗ มีรอบ ingest กำลังรันอยู่ (เริ่ม {runs[0].get('started_at')}) — "
            f"ไม่เขียนตารางใหม่ตอนนี้ เพราะจะล็อกจนรอบนั้นค้าง")
        return False
    with db.engine.connect() as c:
        before = _table_size(c, table)
    log("")
    log(f"เขียนตาราง {table} ใหม่ ({before / MB:,.1f} MB) — ตารางถูกล็อกระหว่างนี้…")
    # VACUUM ทำงานในทรานแซกชันไม่ได้ ต้อง autocommit
    with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f"VACUUM (FULL, ANALYZE) {table}"))
        after = _table_size(c, table)
        total = c.execute(text("SELECT pg_database_size(current_database())")).scalar()
    log(f"เสร็จแล้ว: {before / MB:,.1f} MB → {after / MB:,.1f} MB "
        f"(คืนมา {(before - after) / MB:,.1f} MB)")
    log(f"ฐานข้อมูลทั้งก้อนตอนนี้ {total / MB:,.1f} MB")
    return True


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
    ap.add_argument("--no-disk", action="store_true", help="ข้ามการวัดว่าอะไรกินพื้นที่")
    ap.add_argument("--vacuum", action="store_true",
                    help="เขียนตาราง trips ใหม่เพื่อคืนพื้นที่ซาก (ล็อกตารางชั่วคราว)")
    ap.add_argument("--vacuum-table", default="trips", help=f"ตารางที่จะเขียนใหม่ ({', '.join(VACUUMABLE)})")
    ap.add_argument("--force", action="store_true", help="เขียนตารางใหม่แม้มีรอบ ingest กำลังรัน")
    a = ap.parse_args(argv)
    db.init_db()
    if not a.no_disk:
        disk()
    run(apply=a.apply)
    if a.vacuum:
        vacuum(table=a.vacuum_table, force=a.force)
        disk()
    return 0


if __name__ == "__main__":
    sys.exit(main())
