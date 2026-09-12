# -*- coding: utf-8 -*-
"""ค่าอ่านสลิปจริงต่อสัปดาห์ — คิดจาก token ที่เก็บไว้ในทุกแถว ไม่ใช่จากราคาป้าย

ทุกแถวเก็บ model, tok_in, tok_out, tok_think ไว้ตั้งแต่ต้นโปรเจกต์ (README: "เพื่อดูต้นทุนจริง
ย้อนหลังได้") อันนี้คือตัวที่อ่านมันออกมา: รวม token ต่อสัปดาห์ คูณราคาของโมเดลที่อ่านแถวนั้นจริง
แล้วหารครึ่งให้รอบที่ส่งผ่าน Batch API

Batch ลดครึ่งราคา แต่ฐานข้อมูลไม่ได้เก็บว่าแถวไหนอ่านผ่าน batch — ช่อง batch_name ถูกล้างทิ้ง
ตอนเก็บผล สิ่งที่เหลือคือวันที่: โค้ดอ่านผ่าน batch เข้ามา 2026-08-27 (b29eeea) งานที่เปิดก่อน
วันนั้นจ่ายราคาเต็ม หลังจากนั้นจ่ายครึ่งเดียว เปลี่ยนวันได้ด้วย --batch-from

ไม่เขียนอะไรลงฐานข้อมูลทั้งสิ้น

    python cost_report.py                 # ต่อสัปดาห์
    python cost_report.py --by-model      # แยกตามโมเดลด้วย
"""
import argparse
import collections
import sys
from datetime import date

from sqlalchemy import select

import config
import db

BATCH_FROM = "2026-08-27"      # b29eeea 'read images through the Batch API, and run every 4 hours'
BATCH_SHARE = 0.5              # Batch API คิดครึ่งราคาของ interactive


def iso_week(d: str) -> str:
    """'2026-08-31' → '2026-W36'"""
    try:
        y, w, _ = date.fromisoformat(d[:10]).isocalendar()
        return f"{y}-W{w:02d}"
    except (TypeError, ValueError):
        return "ไม่รู้สัปดาห์"


def price_thb(model, tok_in, tok_out, tok_think):
    """ค่าอ่านของแถวเดียว เป็นบาท ราคาเต็ม (ยังไม่หักส่วนลด batch).

    thinking คิดเป็น output ตามที่ Gemini คิดเงิน โมเดลที่ไม่มีในตารางราคาให้เป็น None
    เพื่อไม่ให้เดาราคาแล้วรายงานเลขที่ไม่จริง"""
    p = config.GEMINI_PRICE.get(model)
    if not p:
        return None
    usd_in, usd_out = p
    out = (tok_out or 0) + (tok_think or 0)
    return ((tok_in or 0) * usd_in + out * usd_out) / 1_000_000 * config.USD_THB


def load():
    t, j = db.trips.c, db.jobs.c
    with db.engine.begin() as c:
        return [dict(r) for r in c.execute(
            select(t.id, t.model, t.tok_in, t.tok_out, t.tok_think, t.status, t.committed,
                   j.date_from, j.created_at)
            .select_from(db.trips.join(db.jobs, j.id == t.job_id))).mappings().all()]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-from", default=BATCH_FROM, help="งานที่เปิดตั้งแต่วันนี้คิดราคา batch")
    ap.add_argument("--by-model", action="store_true")
    a = ap.parse_args(argv)

    db.init_db()
    rows = load()
    read = [r for r in rows if r["model"] and (r["tok_in"] or r["tok_out"])]
    print(f"แถวทั้งหมด {len(rows):,} · ในนั้นมีบันทึกการอ่าน {len(read):,} "
          f"· ไม่มี token {len(rows) - len(read):,} (ครึ่งล่างที่ยุบเข้าคู่ หรืออ่านก่อนเก็บ token)")

    weeks, models, unpriced = collections.defaultdict(lambda: collections.Counter()), collections.Counter(), collections.Counter()
    for r in read:
        full = price_thb(r["model"], r["tok_in"], r["tok_out"], r["tok_think"])
        if full is None:
            unpriced[r["model"]] += 1
            continue
        batch = (r["created_at"] or "")[:10] >= a.batch_from
        w = weeks[iso_week(r["date_from"])]
        w["รูป"] += 1
        w["tok_in"] += r["tok_in"] or 0
        w["tok_out"] += (r["tok_out"] or 0) + (r["tok_think"] or 0)
        w["เต็ม"] += full
        w["จ่ายจริง"] += full * (BATCH_SHARE if batch else 1.0)
        w["batch"] += 1 if batch else 0
        models[r["model"]] += 1

    print(f"\n{'สัปดาห์':<12}{'รูปที่อ่าน':>10}{'ผ่าน batch':>11}{'token เข้า':>13}{'token ออก':>12}"
          f"{'ราคาเต็ม ฿':>13}{'จ่ายจริง ฿':>13}{'฿/รูป':>8}")
    tot = collections.Counter()
    for w in sorted(weeks):
        c = weeks[w]
        per = c["จ่ายจริง"] / c["รูป"] if c["รูป"] else 0
        print(f"{w:<12}{c['รูป']:>10,}{c['batch']:>11,}{c['tok_in']:>13,}{c['tok_out']:>12,}"
              f"{c['เต็ม']:>13,.0f}{c['จ่ายจริง']:>13,.0f}{per:>8.3f}")
        tot.update(c)
    per = tot["จ่ายจริง"] / tot["รูป"] if tot["รูป"] else 0
    print(f"{'รวม':<12}{tot['รูป']:>10,}{tot['batch']:>11,}{tot['tok_in']:>13,}{tot['tok_out']:>12,}"
          f"{tot['เต็ม']:>13,.0f}{tot['จ่ายจริง']:>13,.0f}{per:>8.3f}")
    print(f"\nส่วนลด batch ประหยัดไป ฿{tot['เต็ม'] - tot['จ่ายจริง']:,.0f} "
          f"(คิดที่ ${config.USD_THB:.0f}/USD, งานที่เปิดตั้งแต่ {a.batch_from} คิดครึ่งราคา)")
    if a.by_model:
        print("\nโมเดลที่อ่าน:")
        for m, n in models.most_common():
            print(f"  {m:<28}{n:>8,} รูป")
    if unpriced:
        print("\n⚠ ไม่มีราคาในตาราง GEMINI_PRICE — ไม่ถูกนับ:")
        for m, n in unpriced.most_common():
            print(f"  {m or '(ไม่ระบุโมเดล)':<28}{n:>8,} รูป")
    return 0


if __name__ == "__main__":
    sys.exit(main())
