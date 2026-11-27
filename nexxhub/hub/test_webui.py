import tempfile
import unittest
from pathlib import Path

import webui


class TestWebUI(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        d = Path(self.td.name)
        (d / "shaders").mkdir()
        (d / "shaders" / "00-frequency-hallway.frag").write_text("")
        (d / "shaders" / "20-spectral-ring.frag").write_text("")
        webui.SHADER_DIR = d / "shaders"
        webui.SELECTION = d / "visualizer"

    def test_list(self):
        self.assertEqual(
            webui.shader_files(),
            ["00-frequency-hallway.frag", "20-spectral-ring.frag"],
        )

    def test_friendly(self):
        self.assertEqual(webui.friendly("00-frequency-hallway.frag"),
                         "Frequency Hallway")
        self.assertEqual(webui.friendly("20-spectral-ring.frag"),
                         "Spectral Ring")

    def test_select(self):
        self.assertEqual(webui.current_selection(), "auto")
        self.assertTrue(webui.set_selection("00-frequency-hallway.frag"))
        self.assertEqual(webui.current_selection(), "00-frequency-hallway.frag")
        self.assertFalse(webui.set_selection("nope.frag"))
        self.assertEqual(webui.current_selection(), "00-frequency-hallway.frag")
        self.assertTrue(webui.set_selection("auto"))
        self.assertEqual(webui.current_selection(), "auto")


if __name__ == "__main__":
    unittest.main()
