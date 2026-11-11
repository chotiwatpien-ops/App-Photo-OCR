# -*- coding: utf-8 -*-
"""Pictures of each week's repeats, ready to post in LINE (Fiat 2026-11-11).

The customer's group asked for examples to take to the people who sent the work, then for every
repeated picture to be shown, not a sample ("มันต้องมีรูปซ้ำรูปอะไรด้วย ทั้งอัพซ้ำ หรืออื่นๆ").
Only repeats: a half picture the pool could not pair may be the pairing's own miss, not the
sender's (Fiat 2026-11-11), so it is not shown. Beside the duplicate report the round leaves, for
every album of the week that repeats work:

    Exports/_รายงานรูปซ้ำ/<2026-W46> ตัวอย่าง/<album>/
        00 สรุป.jpg                       the album's numbers
        #40214 แคปจอ 2 รอบ ฿34.jpg         a read repeat beside the trip it repeats
        ไฟล์ซ้ำ หน้า 1 จาก 8.jpg            every exact copy, 20 to a page, each named with its original

A pair picture already there is not made again (its name carries the row id). Pages are made again
whenever the report changes, which is the only time this runs. A picture no longer wanted moves to
_เก่า. Nothing here can stop the round."""
import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import duplicate_report as dr

OLD_DIR = "_เก่า"
SUMMARY = "00 สรุป.jpg"
PER_PAGE = 20
FONTS = [("/usr/share/fonts/truetype/tlwg/Loma.ttf", "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf"),
         ("/usr/share/fonts/truetype/tlwg/Garuda.ttf", "/usr/share/fonts/truetype/tlwg/Garuda-Bold.ttf"),
         ("C:/Windows/Fonts/LeelawUI.ttf", "C:/Windows/Fonts/LeelaUIb.ttf")]
TITLE = {dr.KIND_SAME_WEEK: "แคปจอ 2 รอบ", dr.KIND_SAME_FILE: "ไฟล์เดียวกัน",
         dr.KIND_BOTTOM: "รูปล่างเกิน", dr.KIND_SUSPECT: "ข้อมูลตรงกัน เลขจองต่าง"}
RED, AMBER, GREY = (178, 58, 72), (196, 131, 30), (96, 104, 118)


@dataclass(frozen=True)
class Example:
    album: str
    name: str            # file name in the album's folder
    title: str
    sub: str
    pictures: tuple      # ((drive file id, caption), ...): two make a pair, more make a page
    color: tuple = RED
    redo: bool = False   # made again on every run (a page), or only when missing (a pair)


def drive_id(url):
    m = re.search(r"/d/([\w-]+)|[?&]id=([\w-]+)", url or "")
    return (m.group(1) or m.group(2)) if m else None


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]', " ", s or "").strip()


def _pages(album, title, sub_of, tiles, prefix, color):
    pages = [tiles[i:i + PER_PAGE] for i in range(0, len(tiles), PER_PAGE)]
    return [Example(album=album, name=f"{prefix} หน้า {k} จาก {len(pages)}.jpg", title=title,
                    sub=sub_of(k, len(pages)), pictures=tuple(p), color=color, redo=True)
            for k, p in enumerate(pages, 1)]


def examples(cases, undecided, pre):
    """[Example] of one week: every read repeat beside its original, and pages of every exact copy,
    per album."""
    out = []
    for c, waiting in [(c, False) for c in cases] + [(c, True) for c in undecided]:
        mine, twin = drive_id(c.get("ลิงก์รูป")), drive_id(c.get("twin_url"))
        if not mine or not twin:
            continue
        title = TITLE.get(c.get("ประเภทการซ้ำ"), "งานซ้ำ")
        money = f"฿{c['ยอด']:,.0f}" if c.get("ยอด") is not None else ""
        out.append(Example(
            album=c["ไรเดอร์ผู้ส่ง"], name=_safe(f"#{c['id']} {title} {money}") + ".jpg", title=title,
            sub=" · ".join(x for x in (f"เลขจอง {c.get('รหัสการจอง')}" if c.get("รหัสการจอง") else "", money,
                                       c.get("วันที่งาน") or "") if x),
            pictures=((twin, "นับแล้ว"), (mine, "รอตัดสิน" if waiting else "ไม่นับ (ตัดออก)"))))
    for album in sorted({p.get("ไรเดอร์ผู้ส่ง") for p in pre}):
        tiles = sorted(((drive_id(p.get("ลิงก์รูป")),
                         f"{p.get('ไฟล์ที่ซ้ำ')} = {(p.get('ซ้ำกับไฟล์') or '').split('/')[-1]}")
                        for p in pre if p.get("ไรเดอร์ผู้ส่ง") == album and drive_id(p.get("ลิงก์รูป"))),
                       key=lambda t: t[1])
        n = len(tiles)
        out += _pages(album, "ไฟล์เดียวกัน อัปโหลดซ้ำ",
                      lambda k, m: f"ทั้งหมด {n:,} ไฟล์ · ไม่ได้นับเป็นงาน · หน้า {k}/{m}",
                      tiles, "ไฟล์ซ้ำ", AMBER)
    return out


def _fonts():
    from pathlib import Path

    from PIL import ImageFont
    for regular, bold in FONTS:
        if Path(regular).exists() and Path(bold).exists():
            return (lambda s: ImageFont.truetype(regular, s)), (lambda s: ImageFont.truetype(bold, s))
    return None


