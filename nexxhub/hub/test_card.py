import io
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from card import CARD_H, CARD_W, render_cdj_card, write_rgba


def _jpeg(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


class TestCard(unittest.TestCase):
    def test_render_without_art(self):
        img = render_cdj_card(1, 174.0, 1.2, True, None)
        self.assertEqual(img.size, (CARD_W, CARD_H))
        self.assertEqual(img.mode, "RGBA")
        self.assertTrue(any(a > 0 for a in img.getchannel("A").getdata()))

    def test_render_with_art(self):
        img = render_cdj_card(2, 128.0, -0.5, False, _jpeg((200, 30, 30)))
        self.assertEqual(img.size, (CARD_W, CARD_H))
        self.assertEqual(img.mode, "RGBA")
        px = img.getpixel((CARD_W // 8, CARD_H // 2))
        self.assertGreater(px[0], 140)
        self.assertLess(px[1], 120)

    def test_write_rgba(self):
        img = render_cdj_card(1, 176.0, 1.14, False, None)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "cdj.rgba"
            write_rgba(out, img)
            data = out.read_bytes()
            w, h = struct.unpack("<II", data[:8])
            self.assertEqual((w, h), (CARD_W, CARD_H))
            self.assertEqual(len(data), 8 + CARD_W * CARD_H * 4)
            self.assertEqual(oct(out.stat().st_mode & 0o777), oct(0o644))


if __name__ == "__main__":
    unittest.main()
