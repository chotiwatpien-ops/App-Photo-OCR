# -*- coding: utf-8 -*-
"""drive_usage: the space report sums every file into the right week and folder kind, counts
the system account's own bytes apart, and never prints a file or rider name."""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-usage-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

import drive_usage as du                                        # noqa: E402

ok = True
MB = 1024 ** 2


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and cond


TREE = {
    "inbox": [("Week 24-30 Aug", True), ("Export Pic", True), ("loose.jpg", 1, False)],
    "inbox/Week 24-30 Aug": [("2 W Saver", True), ("Pool", True), ("_ทิ้ง-กดลบ", True)],
    "inbox/Week 24-30 Aug/2 W Saver": [("01 สมชาย", True)],
    "inbox/Week 24-30 Aug/2 W Saver/01 สมชาย": [("ops-upload.jpg", 3, False), ("Album_1+2_฿50.jpg", 2, True)],
    "inbox/Week 24-30 Aug/Pool": [("2W Album", True), ("_ใช้แล้ว", True)],
    "inbox/Week 24-30 Aug/Pool/2W Album": [("left.jpg", 1, False)],
    "inbox/Week 24-30 Aug/Pool/_ใช้แล้ว": [("2W Album", True)],
    "inbox/Week 24-30 Aug/Pool/_ใช้แล้ว/2W Album": [("top.jpg", 4, False)],
    "inbox/Week 24-30 Aug/_ทิ้ง-กดลบ": [("x.jpg", 1, True)],
    "inbox/Export Pic": [("2026-W35", True), ("Rider Trips Phase 3.xlsx", 5, True)],
    "inbox/Export Pic/2026-W35": [("2 W Saver", True), ("_แทนที่แล้ว", True)],
    "inbox/Export Pic/2026-W35/2 W Saver": [("WK35-สมชาย1.jpg", 2, True)],
    "inbox/Export Pic/2026-W35/_แทนที่แล้ว": [("WK35-old.jpg", 1, True)],
}


def children(folder_id):
    return [{"id": f"{folder_id}/{n}", "name": n, "folder": len(e) == 1,
             "bytes": (e[0] * MB if len(e) == 2 else 0), "mine": e[1] if len(e) == 2 else False}
            for n, *e in TREE.get(folder_id, [])]


inbox_files = du.walk(children, "inbox", skip_ids={"inbox/Export Pic"})
export_files = du.walk(children, "inbox/Export Pic")
check("Inbox ไม่นับ Exports ที่อยู่ข้างในซ้ำ", all("Export Pic" not in p for p, _e in inbox_files))
t_in, t_ex = du.tally(inbox_files, "inbox"), du.tally(export_files, "exports")

cell = t_in[("2026-W35", du.RIDER)]
check("โฟลเดอร์ไรเดอร์ของ Week 24-30 Aug นับเป็น 2026-W35", cell["files"] == 2 and cell["bytes"] == 5 * MB, cell)
check("ส่วนของบัญชีระบบคือรูปคู่ที่กองต่อเท่านั้น (2 MB)", cell["mine"] == 2 * MB, cell["mine"])
check("ต้นฉบับใน _ใช้แล้ว แยกชนิดของมัน",
      t_in[("2026-W35", du.INBOX_KINDS["_ใช้แล้ว"])]["bytes"] == 4 * MB)
check("รูปในกองที่ยังไม่จับคู่", t_in[("2026-W35", du.POOL)]["bytes"] == 1 * MB)
check("รูปที่คนกดลบ", t_in[("2026-W35", du.INBOX_KINDS["_ทิ้ง-กดลบ"])]["mine"] == 1 * MB)
check("ไฟล์ที่ราก Inbox ไม่มีสัปดาห์", t_in[(None, "ไฟล์ที่ราก Inbox")]["files"] == 1)
check("รูปส่งลูกค้าของ 2026-W35", t_ex[("2026-W35", du.CUSTOMER)]["mine"] == 2 * MB)
check("รูปส่งลูกค้าที่ถูกแทนที่ แยกชนิด", t_ex[("2026-W35", du.EXPORT_KINDS["_แทนที่แล้ว"])]["files"] == 1)
check("Excel ที่ราก Exports", t_ex[(None, "ไฟล์ Excel และไฟล์อื่นที่ราก Exports")]["bytes"] == 5 * MB)

text = du.report({"limit": str(15 * 1024 ** 3), "usage": str(14 * 1024 ** 3), "usageInDriveTrash": "0"},
                 [t_in, t_ex], closed={"2026-W35"})
check("รายงานบอกว่าใช้ไปกี่ % ของเพดาน", "93%" in text)
check("สัปดาห์ที่ปิดแล้วติดป้ายปิดแล้ว", "| 2026-W35 | ปิดแล้ว |" in text)
check("ไม่มีชื่อไฟล์หรือชื่อไรเดอร์ในรายงาน (repo เป็น public)",
      not any(x in text for x in ("สมชาย", "ops-upload", "Album_1", "WK35-", "top.jpg")))

print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