def _header(d, width, ex, fonts, pad=40):
    reg, bold = fonts
    d.rectangle([0, 0, width, 10], fill=ex.color)
    d.text((pad, 30), ex.title, font=bold(46), fill=(20, 20, 20))
    d.text((pad, 92), ex.sub, font=reg(30), fill=(90, 90, 90))


def _jpeg(im, quality=85):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def render(ex, images, fonts, h=1000) -> bytes:
    """A pair: the two pictures side by side under the title, each with its caption."""
    from PIL import Image, ImageDraw
    pics = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
    pics = [p.resize((int(p.width * h / p.height), h)) for p in pics]
    gap, pad, top, bot = 40, 40, 150, 90
    width = max(sum(p.width for p in pics) + gap * (len(pics) - 1) + 2 * pad, 1100)
    im = Image.new("RGB", (width, top + h + bot), "white")
    d = ImageDraw.Draw(im)
    _header(d, width, ex, fonts)
    x = pad
    for p, (_, cap) in zip(pics, ex.pictures):
        im.paste(p, (x, top))
        d.rectangle([x - 2, top - 2, x + p.width + 1, top + h + 1], outline=(200, 200, 200), width=2)
        d.text((x, top + h + 20), cap, font=fonts[1](30), fill=ex.color)
        x += p.width + gap
    return _jpeg(im)


def render_page(ex, images, fonts, cols=5, tw=230, th=460) -> bytes:
    """A page: up to PER_PAGE small pictures in a grid, each named under it."""
    from PIL import Image, ImageDraw
    gap, pad, top, cap = 20, 40, 150, 56
    rows = (len(images) + cols - 1) // cols
    width = 2 * pad + cols * tw + (cols - 1) * gap
    im = Image.new("RGB", (width, top + rows * (th + cap + gap) + pad), "white")
    d = ImageDraw.Draw(im)
    _header(d, width, ex, fonts)
    small = fonts[0](17)
    for i, (b, (_, label)) in enumerate(zip(images, ex.pictures)):
        x, y = pad + (i % cols) * (tw + gap), top + (i // cols) * (th + cap + gap)
        if b:
            p = Image.open(io.BytesIO(b)).convert("RGB")
            p.thumbnail((tw, th))
            im.paste(p, (x + (tw - p.width) // 2, y))
        d.rectangle([x - 1, y - 1, x + tw, y + th], outline=(210, 210, 210), width=1)
        name, _, original = label.partition(" = ")
        d.text((x, y + th + 6), name, font=small, fill=(20, 20, 20))
        d.text((x, y + th + 28), f"= {original}", font=small, fill=GREY)
    return _jpeg(im, 80)


def summary_card(week, album, row, fonts) -> bytes:
    """The album's numbers on one card. `row` is its line of duplicate_report.album_overview."""
    from PIL import Image, ImageDraw
    reg, bold = fonts
    filed, pre_n, post_n, waiting = row[4], row[5], row[6], row[11] or 0
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
    return _jpeg(im, 88)


def write(drive, report_folder, week, cases, undecided, pre, albums, log=print):
    """Make the week's pictures under report_folder. Returns how many pictures were made."""
    fonts = _fonts()
    if fonts is None:
        log("⚠ รูปตัวอย่างงานซ้ำ: ไม่พบฟอนต์ภาษาไทย — ข้าม")
        return 0
    wanted = examples(cases, undecided, pre)
    rows = {r[1]: r for r in albums if r[7]}             # albums that repeat work
    if not wanted and not rows:
        return 0
    week_dir = drive.ensure_folder(report_folder, f"{week} ตัวอย่าง")

    def fetch(fid):
        try:
            return drive.download(fid)
        except Exception:  # noqa: BLE001 — a picture that cannot be fetched leaves its tile empty
            return None

    made = 0
    for album in sorted({e.album for e in wanted} | set(rows)):
        folder = drive.ensure_folder(week_dir, _safe(album) or "ไม่รู้อัลบั้ม")
        here = {f["name"]: f["id"] for f in drive.list_images(folder)}
        mine = [e for e in wanted if e.album == album]
        for e in mine:
            if e.name in here and not e.redo:
                continue
            with ThreadPoolExecutor(max_workers=8) as ex:
                images = list(ex.map(fetch, [fid for fid, _ in e.pictures]))
            if not e.redo and not all(images):
                log(f"  ⚠ ทำรูปตัวอย่าง {e.name} ไม่ได้: โหลดรูปต้นทางไม่ได้")
                continue
            data = render_page(e, images, fonts) if e.redo else render(e, images, fonts)
            drive.upload_file(folder, e.name, data, "image/jpeg")
            made += 1
        if album in rows:
            drive.upload_file(folder, SUMMARY, summary_card(week, album, rows[album], fonts), "image/jpeg")
        keep = {e.name for e in mine} | {SUMMARY}
        stale = [fid for name, fid in here.items() if name not in keep]
        if stale:
            old = drive.ensure_folder(folder, OLD_DIR)
            for fid in stale:
                drive.move_file(fid, old)
    if made:
        log(f"🖼 รูปตัวอย่างงานซ้ำ {week}: ทำ {made} รูป → _รายงานรูปซ้ำ/{week} ตัวอย่าง/")
    return made
