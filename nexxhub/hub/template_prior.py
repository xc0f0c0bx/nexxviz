"""Extract a structural/colour prior from the crop-circle reference images.

Reads a directory of crops (JPEG/PNG/WebP), downsamples each image and
measures the qualities the shader cares about: edge density (how busy the
formation is), radial/horizontal symmetry, contrast, saturation and value.
It also records a dark and a light representative colour.  The aggregate is
written as JSON; evolve.py maps it onto its eight genes and biases the
population toward it.

Run on the Pi (python3-pil):
    python3 template_prior.py /path/to/images_template \
        /var/lib/nexxhub/template-prior.json
"""
from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

from PIL import Image

SIZE = 96
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def image_stats(path: Path) -> dict | None:
    try:
        im = Image.open(path).convert("RGB").resize((SIZE, SIZE))
    except Exception:
        return None
    px = list(im.getdata())
    n = len(px)
    if not n:
        return None
    sat = val = 0.0
    lum = []
    for r, g, b in px:
        _, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        sat += s
        val += v
        lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    sat /= n
    val /= n

    w = h = SIZE
    edges = 0
    tot = 0
    for y in range(h - 1):
        row = y * w
        nrow = row + w
        for x in range(w - 1):
            dx = abs(lum[row + x] - lum[row + x + 1])
            dy = abs(lum[row + x] - lum[nrow + x])
            if dx + dy > 18.0:
                edges += 1
            tot += 1
    edge = edges / max(tot, 1)

    diff = 0.0
    cnt = 0
    for y in range(h):
        row = y * w
        for x in range(w // 2):
            diff += abs(lum[row + x] - lum[row + w - 1 - x])
            cnt += 1
    sym = max(0.0, 1.0 - (diff / max(cnt, 1)) / 128.0)

    mean = sum(lum) / n
    var = sum((v - mean) ** 2 for v in lum) / n
    contrast = min(1.0, (var ** 0.5) / 64.0)

    dark = (0.1, 0.08, 0.04)
    light = (0.9, 0.85, 0.65)
    try:
        q = im.quantize(colors=6, method=Image.MEDIANCUT).convert("RGB")
        colors = q.getcolors(SIZE * SIZE) or []
        colors.sort(reverse=True)
        pal = [c for _, c in colors[:6]]
        pal.sort(key=lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])
        if pal:
            dark = tuple(pal[0])
            light = tuple(pal[-1])
    except Exception:
        pass

    def norm(c):
        return [round(x / 255.0, 3) for x in c]

    return {"edge_density": edge, "symmetry": sym, "contrast": contrast,
            "saturation": sat, "value": val,
            "dark": norm(dark), "light": norm(light)}


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: template_prior.py IMAGES_DIR OUT_JSON", file=sys.stderr)
        return 2
    src, out = Path(argv[1]), Path(argv[2])
    stats = [s for p in sorted(src.iterdir()) if p.suffix.lower() in EXTS
             for s in [image_stats(p)] if s]
    if not stats:
        print("no readable images", file=sys.stderr)
        return 1
    keys = ("edge_density", "symmetry", "contrast", "saturation", "value")
    agg = {k: round(sum(s[k] for s in stats) / len(stats), 4) for k in keys}
    agg["count"] = len(stats)
    for name in ("dark", "light"):
        agg[f"palette_{name}"] = [round(sum(s[name][i] for s in stats) / len(stats), 3)
                                  for i in range(3)]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(agg, indent=2) + "\n")
    tmp.chmod(0o644)
    tmp.replace(out)
    print(json.dumps(agg))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
