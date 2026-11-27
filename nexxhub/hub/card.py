"""CDJ card renderer for the nexxvis visualizer.

Renders the selected Pro DJ Link deck (deck number, effective BPM, pitch,
MASTER badge and album art) into the same raw-RGBA format as
``nowplaying.py``: u32 width, u32 height, then RGBA pixels, drawn for a
2560-px-wide screen.  No title/artist: the OPUS-QUAD does not serve them.
"""

from __future__ import annotations

import colorsys
import io
import math
import os
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

CARD_W, CARD_H = 1180, 300
COVER = 240
PAD = 30


_FONT_CACHE: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}
_SHADOW_CACHE: Image.Image | None = None


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    font = _FONT_CACHE.get(key)
    if font is not None:
        return font
    try:
        font = ImageFont.truetype(FONT_B if bold else FONT_R, size)
    except OSError:
        # Macs and stripped-down images: Pillow's bundled font, same size
        # (load_default gained a size argument in Pillow 10.1).
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _shadow() -> Image.Image:
    """The blurred panel shadow is identical on every card; build it once."""
    global _SHADOW_CACHE
    if _SHADOW_CACHE is None:
        shadow = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [12, 12, CARD_W - 12, CARD_H - 12], radius=34, fill=(0, 0, 0, 150)
        )
        _SHADOW_CACHE = shadow.filter(ImageFilter.GaussianBlur(10))
    return _SHADOW_CACHE


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _art_tile(card: Image.Image, draw: ImageDraw.ImageDraw, art_jpeg: bytes | None) -> None:
    x, cy = PAD, (CARD_H - COVER) // 2
    if art_jpeg:
        try:
            art = Image.open(io.BytesIO(art_jpeg)).convert("RGB")
            art = art.resize((COVER, COVER), Image.LANCZOS)
            mask = Image.new("L", (COVER, COVER), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, COVER - 1, COVER - 1], radius=22, fill=255
            )
            card.paste(art, (x, cy), mask)
            return
        except Exception:
            pass  # truncated/invalid chunks: fall through to the glyph
    draw.rounded_rectangle([x, cy, x + COVER, cy + COVER], radius=22, fill=(40, 48, 70, 255))
    draw.text(
        (x + COVER / 2, cy + COVER / 2),
        "♪",
        font=_font(120, bold=True),
        fill=(150, 200, 255, 255),
        anchor="mm",
    )


def render_cdj_card(
    deck_display: int,
    bpm: float,
    pitch_pct: float,
    master: bool,
    art_jpeg: bytes | None,
) -> Image.Image:
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.alpha_composite(_shadow())
    d = ImageDraw.Draw(card)
    d.rounded_rectangle(
        [12, 12, CARD_W - 12, CARD_H - 12],
        radius=34,
        fill=(10, 12, 20, 165),
        outline=(255, 255, 255, 28),
        width=2,
    )

    _art_tile(card, d, art_jpeg)

    tx = PAD + COVER + 36
    tw = CARD_W - tx - PAD - 10
    f_tag = _font(24, bold=True)
    f_bpm = _font(92, bold=True)
    f_unit = _font(30, bold=True)
    f_pitch = _font(34)

    tag = f"PRO DJ LINK · DECK {deck_display}"
    d.text((tx, 46), _fit(d, tag, f_tag, tw), font=f_tag, fill=(90, 190, 255, 255))

    if master:
        f_m = _font(20, bold=True)
        label = "MASTER"
        mw = d.textlength(label, font=f_m)
        bx0 = CARD_W - PAD - mw - 34
        d.rounded_rectangle([bx0, 44, CARD_W - PAD, 82], radius=12, fill=(255, 150, 40, 235))
        d.text((bx0 + 17, 63), label, font=f_m, fill=(20, 12, 4, 255), anchor="lm")

    bpm_text = f"{bpm:.1f}"
    d.text((tx, 84), bpm_text, font=f_bpm, fill=(255, 255, 255, 255))
    bpm_w = d.textlength(bpm_text, font=f_bpm)
    d.text((tx + bpm_w + 14, 132), "BPM", font=f_unit, fill=(150, 165, 195, 255))

    pitch = f"{pitch_pct:+.1f} %"
    d.text((tx, 196), pitch, font=f_pitch, fill=(215, 225, 245, 255))

    # beat dot (the shader does the real pulsing; this is a static accent)
    cx, cy = CARD_W - PAD - 46, CARD_H - 68
    d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=(90, 200, 255, 220))
    d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(235, 245, 255, 255))

    return card


def palette_from_image(img: Image.Image | None):
    """Two vivid colours (bar, peak) from an album cover, or None."""
    if img is None:
        return None
    small = img.convert("RGB").resize((32, 32), Image.BILINEAR)
    scored = []
    for r, g, b in list(small.getdata()):
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        scored.append((s * v, h, s, v))
    scored.sort(reverse=True)
    top = scored[:max(8, len(scored) // 8)]
    sx = sum(math.sin(2.0 * math.pi * h) for _, h, _, _ in top)
    cx = sum(math.cos(2.0 * math.pi * h) for _, h, _, _ in top)
    hue = (math.atan2(sx, cx) / (2.0 * math.pi)) % 1.0
    sat = max(0.65, sum(s for _, _, s, _ in top) / len(top))
    val = max(0.62, sum(v for _, _, _, v in top) / len(top))
    a = colorsys.hsv_to_rgb(hue, sat, val)
    b = colorsys.hsv_to_rgb((hue + 0.45) % 1.0, min(1.0, sat + 0.20),
                            min(1.0, val + 0.15))
    return (tuple(int(round(x * 255)) for x in a),
            tuple(int(round(x * 255)) for x in b))


def palette_from_jpeg(data: bytes | None):
    if not data:
        return None
    try:
        return palette_from_image(Image.open(io.BytesIO(data)))
    except Exception:
        return None


def write_palette(path: Path, colors) -> None:
    """Write six 0..255 values (bar RGB, peak RGB) atomically."""
    a, b = colors
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        f.write(f"{a[0]} {a[1]} {a[2]} {b[0]} {b[1]} {b[2]}\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def write_rgba(path: Path, img: Image.Image) -> None:
    """Write the u32 width/height + RGBA payload (atomic replace is the caller's)."""
    with open(path, "wb") as f:
        f.write(struct.pack("<II", img.width, img.height))
        f.write(img.tobytes())
    path.chmod(0o644)
