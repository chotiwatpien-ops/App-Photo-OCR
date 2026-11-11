# -*- coding: utf-8 -*-
"""The week's duplicate pictures, one comparison per repeat, to forward to the admins.

The customer asked for a report that says, for every repeated picture, which picture it repeats,
in which folder, sent by whom, with the two side by side, so they can pass it on to the admin who
sent it (Fiat 2026-11-11). Beside the duplicate report the round writes:

    Exports/_รายงานรูปซ้ำ/<2026-W46> ตัวอย่าง/<album>/
        00 สรุป.jpg                          the album's numbers
        ไฟล์ซ้ำ 112687_1.jpg                  an exact copy beside the file it copies
        แคปจอ 2 รอบ #40214 ฿34.jpg            a read repeat beside the trip it repeats

and the report's first sheet lists the same entries with a link to each picture. "Sent by" is the
admin named in the album (2W <admin> ...): which rider inside an album sent a picture is not
known. Half pictures the pool could not pair are not repeats and are not shown: they may be the
pairing's own miss (Fiat 2026-11-11).

A picture already there is not made again. One no longer wanted moves to _เก่า. Nothing here
can stop the round."""
import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import duplicate_report as dr

OLD_DIR = "_เก่า"
SUMMARY = "00 สรุป.jpg"
FONTS = [("/usr/share/fonts/truetype/tlwg/Loma.ttf", "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf"),
         ("/usr/share/fonts/truetype/tlwg/Garuda.ttf", "/usr/share/fonts/truetype/tlwg/Garuda-Bold.ttf"),
         ("C:/Windows/Fonts/LeelawUI.ttf", "C:/Windows/Fonts/LeelaUIb.ttf")]
TITLE = {dr.KIND_SAME_WEEK: "แคปจอ 2 รอบ", dr.KIND_SAME_FILE: "ไฟล์เดียวกัน อ่านแล้ว",
         dr.KIND_BOTTOM: "รูปล่างเกิน", dr.KIND_SUSPECT: "ข้อมูลตรงกัน เลขจองต่าง"}
COPY_TITLE = "ไฟล์ซ้ำ อัปโหลดซ้ำ"
RED, AMBER, GREEN, GREY = (178, 58, 72), (196, 131, 30), (46, 125, 91), (96, 104, 118)


@dataclass(frozen=True)
class Entry:
    """One repeated picture and the picture it repeats."""
    kind: str             # the reason, as Ops says it
    album: str            # the album the repeat came in
    file: str             # the repeat's file, as Ops would find it in that album
    file_id: str
    orig_album: str
    orig_file: str
    orig_id: str          # None when the original's picture cannot be found
    status: str           # what became of the repeat
    counted_as: str = ""  # the original's name in the customer's folder, when it has one
    code: str = ""
    amount: float = None
    name: str = ""        # the comparison picture's file name


def drive_id(url):
    m = re.search(r"/d/([\w-]+)|[?&]id=([\w-]+)", url or "")
    return (m.group(1) or m.group(2)) if m else None


def sender(album):
    """The admin an album names: '2W Karnjana 1748 งาน' → 'Karnjana'."""
    words = re.sub(r"^\s*[24]W(-\w+)?\s*", "", album or "").split()
    return words[0] if words else (album or "")


def line_photos(file_name):
    """'2W X_116359+116360_฿58.jpg' → 'รูป 116359 + 116360' (the numbers Ops sees in LINE)."""
    m = re.search(r"_(\d+)\+(\d+)_", file_name or "")
    return f"รูป {m.group(1)} + {m.group(2)}" if m else (file_name or "").split("/")[-1]


def _copy_name(copy, orig, orig_id):
    """'ไฟล์ซ้ำ 112687_1 (ต้นฉบับ 112687_0).jpg'. Whether the original was found is part of the
    name, so a picture made without it is made again once it can be found."""
    stem = lambda f: re.sub(r"\.[A-Za-z]+$", "", f or "")
    tail = f"(ต้นฉบับ {stem(orig)})" if orig_id else f"(ไม่พบรูปต้นฉบับ {stem(orig)})"
    return _safe(f"ไฟล์ซ้ำ {stem(copy)} {tail}") + ".jpg"


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]', " ", s or "").strip()


