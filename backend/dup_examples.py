# -*- coding: utf-8 -*-
"""Pictures of each week's repeats, ready to post in LINE (Fiat 2026-11-11).

The customer's group asked for examples to take to the people who sent the work ("ยกตัวอย่าง
ส่งให้ดูสักหน่อย ... ไปคุยกับคนที่ส่งมา"). Beside the duplicate report the round now leaves, for
every album of the week that repeats work:

    Exports/_รายงานรูปซ้ำ/<2026-W46> ตัวอย่าง/<album>/
        00 สรุป.jpg                         counts of the album, rewritten when they change
        #40214 แคปจอ 2 รอบ ฿34.jpg           the repeat beside the trip it repeats
        ไฟล์เดียวกัน 112687_1.jpg             one of the album's exact copies, as a sample

A picture already there is not made again (its name carries the row id); a row that is no longer
a repeat has its picture moved to _ไม่ซ้ำแล้ว. Nothing here can stop the round."""
import io
import re
from dataclasses import dataclass

import duplicate_report as dr

OLD_DIR = "_ไม่ซ้ำแล้ว"
SUMMARY = "00 สรุป.jpg"
FONTS = [("/usr/share/fonts/truetype/tlwg/Loma.ttf", "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf"),
         ("/usr/share/fonts/truetype/tlwg/Garuda.ttf", "/usr/share/fonts/truetype/tlwg/Garuda-Bold.ttf"),
         ("C:/Windows/Fonts/LeelawUI.ttf", "C:/Windows/Fonts/LeelaUIb.ttf")]
# the reasons a read row is a repeat, as Ops says them (no tone mark over an upper vowel: without
# a shaping engine those collide)
TITLE = {dr.KIND_SAME_WEEK: "แคปจอ 2 รอบ", dr.KIND_SAME_FILE: "ไฟล์เดียวกัน",
         dr.KIND_BOTTOM: "รูปล่างเกิน", dr.KIND_SUSPECT: "ข้อมูลตรงกัน เลขจองต่าง"}
RED, AMBER = (178, 58, 72), (196, 131, 30)


@dataclass(frozen=True)
class Example:
    album: str
    name: str            # file name in the album's folder; carries the row id, so it is stable
    title: str
    sub: str
    pictures: tuple      # ((drive file id, caption), ...) one or two


def drive_id(url):
    m = re.search(r"/d/([\w-]+)|[?&]id=([\w-]+)", url or "")
    return (m.group(1) or m.group(2)) if m else None


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]', " ", s or "").strip()


def examples(cases, undecided, pre):
    """[Example] of one week: every read repeat with its original, one sample exact copy per album."""
    out = []
    for c, waiting in [(c, False) for c in cases] + [(c, True) for c in undecided]:
        mine, twin = drive_id(c.get("ลิงก์รูป")), drive_id(c.get("twin_url"))
        if not mine or not twin:
            continue
        title = TITLE.get(c.get("ประเภทการซ้ำ"), "งานซ้ำ")
        money = f"฿{c['ยอด']:,.0f}" if c.get("ยอด") is not None else ""
        out.append(Example(
            album=c["ไรเดอร์ผู้ส่ง"],
            name=_safe(f"#{c['id']} {title} {money}") + ".jpg",
            title=title,
            sub=" · ".join(x for x in (f"เลขจอง {c.get('รหัสการจอง')}" if c.get("รหัสการจอง") else "", money,
                                       c.get("วันที่งาน") or "") if x),
            pictures=((twin, "นับแล้ว"), (mine, "รอตัดสิน" if waiting else "ไม่นับ (ตัดออก)"))))
    seen = set()
    for p in pre:
        album, fid = p.get("ไรเดอร์ผู้ส่ง"), drive_id(p.get("ลิงก์รูป"))
        if album in seen or not fid:
            continue
        seen.add(album)
        n = sum(1 for q in pre if q.get("ไรเดอร์ผู้ส่ง") == album)
        out.append(Example(
            album=album, name=_safe(f"ไฟล์เดียวกัน {p.get('ไฟล์ที่ซ้ำ')}"),
            title="ไฟล์เดียวกัน อัปโหลดซ้ำ",
            sub=f"แบบนี้ในอัลบั้มนี้ {n:,} ไฟล์ · ระบบไม่ได้นับเป็นงาน",
            pictures=((fid, f"{p.get('ไฟล์ที่ซ้ำ')} = {(p.get('ซ้ำกับไฟล์') or '').split('/')[-1]}"),)))
    return out


