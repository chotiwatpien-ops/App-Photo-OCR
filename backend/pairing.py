# -*- coding: utf-8 -*-
"""Pair half screenshots BEFORE any paid reading — free, local, no Gemini.

A rider often sends one trip as two screenshots: the top half (route, booking code, the big green
'คุณได้รับ ฿X') and the bottom half (fare breakdown). Reading both halves costs two Gemini calls;
if we can tell which two belong together we stitch them and read once.

How a pair is recognised without understanding Thai:
  * top half    — the biggest green number on the screen is 'คุณได้รับ' (net).
  * bottom half — every number on the screen is collected. The net always appears there, either
                  directly ('รวมรายได้จากรอบขับ ฿X' / 'รายได้จากรอบขับ X') or as base + extras
                  (bonus, turbo, tip on car trips), so net == one number or a sum of 2-3 of them.
  * long image  — one screenshot that already shows the whole trip; nothing to pair.
Albums are usually in shooting order, so the nearest file number wins when amounts collide; a
genuine tie is left unpaired rather than guessed — an unpaired half simply takes the old path
(read separately), a wrong pair would be a wrong trip.

Measured on the Phase2 samples (Sep 2026): ~90% of halves paired at ฿0, ~1.8 s per image on a
laptop CPU. Needs `rapidocr_onnxruntime` (see requirements-pairing.txt); imported lazily so the
web app never loads it.
"""
import io
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

import threading

_local = threading.local()


def _engine():
    """One OCR engine per thread — the pool job inspects images in parallel."""
    e = getattr(_local, "ocr", None)
    if e is None:
        from rapidocr_onnxruntime import RapidOCR      # heavy; only when pairing is asked for
        e = _local.ocr = RapidOCR()
    return e


def _read_text(img):
    res, _ = _engine()(np.asarray(img))
    return " ".join(t for _, t, _ in (res or []))