def entries(cases, undecided, pre, half_ids):
    """[Entry] of one week: every read repeat and every exact copy. half_ids maps (album, file)
    to the Drive id of a half picture the pool paired (duplicate_report.half_ids)."""
    out = []
    for c, waiting in [(c, False) for c in cases] + [(c, True) for c in undecided]:
        mine, twin = drive_id(c.get("ลิงก์รูป")), drive_id(c.get("twin_url"))
        if not mine:
            continue
        kind = TITLE.get(c.get("ประเภทการซ้ำ"), "งานซ้ำ")
        amount = c.get("ยอด")
        out.append(Entry(
            kind=kind, album=c["ไรเดอร์ผู้ส่ง"], file=line_photos(c.get("ไฟล์ที่ซ้ำ")), file_id=mine,
            orig_album=c.get("ของไรเดอร์") or "", orig_file=line_photos(c.get("ซ้ำกับไฟล์")), orig_id=twin,
            status="รอคนตัดสิน" if waiting else "ไม่นับ (ตัดออก)", counted_as=c.get("รูปที่ส่งลูกค้า") or "",
            code=c.get("รหัสการจอง") or "", amount=amount,
            name=_safe(f"{kind} #{c['id']}" + (f" ฿{amount:,.0f}" if amount is not None else "")) + ".jpg"))
    for p in pre:
        mine = drive_id(p.get("ลิงก์รูป"))
        if not mine:
            continue
        orig_album, _, orig_file = (p.get("ซ้ำกับไฟล์") or "").rpartition("/")
        orig_album = orig_album or p.get("ของอัลบั้ม") or ""
        out.append(Entry(
            kind=COPY_TITLE, album=p.get("ไรเดอร์ผู้ส่ง") or "", file=p.get("ไฟล์ที่ซ้ำ") or "", file_id=mine,
            orig_album=orig_album, orig_file=orig_file, orig_id=half_ids.get((orig_album, orig_file)),
            status="ไม่ได้นับเป็นงาน", name=_copy_name(p.get("ไฟล์ที่ซ้ำ"), orig_file,
                                                         half_ids.get((orig_album, orig_file)))))
    return out


def _fonts():
    from pathlib import Path

    from PIL import ImageFont
    for regular, bold in FONTS:
        if Path(regular).exists() and Path(bold).exists():
            return (lambda s: ImageFont.truetype(regular, s)), (lambda s: ImageFont.truetype(bold, s))
    return None


