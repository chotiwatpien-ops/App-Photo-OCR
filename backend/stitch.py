# -*- coding: utf-8 -*-
"""Customer-facing images: one JPEG per trip, named '<rider><n>.jpg'.

A trip that came as two screenshots is stitched side by side (top half left, bottom half
right — the layout Operation used to assemble by hand); a single full screenshot is just
re-encoded. Output height is capped so a week's folder stays small.
"""
import io
import re

from PIL import Image

MAX_HEIGHT = 1400
JPEG_QUALITY = 85


def _open(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b)).convert("RGB")


def _fit(im: Image.Image, height: int) -> Image.Image:
    if im.height == height:
        return im
    return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)


def _encode(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def stitch(top: bytes, bottom: bytes = None) -> bytes:
    a = _open(top)
    if bottom is None:
        return _encode(_fit(a, min(a.height, MAX_HEIGHT)))
    b = _open(bottom)
    h = min(max(a.height, b.height), MAX_HEIGHT)
    a, b = _fit(a, h), _fit(b, h)
    gap = 16
    out = Image.new("RGB", (a.width + gap + b.width, h), "white")
    out.paste(a, (0, 0))
    out.paste(b, (a.width + gap, 0))
    return _encode(out)


def customer_name(rider: str, n: int) -> str:
    """'กิตติพงศ์ สินประเสริฐ', 7 -> 'กิตติพงศ์ สินประเสริฐ7.jpg' (spaces kept, unsafe chars dropped)."""
    safe = re.sub(r'[\\/:*?"<>|]+', "", rider).strip()
    return f"{safe}{n}.jpg"