# --- the green amount ---------------------------------------------------------------------
def _green_blocks(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = (g > 120) & (g > r + 50) & (g > b + 40)
    blue = (b > 150) & (b > r + 60) & (b > g + 30)          # map routes are blue: skip them
    rows = np.where(mask.sum(axis=1) > 2)[0]
    blocks, start = [], None
    for i, y in enumerate(rows):
        if start is None:
            start = y
        elif y - rows[i - 1] > 3:
            blocks.append((start, rows[i - 1]))
            start = y
    if start is not None:
        blocks.append((start, rows[-1]))
    return mask, [(y0, y1) for y0, y1 in blocks if blue[y0:y1 + 1].sum() < 40]


def _try_amount(im, mask, y0, y1):
    """_amount_from_block that never raises. Every green block on the screen is read now, not
    just the chosen one, and a decoration can crop to a shape the OCR refuses to resize —
    which killed a whole run before this existed. An unreadable block simply has no amount."""
    try:
        return _amount_from_block(im, mask, y0, y1)
    except Exception:  # noqa: BLE001 — a block we cannot read is a block with no number in it
        return None, []


def _amount_from_block(im, mask, y0, y1):
    """The figure printed in a green block → (best guess, [other plausible readings]).
    The '฿' glyph is sometimes read as a digit glued to the number (฿94 → '494', ฿99 → '899').
    Settled by a second reading with the leftmost green glyph painted out: if that reading is
    the first one minus its first digit, the first "digit" was the '฿'."""
    cols = np.where(mask[y0:y1 + 1].sum(axis=0) > 0)[0]
    h = y1 - y0
    x0, ya = max(0, cols[0] - 3 * h), max(0, y0 - h)
    crop = im.crop((x0, ya, min(im.width, cols[-1] + int(1.5 * h)), min(im.height, y1 + h)))
    scale = max(2, int(140 / max(1, h)))

    def read(c):
        """(digits, was the ฿ recognised as a symbol?) — the second half decides whether the
        first digit is real. '฿43' comes back as 'B43': the currency mark was read AS a mark, so
        every digit after it belongs to the fare. Only when it is read as a digit ('494' for ฿94)
        is there a leading digit to remove."""
        txt = _read_text(c.resize((c.width * scale, c.height * scale), Image.LANCZOS))
        m = None
        for m in re.finditer(r'(?<![\d.])(\d{1,4}(?:\.\d{1,2})?)(?![\d])', txt):
            pass
        if not m:
            return None, False
        before = txt[:m.start()].rstrip()
        return m.group(1), before.endswith(("฿", "B", "b"))

    d1, marked = read(crop)
    gap = max(2, h // 8)
    breaks = np.where(np.diff(cols) > gap)[0]
    if len(breaks) and not marked:
        # Only worth a second look when the ฿ did NOT come through as a symbol. It cost 3 trips
        # in one album to learn the difference: '฿43' read as 'B43' had its 4 taken away as if
        # the 4 were the currency mark, leaving ฿3 — and 43 was the fare.
        first_end = cols[breaks[0]]                            # last column of the leftmost glyph
        crop2 = crop.copy()
        crop2.paste((255, 255, 255), (0, 0, first_end - x0 + gap, crop2.height))
        d2, _ = read(crop2)
        if d2 and d1 and len(d1) == len(d2) + 1 and d1.endswith(d2) and d1[0] in "48B":
            return float(d2), []                              # the '฿' had been read as a 4/8
        if d2 and not d1:
            return float(d2), []
    return (float(d1), []) if d1 else (None, [])


def _all_numbers(im):
    """Every number on the screen below the status bar (its clock, '4G', battery % are not
    trip figures — a charging iPhone even paints them green). Returns (sorted set, reading
    order top→bottom) — the order is what lets the fee card be recognised."""
    w = 720
    im = im.crop((0, int(im.height * 0.04), im.width, im.height))
    im2 = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    res, _ = _engine()(np.asarray(im2))
    seq = []
    for box, t, _ in sorted(res or [], key=lambda r: (r[0][0][1], r[0][0][0])):
        seq += [float(x) for x in re.findall(r'(?<![\d.:])(\d{1,4}(?:\.\d{1,2})?)(?![\d:])', t)]
    return sorted(set(seq)), seq


MIN_AMOUNT = 15    # no Grab trip nets less than this; a smaller "amount" is a misread digit


def inspect(source):
    """source: path or bytes. Returns {'role': 'long'|'top'|'bottom', 'amount', 'numbers', ...}."""
    im = Image.open(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source).convert("RGB")
    a = np.asarray(im).astype(int)
    mask, blocks = _green_blocks(a)

    def is_text(y0, y1):
        """A printed figure ('฿ 28', '฿ 413') is always wider than it is tall; the green map
        pin, the status-bar icon and other blobs are square or upright. Skip the blobs."""
        cols = np.where(mask[y0:y1 + 1].sum(axis=0) > 0)[0]
        if len(cols) < 2:
            return False
        width, height = cols[-1] - cols[0] + 1, y1 - y0 + 1
        fill = mask[y0:y1 + 1, cols[0]:cols[-1] + 1].mean()
        return width >= 1.3 * height and fill < 0.6

    # the big 'คุณได้รับ' figure is ≥5.5% of the width tall; the status bar (top 4% of the
    # screen) can hold a green LINE icon glued to a half-hidden line, so it never counts as big
    big = [(y0, y1) for y0, y1 in blocks
           if im.width * 0.055 <= y1 - y0 <= im.width * 0.16 and y0 > im.height * 0.04 and is_text(y0, y1)]
    small = [(y0, y1) for y0, y1 in blocks
             if im.width * 0.015 <= y1 - y0 < im.width * 0.055 and y0 > im.height * 0.04 and is_text(y0, y1)]
    info = {"width": im.width, "height": im.height, "amount": None, "alts": [], "numbers": [], "seq": []}
    if im.width / im.height < 0.36:
        info["role"] = "long"
    elif big:
        # The map carries green of its own — the pick-up pin and the 'เส้นทางที่แนะนำ' legend sit
        # on one row, wide enough to pass for printed text and often TALLER than the ฿ figure
        # underneath. Taking the tallest block therefore picked the map on a whole album of Saver
        # slips: 24 of 26 leftovers read a decoration instead of the fare (฿3352 off one, nothing
        # off the next) and, because the map sits above the 40% line, every one of them was filed
        # as a bottom half with no top to pair with. The fare is the LOWEST green block that reads
        # as money; the map never does. Tallest stays the fallback when none of them read.
        read = {t: _try_amount(im, mask, *t) for t in big}
        priced = [t for t in big if (read[t][0] or 0) >= MIN_AMOUNT]
        y0, y1 = max(priced, key=lambda t: t[1]) if priced else max(big, key=lambda t: t[1] - t[0])
        info["amount"], info["alts"] = read[(y0, y1)]
        if (y0 + y1) / 2 > im.height * 0.4:
            info["role"] = "top"                             # route + map above, amount below
        else:
            # screenshot that STARTS at 'คุณได้รับ' and continues into the fare breakdown:
            # for pairing it plays the bottom (it carries the net and every breakdown number)
            info["role"] = "bottom"
            info["numbers"], info["seq"] = _all_numbers(im)
    else:
        info["role"] = "bottom"
        if small:
            y0, y1 = small[0]                                # topmost small green line = 'รวมรายได้จากรอบขับ'
            info["amount"], info["alts"] = _amount_from_block(im, mask, y0, y1)
        info["numbers"], info["seq"] = _all_numbers(im)
    if info["amount"] is not None and info["amount"] < MIN_AMOUNT:
        # ฿4, ฿8 … are never a fare: the OCR dropped digits (or read the bonus line). Treated
        # as unreadable, so two such misreads can never be glued together as a "฿4 trip".
        info["amount"], info["alts"] = None, []
    return info


# --- vehicle type ---------------------------------------------------------------------------
def vehicle_type(source):
    """('2W'|'4W'|None, 'Saver'|'Standard'|None) from the service chip printed under the map
    on a top half or a long screenshot ('Saver Bike', 'Standard Bike', 'Standard (JustGrab)',
    'Standard | Car only', 'Saver Car'). Latin text, so the free OCR reads it well; a narrow
    long screenshot is tried again bigger when the first pass finds nothing."""
    im = Image.open(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source).convert("RGB")
    for w in (720, 1200):
        txt = _read_text(im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)).lower()
        wheels = "2W" if re.search(r"bike", txt) else ("4W" if re.search(r"car|justgrab|standard|premium", txt) else None)
        tier = "Saver" if re.search(r"saver", txt) else ("Standard" if re.search(r"standard|justgrab", txt) else None)
        if wheels and tier:
            return wheels, tier
    return wheels, tier


def type_from_album(name):
    """Fallback when the chip cannot be read: '2W93 kanjana standard', '4W67bob', '2W=41 std'."""
    n = (name or "").lower()
    wheels = "2W" if re.search(r"2\s*w", n) else ("4W" if re.search(r"4\s*w", n) else None)
    tier = "Saver" if "saver" in n else ("Standard" if re.search(r"std|standard", n) else None)
    return wheels, tier


def category_folder(wheels, tier):
    """The Inbox category folder ingest understands, or None when either half is unknown."""
    if wheels and tier:
        return f"{wheels[0]} W {tier}"
    return None


# --- matching -----------------------------------------------------------------------------
def _fee_card(seq):
    """The 'ค่าบริการที่แกร็บได้รับ' card prints, one under the other: passenger fare a,
    driver income b ('รายได้จากรอบขับ'), Grab's cut a − b (rounded, so ±1). Three consecutive
    figures in reading order that satisfy this name the bottom's income with no Thai needed.
    Returns [(a, b, c)] found."""
    out = []
    for i in range(len(seq) - 2):
        a, b, c = seq[i], seq[i + 1], seq[i + 2]
        if a > b > 0 and 0 < c < b and abs((a - b) - c) <= 1:
            out.append((a, b, c))
    return out


def _extras_ok(base, parts):
    """Bonus / turbo / tip are small next to the base fare. A passenger figure or a toll is not
    an 'extra' — 149 + 199 = 348 must never pair a ฿149 bottom with a ฿348 top."""
    return all(0 < x < base for x in parts) and sum(parts) <= 0.5 * base


def _tier_one(net, green, nums):
    if green is not None:
        if abs(green - net) < 0.01:
            return 0
        extras = [n for n in nums if 0 < n < net - green + 0.01]
        for i, x in enumerate(extras):
            if abs(green + x - net) < 0.01 and _extras_ok(green, [x]):
                return 1
            for y in extras[i + 1:]:
                if abs(green + x + y - net) < 0.01 and _extras_ok(green, [x, y]):
                    return 1
    weak = 2 if green is None else 3
    if net in nums:
        return weak
    ns = sorted((n for n in nums if 0 < n < net), reverse=True)   # largest first = the base
    for i, base in enumerate(ns):
        rest = ns[i + 1:]
        for j, y in enumerate(rest):
            if abs(base + y - net) < 0.01 and _extras_ok(base, [y]):
                return weak
            for z in rest[j + 1:]:
                if abs(base + y + z - net) < 0.01 and _extras_ok(base, [y, z]):
                    return weak
    return None


def match_tier(top, bottom):
    """How strongly a top half and a bottom half agree, or None. Evidence is ranked and the
    strongest kind available DECIDES — weaker kinds are never consulted behind it:
      A. the bottom's own green figure ('คุณได้รับ' / 'รวมรายได้จากรอบขับ') is readable:
         tier 0 if it equals the top's net, tier 1 if net = figure + small extras (bonus /
         turbo / tip printed on the bottom; never a figure of the fee card), else no match
      B. no green figure, but the fee card is legible (passenger fare − income = Grab's cut,
         three consecutive figures): same two tiers against that income
      C. neither: tier 2 when the net appears among the bottom's numbers, or is the largest
         of 2-3 of them plus small extras — weak, so pair_album() lets it win only by distance
    Every plausible reading of either figure (the '฿'-as-digit variants) is tried."""
    nets = [n for n in [top.get("amount")] + list(top.get("alts") or []) if n is not None and n > 0]
    if not nets:
        return None
    nums = bottom.get("numbers") or []
    cards = _fee_card(bottom.get("seq") or [])
    card_figs = {x for card in cards for x in card}
    greens = [g for g in [bottom.get("amount")] + list(bottom.get("alts") or []) if g is not None]
    # A green figure the rest of its own page never repeats is a misreading, not evidence. The
    # round income is printed again inside the fare cards, so a real one always turns up in the
    # numbers; '฿72' read as 372 on a page whose largest number is 72 does not. Letting it stand
    # as the strongest evidence blocked a pair its own page could confirm — and because the
    # strongest kind decides alone, nothing weaker was ever consulted behind it.
    if nums and greens:
        greens = [g for g in greens if any(abs(g - n) <= 1 for n in nums)]
    best = None
    if greens:                                                   # A
        for net in nets:
            for green in greens:
                pool = [n for n in nums if n not in card_figs and 0 < n <= 0.5 * green]
                t = _tier_one(net, green, pool)
                if t in (0, 1) and (best is None or t < best):
                    best = t
        return best
    if cards:                                                    # B
        for net in nets:
            for _a, inc, _c in cards:
                pool = [n for n in nums if n not in card_figs and 0 < n <= 0.5 * inc]
                t = _tier_one(net, inc, pool)
                if t in (0, 1) and (best is None or t < best):
                    best = t
        return best
    for net in nets:                                             # C
        t = _tier_one(net, None, nums)
        if t is not None and (best is None or t < best):
            best = t
    return best


def matches(top, bottom) -> bool:
    return match_tier(top, bottom) is not None


def pair_album(items):
    """items: list of (key, info) in album order. Returns (pairs, leftovers):
    pairs = [(top_key, bottom_key, distance)], leftovers = unpaired half keys.
    Nearest neighbour wins; an exact tie is left unpaired."""
    order = {k: i for i, (k, _) in enumerate(items)}
    info = dict(items)
    tops = [k for k, d in items if d["role"] == "top"]
    bottoms = [k for k, d in items if d["role"] == "bottom"]
    cands = []
    for t in tops:
        for b in bottoms:
            tier = match_tier(info[t], info[b])
            if tier is not None:
                cands.append(((tier, abs(order[t] - order[b])), t, b))
    cands.sort()

    def greedy(ranked):
        pairs, used = [], set()
        for d, t, b in ranked:
            if t in used or b in used:
                continue
            used.update((t, b))
            pairs.append((t, b, d))
        return pairs

    # 1) pairs that are unambiguous (no other candidate at the same distance)
    best_t, best_b = {}, {}
    for d, t, b in cands:                       # d = (tier, distance)
        best_t.setdefault(t, d)
        best_b.setdefault(b, d)
    tie_t = {t for d, t, _ in cands if d == best_t[t]
             and sum(1 for d2, t2, _ in cands if t2 == t and d2 == d) > 1}
    tie_b = {b for d, _, b in cands if d == best_b[b]
             and sum(1 for d2, _, b2 in cands if b2 == b and d2 == d) > 1}
    sure = greedy([c for c in cands if c[1] not in tie_t and c[2] not in tie_b])
    # 2) the album tells its own habit (bottom after the top, or before); use it to break ties.
    #    With nothing to learn from, a tie stays unpaired rather than guessed.
    after = sum(1 for t, b, _ in sure if order[b] > order[t])
    before = len(sure) - after
    if after == before:
        pairs = sure
    else:
        habit = 1 if after > before else -1
        ranked = sorted(cands, key=lambda c: (c[0], 0 if (order[c[2]] - order[c[1]]) * habit > 0 else 1))
        pairs = greedy(ranked)
    pairs = [(t, b, d[1]) for t, b, d in pairs]  # report the file distance, not the rank
    used = {k for t, b, _ in pairs for k in (t, b)}
    leftovers = [k for k in tops + bottoms if k not in used]
    return pairs, leftovers


def stitch(top_img, bottom_img, side_by_side=True, gap=16):
    A, B = (x if isinstance(x, Image.Image) else Image.open(x).convert("RGB") for x in (top_img, bottom_img))
    if side_by_side:
        out = Image.new("RGB", (A.width + gap + B.width, max(A.height, B.height)), "white")
        out.paste(A, (0, 0))
        out.paste(B, (A.width + gap, 0))
    else:
        out = Image.new("RGB", (max(A.width, B.width), A.height + gap + B.height), "white")
        out.paste(A, (0, 0))
        out.paste(B, (0, A.height + gap))
    return out


# --- CLI: dry run on a folder -------------------------------------------------------------
def _natural(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def album_of(name):
    """Which album a picture belongs to. Files now arrive as 'album/photo.jpg' when a training
    set is dropped in as whole album folders, and the folder is the better answer — a name built
    from the full path put a separator in every output file name and the writes all failed."""
    head, _, tail = name.replace("\\", "/").rpartition("/")
    return head or re.sub(r'^LINE_ALBUM_|_\d{6}_\d+\.\w+$', '', tail)


PAIRED_DIR = "1 จับคู่ได้"
LEFT_DIR = "2 จับคู่ไม่ได้"


def why_left(i):
    """Why this half is still on its own, in the words the pool report uses."""
    if i["role"] == "top" and i["amount"] is None:
        return "อ่านยอดไม่ออก"
    return "ไม่มีคู่ที่ยอดตรง"


def _images_under(src):
    """Every picture in the folder and in one level of album folders below it, as paths
    relative to src. A training set arrives as whole LINE albums, not loose files."""
    out = []
    for f in sorted(os.listdir(src), key=_natural):
        p = os.path.join(src, f)
        if os.path.isdir(p):
            out += [os.path.join(f, g) for g in sorted(os.listdir(p), key=_natural)
                    if g.lower().endswith((".jpg", ".jpeg", ".png"))]
        elif f.lower().endswith((".jpg", ".jpeg", ".png")):
            out.append(f)
    return out


def run_folder(src, out=None, log=print):
    files = _images_under(src)
    t0 = time.time()
    info = {f: inspect(os.path.join(src, f)) for f in files}
    pairs, leftovers = [], []
    longs = [f for f in files if info[f]["role"] == "long"]
    for alb in sorted({album_of(f) for f in files}):
        p, l = pair_album([(f, info[f]) for f in files if album_of(f) == alb])
        pairs += p
        leftovers += l
    if out:
        # Two folders, because the two piles are read for different reasons: the first to spot a
        # pair that should never have been made, the second to see what the reader still cannot
        # do. The leftovers carry their role, what was read off them and why they are here, so
        # the folder can be judged without opening anything else.
        import shutil
        paired, left_dir = os.path.join(out, PAIRED_DIR), os.path.join(out, LEFT_DIR)
        os.makedirs(paired, exist_ok=True)
        os.makedirs(left_dir, exist_ok=True)
        for i, (t, b, d) in enumerate(pairs, 1):
            tn, bn = (re.search(r'(\d+)\.\w+$', x).group(1) for x in (t, b))
            gap = f"_ห่าง{d}" if d > 3 else ""          # a pair from opposite ends of the album
            stitch(os.path.join(src, t), os.path.join(src, b)).save(
                os.path.join(paired, f"{i:03d}_{album_of(t)}_฿{info[t]['amount']:g}_{tn}+{bn}{gap}.jpg"),
                quality=88)
        for i, f in enumerate(sorted(leftovers, key=_natural), 1):
            n = info[f]
            amt = f"฿{n['amount']:g}" if n["amount"] is not None else "ไม่มียอด"
            side = {"top": "บน", "bottom": "ล่าง", "long": "ยาว"}.get(n["role"], n["role"])
            base = re.search(r'(\d+)\.\w+$', f).group(1)
            shutil.copy2(os.path.join(src, f),
                         os.path.join(left_dir, f"{i:03d}_{side}_{amt}_{why_left(n)}_{base}.jpg"))
        with open(os.path.join(out, "pairing.json"), "w", encoding="utf-8") as fh:
            json.dump({"pairs": pairs, "leftovers": leftovers, "long": longs, "info": info}, fh, ensure_ascii=False, indent=1)
    halves = len(files) - len(longs)
    log(f"{src}: {len(files)} รูป · รูปยาว {len(longs)} · ครึ่งรูป {halves} → จับคู่ได้ {len(pairs)} คู่ "
        f"({100 * 2 * len(pairs) / max(1, halves):.0f}% ของครึ่งรูป) · เหลือ {len(leftovers)} · {time.time() - t0:.0f} วิ")
    return pairs, leftovers, longs, info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("ใช้: python backend/pairing.py <โฟลเดอร์รูป> [โฟลเดอร์ผลลัพธ์]")
        sys.exit(1)
    run_folder(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1].rstrip("/\\") + " - จับคู่")