def _jpeg(im, quality=85):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def render(e, orig, mine, fonts, h=900) -> bytes:
    """The original on the left, the repeat on the right, each with where it came from."""
    from PIL import Image, ImageDraw
    reg, bold = fonts
    gap, pad, top, cap = 40, 40, 150, 230
    sides = []
    for b, role, color, f, album, extra in (
            (orig, "ต้นฉบับ (นับแล้ว)" if e.kind != COPY_TITLE else "ต้นฉบับ", GREEN, e.orig_file, e.orig_album,
             f"ในไฟล์ลูกค้า {e.counted_as}" if e.counted_as else ""),
            (mine, f"รูปซ้ำ · {e.status}", RED, e.file, e.album, "")):
        if b:
            p = Image.open(io.BytesIO(b)).convert("RGB")
            p = p.resize((int(p.width * h / p.height), h))
        else:
            p = Image.new("RGB", (int(h * 0.55), h), (240, 240, 240))
        sides.append((p, b is None, role, color, f, album, extra))
    width = max(sum(s[0].width for s in sides) + gap + 2 * pad, 1100)
    im = Image.new("RGB", (width, top + h + cap), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, width, 10], fill=AMBER if e.kind == COPY_TITLE else RED)
    d.text((pad, 30), e.kind, font=bold(46), fill=(20, 20, 20))
    sub = " · ".join(x for x in (f"เลขจอง {e.code}" if e.code else "",
                                 f"฿{e.amount:,.0f}" if e.amount is not None else "",
                                 "ไฟล์เหมือนกันทุกไบต์" if e.kind == COPY_TITLE else "") if x)
    d.text((pad, 92), sub, font=reg(30), fill=GREY)
    x = pad
    for p, missing, role, color, f, album, extra in sides:
        im.paste(p, (x, top))
        d.rectangle([x - 2, top - 2, x + p.width + 1, top + h + 1], outline=(200, 200, 200), width=2)
        if missing:
            d.text((x + 20, top + h // 2), "ไม่พบรูปต้นฉบับ", font=reg(28), fill=GREY)
        y = top + h + 16
        for text, font, fill in ((role, bold(30), color), (f"ไฟล์ {f}", reg(26), (20, 20, 20)),
                                 (f"อัลบั้ม {album}", reg(26), (20, 20, 20)),
                                 (f"ส่งโดย {sender(album)}", reg(26), (20, 20, 20)), (extra, reg(24), GREY)):
            if text:
                d.text((x, y), text, font=font, fill=fill)
                y += 36
        x += p.width + gap
    return _jpeg(im)


def summary_lines(row):
    """[(label, number, unit, note, kind)] of one album, top to bottom, from its line of
    duplicate_report.album_overview. kind: 'total', 'minus' or 'result'."""
    (_, _, _, _, filed, pre_n, post_n, _, _, _, left, waiting, _,
     pictures, originals, most, trips_n, deleted, real, pending, ops, gap) = row
    lines = [("รูปทั้งหมดในอัลบั้ม", pictures, "รูป", "", "total"),
             ("ไฟล์ซ้ำ อัปโหลดซ้ำ", -pre_n, "รูป", "ไม่ได้นับเป็นงาน", "minus"),
             ("รูปต้นฉบับ", originals, "รูป", "", "total"),
             ("ถ้าจับคู่ได้ครบ", most, "งาน", "1 งาน = รูปบน + รูปล่าง", "total"),
             ("จับคู่ได้แล้ว", trips_n, "งาน", f"หาคู่ไม่ได้ {left or 0:,} รูป · ระบบกำลังตรวจ" if left else "", "total"),
             ("แคปจอซ้ำ / งานซ้ำหลังอ่าน", -post_n, "งาน", "", "minus")]
    if deleted:
        lines.append(("ลบในคิวตรวจ", -deleted, "งาน", "", "minus"))
    lines += [("งานจริง", real, "งาน", "", "total"),
              ("นับในไฟล์ลูกค้า", filed, "งาน", "", "result")]
    if pending:
        lines.append(("ค้างในระบบ", pending, "งาน",
                      f"รออ่าน {waiting:,} รูป" if waiting else "รอตรวจหรือรอลงงาน", "minus"))
    if ops is not None:
        lines.append(("ยอดที่ Ops จดในชื่ออัลบั้ม", ops, "งาน",
                      f"ต่างจากที่รูปให้ได้ {gap:,} งาน" if gap else "ตรงกับที่รูปให้ได้", "total"))
    return lines


def summary_card(week, album, row, fonts) -> bytes:
    """The album's numbers on one card, top to bottom, the way the customer's report reads."""
    from PIL import Image, ImageDraw
    reg, bold = fonts
    lines = summary_lines(row)
    width, pad = 1240, 64
    im = Image.new("RGB", (width, 220 + 100 * len(lines)), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, width, 12], fill=(30, 58, 95))
    d.text((pad, 44), f"สรุปอัลบั้ม {week}", font=bold(52), fill=(20, 24, 32))
    d.text((pad, 120), f"{album}  ·  ส่งโดย {sender(album)}", font=reg(32), fill=GREY)
    y = 190
    for label, n, unit, note, kind in lines:
        color = {"minus": RED, "result": GREEN}.get(kind, (20, 24, 32))
        if kind == "result":
            d.rectangle([pad - 20, y - 6, width - pad + 20, y + 84], fill=(234, 246, 240), outline=GREEN, width=3)
        d.line([pad, y - 10, width - pad, y - 10], fill=(226, 229, 235), width=2)
        d.text((pad, y + 6), label, font=bold(36) if kind == "result" else reg(36), fill=color if kind == "result" else (20, 24, 32))
        text = f"{n:,}".replace("-", "−")
        tw = d.textlength(text, font=bold(44))
        d.text((width - pad - 100 - tw, y), text, font=bold(44), fill=color)
        d.text((width - pad - 86, y + 6), unit, font=reg(32), fill=GREY)
        if note:
            d.text((pad, y + 52), note, font=reg(24), fill=GREY)
        y += 100
    return _jpeg(im.crop((0, 0, width, y + 30)), 88)


def write(drive, report_folder, week, found, albums, log=print):
    """Make the week's comparison pictures under report_folder for `found` ([Entry]).
    Returns {Entry.name: Drive file id} of every comparison picture now in place."""
    fonts = _fonts()
    if fonts is None:
        log("⚠ รูปเปรียบเทียบงานซ้ำ: ไม่พบฟอนต์ภาษาไทย — ข้าม")
        return {}
    rows = {r[1]: r for r in albums}                     # every album gets its summary card
    if not found and not rows:
        return {}
    week_dir = drive.ensure_folder(report_folder, f"{week} ตัวอย่าง")

    def fetch(fid):
        try:
            return drive.download(fid) if fid else None
        except Exception:  # noqa: BLE001 — a picture that cannot be fetched leaves its side empty
            return None

    links, made = {}, 0
    for album in sorted({e.album for e in found} | set(rows)):
        folder = drive.ensure_folder(week_dir, _safe(album) or "ไม่รู้อัลบั้ม")
        here = {f["name"]: f["id"] for f in drive.list_images(folder)}
        mine = [e for e in found if e.album == album]
        todo = [e for e in mine if e.name not in here]
        with ThreadPoolExecutor(max_workers=8) as ex:
            pics = list(ex.map(lambda e: (fetch(e.orig_id), fetch(e.file_id)), todo))
        for e, (orig, repeat) in zip(todo, pics):
            if repeat is None:
                log(f"  ⚠ ทำรูปเปรียบเทียบ {e.name} ไม่ได้: โหลดรูปซ้ำไม่ได้")
                continue
            here[e.name] = drive.upload_file(folder, e.name, render(e, orig, repeat, fonts), "image/jpeg")
            made += 1
        links.update({e.name: here[e.name] for e in mine if e.name in here})
        if album in rows:
            drive.upload_file(folder, SUMMARY, summary_card(week, album, rows[album], fonts), "image/jpeg")
        keep = {e.name for e in mine} | {SUMMARY}
        stale = [fid for name, fid in here.items() if name not in keep]
        if stale:
            old = drive.ensure_folder(folder, OLD_DIR)
            for fid in stale:
                drive.move_file(fid, old)
    if made:
        log(f"🖼 รูปเปรียบเทียบงานซ้ำ {week}: ทำใหม่ {made} รูป → _รายงานรูปซ้ำ/{week} ตัวอย่าง/")
    return links