def _fonts():
    from pathlib import Path

    from PIL import ImageFont
    for regular, bold in FONTS:
        if Path(regular).exists() and Path(bold).exists():
            return (lambda s: ImageFont.truetype(regular, s)), (lambda s: ImageFont.truetype(bold, s))
    return None


def render(ex, images, fonts, h=1000) -> bytes:
    """One JPEG: a title, a line under it, then the pictures side by side with their captions."""
    from PIL import Image, ImageDraw
    reg, bold = fonts
    pics = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
    pics = [p.resize((int(p.width * h / p.height), h)) for p in pics]
    gap, pad, top, bot = 40, 40, 150, 90
    width = max(sum(p.width for p in pics) + gap * (len(pics) - 1) + 2 * pad, 1100)
    im = Image.new("RGB", (width, top + h + bot), "white")
    d = ImageDraw.Draw(im)
    color = AMBER if len(pics) == 1 else RED
    d.rectangle([0, 0, width, 10], fill=color)
    d.text((pad, 30), ex.title, font=bold(46), fill=(20, 20, 20))
    d.text((pad, 92), ex.sub, font=reg(30), fill=(90, 90, 90))
    x = pad
    for p, (_, cap) in zip(pics, ex.pictures):
        im.paste(p, (x, top))
        d.rectangle([x - 2, top - 2, x + p.width + 1, top + h + 1], outline=(200, 200, 200), width=2)
        d.text((x, top + h + 20), cap, font=bold(30), fill=color)
        x += p.width + gap
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def summary_card(week, album, row, fonts) -> bytes:
    """The album's numbers on one card. `row` is its line of duplicate_report.album_overview."""
    from PIL import Image, ImageDraw
    reg, bold = fonts
    _, _, _, read, filed, pre_n, post_n, *_rest = row
    waiting = row[11] or 0
    lines = [(bold(44), f"สรุปงานซ้ำ {week}"), (reg(34), f"อัลบั้ม {album}"), (reg(30), ""),
             (reg(34), f"นับในไฟล์ลูกค้า  {filed:,} งาน"),
             (reg(34), f"แคปจอซ้ำ / งานซ้ำหลังอ่าน  {post_n:,} งาน"),
             (reg(34), f"ไฟล์เดียวกัน อัปโหลดซ้ำ  {pre_n:,} ไฟล์ (ไม่ได้นับเป็นงาน)")]
    if waiting:
        lines.append((reg(34), f"ยังรออ่าน  {waiting:,} รูป ตัวเลขอาจเปลี่ยน"))
    im = Image.new("RGB", (1100, 80 + 62 * len(lines)), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1100, 10], fill=RED)
    y = 36
    for font, text in lines:
        d.text((40, y), text, font=font, fill=(20, 20, 20))
        y += 62
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def write(drive, report_folder, week, cases, undecided, pre, albums, log=print):
    """Make the week's example pictures under report_folder. Returns how many pictures were made."""
    fonts = _fonts()
    if fonts is None:
        log("⚠ รูปตัวอย่างงานซ้ำ: ไม่พบฟอนต์ภาษาไทย — ข้าม")
        return 0
    wanted = examples(cases, undecided, pre)
    rows = {r[1]: r for r in albums if r[7]}             # albums that repeat work
    if not wanted and not rows:
        return 0
    week_dir = drive.ensure_folder(report_folder, f"{week} ตัวอย่าง")
    made = 0
    for album in sorted({e.album for e in wanted} | set(rows)):
        folder = drive.ensure_folder(week_dir, _safe(album) or "ไม่รู้อัลบั้ม")
        here = {f["name"]: f["id"] for f in drive.list_images(folder)}
        mine = [e for e in wanted if e.album == album]
        for e in mine:
            if e.name in here:
                continue
            try:
                data = render(e, [drive.download(fid) for fid, _ in e.pictures], fonts)
            except Exception as err:  # noqa: BLE001 — one picture that cannot be fetched is skipped
                log(f"  ⚠ ทำรูปตัวอย่าง {e.name} ไม่ได้: {str(err)[:100]}")
                continue
            drive.upload_file(folder, e.name, data, "image/jpeg")
            made += 1
        if album in rows:
            drive.upload_file(folder, SUMMARY, summary_card(week, album, rows[album], fonts), "image/jpeg")
        stale = [fid for name, fid in here.items() if name != SUMMARY and name not in {e.name for e in mine}]
        if stale:
            old = drive.ensure_folder(folder, OLD_DIR)
            for fid in stale:
                drive.move_file(fid, old)
    if made:
        log(f"🖼 รูปตัวอย่างงานซ้ำ {week}: ทำใหม่ {made} รูป → _รายงานรูปซ้ำ/{week} ตัวอย่าง/")
    return made
