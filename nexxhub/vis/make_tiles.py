#!/usr/bin/env python3
"""Render the launcher menu tiles for nexxvis as raw RGBA files (u32 w, u32 h, pixels).

Usage: make_tiles.py <outdir>
Tile order must match nexxhub's MENU list.
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H = 512, 318
WHITE = (255, 255, 255, 255)
SOFT = (190, 205, 230, 255)
ACCENT = (90, 190, 255, 255)


def icon_gamepad(d, cx, cy, s):
    d.rounded_rectangle([cx - s, cy - s * 0.55, cx + s, cy + s * 0.55], radius=s * 0.5, outline=WHITE, width=7)
    d.line([cx - s * 0.62, cy, cx - s * 0.22, cy], fill=WHITE, width=8)
    d.line([cx - s * 0.42, cy - s * 0.2, cx - s * 0.42, cy + s * 0.2], fill=WHITE, width=8)
    for dx, dy in ((0.38, -0.14), (0.58, 0.06), (0.38, 0.22)):
        r = s * 0.08
        d.ellipse([cx + s * dx - r, cy + s * dy - r, cx + s * dx + r, cy + s * dy + r], fill=ACCENT)


def icon_play(d, cx, cy, s):
    d.rounded_rectangle([cx - s, cy - s * 0.62, cx + s, cy + s * 0.62], radius=18, outline=WHITE, width=7)
    d.polygon([(cx - s * 0.25, cy - s * 0.32), (cx - s * 0.25, cy + s * 0.32), (cx + s * 0.35, cy)], fill=ACCENT)


def icon_pixel(d, cx, cy, s):
    # a small pixel-art "joystick + cartridge" glyph
    px = s * 0.16
    pattern = [
        "..XXXX..",
        ".X....X.",
        "X.X..X.X",
        "X......X",
        "X.XXXX.X",
        ".X....X.",
        "..XXXX..",
    ]
    ox, oy = cx - 4 * px, cy - 3.5 * px
    for j, row in enumerate(pattern):
        for i, ch in enumerate(row):
            if ch == "X":
                col = ACCENT if j in (2, 4) else WHITE
                d.rectangle([ox + i * px, oy + j * px, ox + (i + 1) * px - 3, oy + (j + 1) * px - 3], fill=col)


def icon_wave(d, cx, cy, s):
    heights = [0.25, 0.55, 0.9, 0.6, 1.0, 0.45, 0.75, 0.35, 0.2]
    n = len(heights)
    bw = s * 2 / n
    for i, h in enumerate(heights):
        x = cx - s + i * bw
        d.rounded_rectangle([x + 4, cy - s * 0.6 * h, x + bw - 4, cy + s * 0.6 * h], radius=6,
                            fill=ACCENT if i % 2 else WHITE)


TILES = [
    ("PC Games", "Artemis · Apollo", icon_gamepad),
    ("Kodi", "Movies · TV · Music", icon_play),
    ("RetroArch", "Retro consoles", icon_pixel),
    ("Visualizer", "Hide this menu", icon_wave),
]


def save_rgba(img: Image.Image, path: Path) -> None:
    img = img.convert("RGBA")
    with open(path, "wb") as f:
        f.write(struct.pack("<II", img.width, img.height))
        f.write(img.tobytes())


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tiles")
    out.mkdir(parents=True, exist_ok=True)
    fb = ImageFont.truetype(FONT_B, 46)
    fr = ImageFont.truetype(FONT_R, 26)
    for i, (title, sub, icon) in enumerate(TILES):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        icon(d, W / 2, H * 0.36, 70)
        d.text((W / 2, H * 0.70), title, font=fb, fill=WHITE, anchor="mm")
        d.text((W / 2, H * 0.85), sub, font=fr, fill=SOFT, anchor="mm")
        save_rgba(img, out / f"tile{i}.rgba")
    # hint line: [button badge] label ... ; badges are drawn (DejaVu has no circled letters)
    fh = ImageFont.truetype(FONT_R, 28)
    fbadge = ImageFont.truetype(FONT_B, 22)
    parts = [("◀ ▶", None, "choose"), ("A", (16, 124, 16, 255), "open"), ("B", (200, 40, 40, 255), "close"),
             (None, None, "hold Xbox button in an app  →  back here")]
    h, gap, badge = 52, 44, 34
    widths = []
    for key, color, label in parts:
        w = 0
        if key and color:
            w += badge + 12
        elif key:
            w += fh.getlength(key) + 12
        w += fh.getlength(label)
        widths.append(w)
    img = Image.new("RGBA", (int(sum(widths) + gap * (len(parts) - 1) + 40), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 20.0
    for (key, color, label), w in zip(parts, widths):
        cx = x
        if key and color:
            d.ellipse([cx, h / 2 - badge / 2, cx + badge, h / 2 + badge / 2], fill=color)
            d.text((cx + badge / 2, h / 2), key, font=fbadge, fill=WHITE, anchor="mm")
            cx += badge + 12
        elif key:
            d.text((cx, h / 2), key, font=fh, fill=SOFT, anchor="lm")
            cx += fh.getlength(key) + 12
        d.text((cx, h / 2), label, font=fh, fill=SOFT, anchor="lm")
        x += w + gap
    save_rgba(img, out / "hint.rgba")
    print(f"wrote {len(TILES)} tiles + hint to {out}")


if __name__ == "__main__":
    main()
