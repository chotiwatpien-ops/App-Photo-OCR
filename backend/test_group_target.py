# -*- coding: utf-8 -*-
"""Each vehicle group owes the customer 1,470 trips a week on its own.

The rule that matters: a group running over target does NOT cover one running short. Real
W35 numbers — 2 W Saver 1,314 · 2 W Standard 1,576 · 4 W Standard 1,445 — total 4,335 against
4,410, which looks like a 75-trip gap but is really 181: the 106 extra Standard bikes buy
nothing. The Agent has to be sent after the right vehicle type.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import config                                                     # noqa: E402
import main                                                       # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


def job(name, done, job_id=1):
    return {"id": job_id, "driver_name": name, "done": done, "pending": 0, "errors": 0,
            "approved": done, "waiting": 0}


def week(groups, date_from="2026-08-24"):
    """groups: {category: [(rider, trips), ...]}"""
    return {"week": "2026-W35", "date_from": date_from, "date_to": "2026-08-30",
            "groups": [{"category": cat,
                        "jobs": [job(n, d, i * 100 + k) for k, (n, d) in enumerate(riders)]}
                       for i, (cat, riders) in enumerate(groups.items())]}


def run(weeks):
    real = main.db.weeks_overview
    main.db.weeks_overview = lambda: weeks
    try:
        return main.completeness()
    finally:
        main.db.weeks_overview = real


check("เป้าต่อกลุ่มรถคือ 1,470", config.WEEKLY_TARGET_PER_GROUP == 1470)

# W35 ของจริง ย่อส่วนเป็นไรเดอร์ก้อนเดียวต่อกลุ่ม
w35 = run([week({
    "2 W Saver":    [(f"saver{i}", 1314 // 70 + (1 if i < 1314 % 70 else 0)) for i in range(70)],
    "2 W Standard": [(f"std{i}", 1576 // 70 + (1 if i < 1576 % 70 else 0)) for i in range(70)],
    "4 W Standard": [(f"car{i}", 1445 // 70 + (1 if i < 1445 % 70 else 0)) for i in range(70)],
})])["weeks"][0]
by = {g["category"]: g for g in w35["groups"]}

check("2 W Saver เก็บได้ 1,314", by["2 W Saver"]["done"] == 1314)
check("2 W Saver ขาด 156", by["2 W Saver"]["missing"] == 156)
check("4 W Standard ขาด 25", by["4 W Standard"]["missing"] == 25)
check("2 W Standard เกินเป้า จึงขาด 0", by["2 W Standard"]["missing"] == 0)
check("ทุกกลุ่มมีเป้า 1,470 เท่ากัน", all(g["target"] == 1470 for g in w35["groups"]))
check("ยอดขาดรวมคือ 181 ไม่ใช่ 75 (กลุ่มที่เกินไม่ช่วยกลุ่มที่ขาด)", w35["missing"] == 181)
check("เป้ารวมทั้งสัปดาห์ 4,410", w35["target"] == 4410)
check("มี 3 กลุ่มรถ", len(w35["groups"]) == 3)

# กลุ่มที่ไม่ส่งอะไรเลยทั้งสัปดาห์ ต้องยังโผล่ในรายงาน — ไม่ใช่หายไปเฉยๆ
two = run([
    week({"2 W Saver": [("a", 21)], "4 W Standard": [("b", 21)]}, "2026-08-17"),
    week({"2 W Saver": [("a", 21)]}, "2026-08-24"),
])["weeks"]
later = [w for w in two if w["date_from"] == "2026-08-24"][0]
cats = {g["category"]: g for g in later["groups"]}
check("กลุ่มที่เงียบทั้งสัปดาห์ยังอยู่ในรายงาน", "4 W Standard" in cats)
check("กลุ่มที่เงียบขาดเต็มจำนวน 1,470", cats["4 W Standard"]["missing"] == 1470)

# คนไม่พอ: 10 คน × 21 = 210 ต่อให้ส่งครบก็ไม่ถึง 1,470
thin = run([week({"2 W Saver": [(f"r{i}", 21) for i in range(10)]})])["weeks"][0]
g = thin["groups"][0]
check("กำลังคนสูงสุดคือ 210 งาน", g["capacity"] == 210)
check("ต้องหาไรเดอร์เพิ่มอีก 60 คน", g["heads_needed"] == 60)
check("ไรเดอร์ครบโควตาตัวเองแล้ว ไม่มีใครติดค้าง", g["short"] == [])

# กลุ่มนอกสี่ประเภทรถ (อัปโหลดมือ) ไม่มีเป้าของตัวเอง — วัดจากจำนวนคนเหมือนเดิม
manual = run([week({"อัปโหลดมือ": [("x", 10)]})])["weeks"][0]
m = manual["groups"][0] if manual["groups"][0]["category"] == "อัปโหลดมือ" else manual["groups"][-1]
check("กลุ่มอัปโหลดมือไม่ถูกตั้งเป้า 1,470", m["target"] == config.EXPECTED_TRIPS_PER_WEEK)
check("กลุ่มอัปโหลดมือไม่บอกให้หาคนเพิ่ม", m["heads_needed"] == 0)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
