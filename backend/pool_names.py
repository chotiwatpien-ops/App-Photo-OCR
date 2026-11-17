# -*- coding: utf-8 -*-
"""How the pool names what it stitches, without the OCR stack pool.py imports.

The web app reads these names back (accounting.py) and does not install numpy or the OCR, so the
naming lives here and pool.py imports it."""
import re


def half_tag(file_name):
    """What to call one half in the stitched picture's name.

    The trailing number of 'LINE_ALBUM_x_260907_57.jpg' is what tells two halves apart at a
    glance, and it is what every audit since run 7 reads to measure how far apart a pair was.
    But not every picture has one: LINE also delivers files named as a bare UUID, and asking an
    'ends in digits' pattern for its group() raised AttributeError and lost seven real pairs —
    while others quietly took whatever digits happened to sit at the end of the UUID, so a pair
    came out named '5567+4'. Fall back to the first characters of the name: stable, unique
    enough inside one album, and obviously not a sequence number."""
    stem = re.sub(r"\.\w+$", "", str(file_name or ""))
    # Another exporter names its files '74232_0.jpg', 'S__76906624_0.jpg' — a long number and a
    # one-digit copy index. The trailing number there is the index, '0' for every file in the
    # album, so every pair with the same fare in one rider folder got the same name — and
    # upload_file overwrites a same-named file. Run #138 handed อิทธพล 21 trips and left 19
    # pictures: two pairs were written over by later ones with the same ฿. The number before
    # the index is the identity.
    m = re.match(r"^(?:S__)?(\d{4,})_\d$", stem)
    if m:
        return m.group(1)
    m = re.search(r"(\d+)$", stem)
    return m.group(1) if m else (re.sub(r"[^0-9A-Za-z]+", "", stem)[:8] or "x")
