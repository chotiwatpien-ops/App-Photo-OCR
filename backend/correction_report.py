# -*- coding: utf-8 -*-
"""What people corrected in the review queue: the free ground truth for how well we read.

There is no labelled set to score the reader against, but every fix a person makes in the
queue is one: action_log keeps each edit with the value before and after, each approval, and
each delete. This report turns those into two answers.

1. Which fields the reader gets wrong, and how (an empty field filled in, the ฿ sign read as a
   leading digit, a small slip, a different number).
2. For each reason a row was held, how often the person approved it unchanged. A hold rule
   whose rows are nearly always approved as they are costs review time for nothing; one whose
   rows get corrected or deleted is earning its place.

Read-only. The output names trips by id and fields by name, never a rider, an address or a
booking code: it is printed to a public Actions log.

    python correction_report.py --from 2026-11-09 --to 2026-11-15
    python correction_report.py --days 7
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

MONEY = {"net_earnings", "base_fare", "bonus", "turbo", "tip", "tolls", "passenger_total",
         "passenger_paid", "intl_fee", "app_fee", "other_adj", "discount", "insurance_fee",
         "passenger_tolls", "fare_refund", "distance_km"}
IGNORED = {"note"}


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def money_error(before, after):
    """How a number was wrong, in the reviewer's terms."""
    b, a = _num(before), _num(after)
    if b is None and a is not None:
        return "ว่าง แล้วคนกรอกให้"
    if a in (None, 0) and b:
        return "คนลบออก หรือแก้เป็น 0"
    if b is None or a is None or b == a:
        return None
    if a and b > a * 5 and str(int(b)).endswith(str(int(a))):
        return "฿ ถูกอ่านเป็นเลขนำหน้า"
    if abs(b - a) <= max(abs(a), 1) * 0.10:
        return "ต่างเล็กน้อย (ไม่เกิน 10%)"
    return "ต่างมาก"


def hold_reason(row):
    """Why the row was waiting, read from what the system wrote on it."""
    import pipeline
    if row is None:
        return "แถวถูกลบไปแล้ว"
    note = row.get("note") or ""
    if pipeline.UNWITNESSED_TURBO in note:
        return "turbo ที่เติมเอง ไม่มีตัวเลขยืนยัน"
    if "รวมทิป" in note and "ไม่รู้ว่าโบนัส" in note:
        return "ไม่รู้ว่าโบนัสรวมทิปแล้วหรือยัง"
    if pipeline.HALVES_DISAGREE in note:
        return "สองครึ่งแสดงยอดไม่ตรงกัน"
    if row.get("duplicate_of"):
        return "สงสัยว่าซ้ำ"
    if note.startswith("รวม 2 รูป") and "จับคู่ตามลำดับไฟล์" in note:
        return "จับคู่ตามลำดับไฟล์ (ยอดไม่ได้ยืนยัน)"
    status = row.get("check_status")
    if status == "fail":
        return "ตัวเลขไม่ลงตัว"
    if status == "no_data":
        return "ข้อมูลไม่ครบ"
    if not row.get("trip_date"):
        return "ไม่มีวันที่"
    return "ผ่านแล้ว รอคนกด"


def load(d_from, d_to):
    """Each touched trip -> {edits: [(field, before, after)], approved, deleted}; plus the
    current rows of those trips."""
    from sqlalchemy import select
    import db
    a = db.action_log.c
    with db.engine.begin() as c:
        logs = c.execute(select(a.action, a.target, a.detail)
                         .where(a.at >= d_from, a.at < (date.fromisoformat(d_to) + timedelta(days=1)).isoformat(),
                                a.action.in_(["trip.edit", "trip.approve", "trip.delete",
                                              "queue.approve_passing"]),
                                (a.status.is_(None)) | (a.status < 400))
                         .order_by(a.id)).all()
    touched = defaultdict(lambda: {"edits": [], "approved": False, "deleted": False, "snapshot": None})
    for action, target, detail in logs:
        d = json.loads(detail) if detail else {}
        tid = int(target.split(":")[1]) if target and target.startswith("trip:") else None
        if action == "trip.edit" and tid:
            for k, after in (d.get("after") or {}).items():
                if k not in IGNORED:
                    touched[tid]["edits"].append((k, (d.get("before") or {}).get(k), after))
        elif action == "trip.approve" and tid:
            touched[tid]["approved"] = True
        elif action == "trip.delete" and tid:
            touched[tid]["deleted"] = True
            touched[tid]["snapshot"] = d.get("row")
        elif action == "queue.approve_passing":
            for t in d.get("trip_ids") or []:
                touched[int(t)]["approved"] = True
    rows = {}
    if touched:
        t = db.trips.c
        with db.engine.begin() as c:
            for r in c.execute(select(t.id, t.kind, t.check_status, t.note, t.duplicate_of,
                                      t.trip_date, t.service_type, t.model)
                               .where(t.id.in_(list(touched)))).mappings().all():
                rows[r["id"]] = dict(r)
    return dict(touched), rows


