import tempfile
import unittest
from pathlib import Path

from PIL import Image

from card import palette_from_image, write_palette


class TestPalette(unittest.TestCase):
    def test_red_cover(self):
        a, b = palette_from_image(Image.new("RGB", (32, 32), (220, 30, 40)))
        self.assertEqual(len(a), 3)
        self.assertEqual(len(b), 3)
        self.assertGreater(a[0], 120)
        self.assertGreater(a[0], a[1])
        self.assertGreater(a[0], a[2])

    def test_none(self):
        self.assertIsNone(palette_from_image(None))

    def test_write_palette(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "colors"
            write_palette(p, ((10, 20, 30), (200, 100, 50)))
            vals = [int(x) for x in p.read_text().split()]
            self.assertEqual(vals, [10, 20, 30, 200, 100, 50])
            self.assertEqual(oct(p.stat().st_mode & 0o777), oct(0o644))


if __name__ == "__main__":
    unittest.main()
