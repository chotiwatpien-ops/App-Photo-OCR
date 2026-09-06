# -*- coding: utf-8 -*-
"""A pool run's report has to say why a picture stayed behind, not just when one moved.

Run #14 read 609 pre-joined pictures and moved 379. The other 230 printed a line with nothing
after the target folder, because render() only appended text when the move had produced a path —
a failed move leaves its reason in the same field, and the reason was thrown away. The answer
(the rider name list had run out) reached only the web panel. Needs no sample album."""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import pool                                                     # noqa: E402

ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("  ✓ " if cond else "  ✗ ") + name)


def report(long_items=(), pairs=()):
    return {"totals": {"n_images": 2, "n_duplicates": 0, "n_long": len(long_items),
                       "n_pairs": len(pairs), "n_leftover": 0, "pair_rate": None},
            "duplicates": [], "errors": [],
            "albums": [{"week": "W", "group": "", "album": "A", "n_images": 2,
                        "n_duplicates": 0, "long": list(long_items), "pairs": list(pairs),
                        "leftovers": []}]}


txt = pool.render(report(long_items=[
    {"file": "ก.jpg", "target": "2 W Saver", "moved": "2 W Saver/01-x/ก.jpg"},
    {"file": "ข.jpg", "target": "2 W Saver", "moved": "รายชื่อ Home ของ 2W หมดแล้ว"},
    {"file": "ค.jpg", "target": "2 W Saver"}]))
print("รูปยาว:")
check("ย้ายสำเร็จขึ้น ✔", "ก.jpg  → 2 W Saver  ✔ ย้ายแล้ว" in txt)
check("ย้ายไม่ได้ต้องบอกเหตุผล", "⚠ รายชื่อ Home ของ 2W หมดแล้ว" in txt)
check("ยังไม่ได้ลองย้ายก็ไม่ต้องขึ้นอะไร", "ค.jpg  → 2 W Saver\n" in txt + "\n")

txt = pool.render(report(pairs=[
    {"top": "a.jpg", "bottom": "b.jpg", "amount": 56, "tier": "A", "distance": 1,
     "moved": "2 W Saver/01-x/a_b.jpg"},
    {"top": "c.jpg", "bottom": "d.jpg", "amount": 70, "tier": "A", "distance": 1,
     "moved": "รายชื่อ Home ของ 2W หมดแล้ว"}]))
print("คู่:")
check("ย้ายสำเร็จขึ้น ✔", "✔ 2 W Saver/01-x/a_b.jpg" in txt)
check("ย้ายไม่ได้ต้องบอกเหตุผล", "⚠ รายชื่อ Home ของ 2W หมดแล้ว" in txt)

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