def outcome(t):
    if t["deleted"]:
        return "ลบทิ้ง"
    real = [e for e in t["edits"] if e[1] != e[2]]
    if t["approved"]:
        return "แก้แล้วอนุมัติ" if real else "อนุมัติโดยไม่แก้"
    return "แก้แล้ว ยังไม่อนุมัติ" if real else "ยังไม่ได้ตัดสิน"


def report(touched, rows, d_from, d_to):
    lines = [f"# คนแก้อะไรในคิวตรวจ {d_from} ถึง {d_to}", ""]
    if not touched:
        return "\n".join(lines + ["ไม่มีการแก้ อนุมัติ หรือลบในช่วงนี้"])
    by_outcome = Counter(outcome(t) for t in touched.values())
    lines += [f"แถวที่คนแตะ **{len(touched):,}** แถว: " +
              " · ".join(f"{k} {v:,}" for k, v in by_outcome.most_common()), ""]

    lines += ["## เหตุที่แถวมารอ คุ้มเวลาตรวจไหม", "",
              "แถวที่อนุมัติโดยไม่แก้เลย คือแถวที่ระบบกักไว้โดยไม่จำเป็น",
              "",
              "| เหตุที่มารอ | แถว | อนุมัติโดยไม่แก้ | แก้แล้วอนุมัติ | ลบทิ้ง |",
              "|---|---:|---:|---:|---:|"]
    by_reason = defaultdict(Counter)
    for tid, t in touched.items():
        by_reason[hold_reason(rows.get(tid))][outcome(t)] += 1
    for reason, c in sorted(by_reason.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        pct = lambda k: f"{c[k]:,} ({c[k] / n:.0%})"   # noqa: E731
        lines.append(f"| {reason} | {n:,} | {pct('อนุมัติโดยไม่แก้')} | {pct('แก้แล้วอนุมัติ')} | {pct('ลบทิ้ง')} |")

    fields = Counter()
    kinds = defaultdict(Counter)
    examples = defaultdict(list)
    svc = Counter()
    for tid, t in touched.items():
        for field, before, after in t["edits"]:
            if before == after:
                continue
            fields[field] += 1
            if field in MONEY:
                kind = money_error(before, after)
                if kind:
                    kinds[field][kind] += 1
            if field == "service_type":
                svc[(before or "ว่าง", after or "ว่าง")] += 1
            if len(examples[field]) < 8:
                examples[field].append(tid)
    lines += ["", "## ช่องที่คนแก้บ่อยที่สุด", "",
              "| ช่อง | ครั้ง | แก้แบบไหน | ตัวอย่างแถว |", "|---|---:|---|---|"]
    for field, n in fields.most_common():
        how = " · ".join(f"{k} {v}" for k, v in kinds[field].most_common()) or "-"
        lines.append(f"| {field} | {n:,} | {how} | {', '.join(f'#{i}' for i in examples[field])} |")
    if svc:
        lines += ["", "## ประเภทรถที่คนเปลี่ยน", "", "| จาก | เป็น | ครั้ง |", "|---|---|---:|"]
        lines += [f"| {b} | {a} | {n} |" for (b, a), n in svc.most_common()]
    models = Counter((rows.get(tid) or {}).get("model") or "-" for tid, t in touched.items()
                     if outcome(t) in ("แก้แล้วอนุมัติ", "ลบทิ้ง"))
    if models:
        lines += ["", "แถวที่ต้องแก้หรือลบ แยกตามโมเดลที่อ่าน: " +
                  " · ".join(f"{m} {n}" for m, n in models.most_common())]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="คนแก้อะไรในคิวตรวจ (อ่านอย่างเดียว)")
    ap.add_argument("--from", dest="d_from")
    ap.add_argument("--to", dest="d_to")
    ap.add_argument("--days", type=int, default=7, help="ไม่ใส่ --from: ย้อนหลังกี่วันถึงวันนี้")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    import db
    db.init_db()
    d_to = a.d_to or date.today().isoformat()
    d_from = a.d_from or (date.fromisoformat(d_to) - timedelta(days=a.days - 1)).isoformat()
    touched, rows = load(d_from, d_to)
    text = report(touched, rows, d_from, d_to)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
