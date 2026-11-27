import unittest
from pathlib import Path

from djl_protocol import (
    HEADER,
    keepalive,
    send_cdj,
    parse_status,
    parse_metadata,
    is_opus_reply,
    translate_deck,
    pitch_percent,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestPackets(unittest.TestCase):
    def test_keepalive_layout(self):
        mac = bytes.fromhex("dca632350646")
        ip = "192.168.1.199"
        p = keepalive(mac, ip)
        self.assertEqual(len(p), 54)
        self.assertEqual(p[:10], HEADER)
        self.assertEqual(p[10:12], b"\x06\x00")
        self.assertEqual(p[12:32].rstrip(b"\0"), b"rekordbox")
        self.assertEqual(p[32:38], bytes([1, 3, 0, 0x36, 0x17, 1]))
        self.assertEqual(p[38:44], mac)
        self.assertEqual(p[44:48], bytes([192, 168, 1, 199]))
        self.assertEqual(p[48:54], bytes([4, 1, 0, 0, 4, 8]))

    def test_send_cdj_layout(self):
        p = send_cdj("nexxxen")
        self.assertEqual(len(p), 10 + 1 + 20 + 10 + 255)
        self.assertEqual(p[10], 0x11)
        self.assertEqual(p[11:31].rstrip(b"\0"), b"rekordbox")
        self.assertEqual(p[31:41], bytes([1, 1, 0x17, 1, 4, 0x17, 1, 0, 0, 0]))
        self.assertEqual(p[41], ord("n"))
        self.assertEqual(p[42], 0)
        self.assertEqual(p[43], ord("e"))


class TestStatus(unittest.TestCase):
    def test_status_fixture(self):
        b = bytes.fromhex((FIXTURES / "status9.hex").read_text())
        s = parse_status(b, 100.0)
        self.assertEqual(len(b), 293)
        self.assertEqual(s.deck, 9)
        self.assertEqual(s.deck_display, 1)
        self.assertEqual(s.bpm_raw, 17400)
        self.assertEqual(s.pitch_raw, 0x102EB2)
        self.assertAlmostEqual(s.bpm_eff, 175.98, delta=0.02)
        self.assertAlmostEqual(pitch_percent(s.pitch_raw), 1.1400, delta=0.0001)
        self.assertTrue(s.playing and s.master and s.on_air)
        self.assertFalse(s.synced)
        self.assertEqual(s.beat_counter, 560)
        self.assertEqual(s.track_id, 1217)
        self.assertEqual(s.firmware, "1.30")
        self.assertEqual(s.t_recv, 100.0)

    def test_status_rejects_short(self):
        self.assertIsNone(parse_status(b"\x00" * 100, 0.0))

    def test_status_rejects_wrong_type(self):
        b = bytearray(bytes.fromhex((FIXTURES / "status9.hex").read_text()))
        b[10] = 0x99
        self.assertIsNone(parse_status(bytes(b), 0.0))

    def test_deck_display_for_other_decks(self):
        b = bytes.fromhex((FIXTURES / "status10.hex").read_text())
        s = parse_status(b, 0.0)
        self.assertEqual(s.deck, 10)
        self.assertEqual(s.deck_display, 2)


class TestMetadata(unittest.TestCase):
    def test_metadata_fixture(self):
        b = bytes.fromhex((FIXTURES / "art_meta.hex").read_text())
        m = parse_metadata(b)
        self.assertEqual(m.deck, 10)
        self.assertEqual(m.subtype, 2)
        self.assertEqual(m.track_id, 1230)
        self.assertEqual(m.index, 0)
        self.assertEqual(m.count, 6)
        self.assertEqual(len(m.payload), 512 - 0x34)

    def test_metadata_rejects_wrong_type(self):
        b = bytearray(bytes.fromhex((FIXTURES / "art_meta.hex").read_text()))
        b[10] = 0x0A
        self.assertIsNone(parse_metadata(bytes(b)))

    def test_metadata_rejects_short(self):
        self.assertIsNone(parse_metadata(b"\x00" * 0x20))


class TestHelpers(unittest.TestCase):
    def test_translate_deck(self):
        self.assertEqual(translate_deck(9), 1)
        self.assertEqual(translate_deck(12), 4)
        self.assertEqual(translate_deck(0), 0)
        self.assertEqual(translate_deck(8), 0)
        self.assertEqual(translate_deck(13), 0)

    def test_pitch(self):
        self.assertAlmostEqual(pitch_percent(0x100000), 0.0)
        self.assertAlmostEqual(pitch_percent(0x102EB2), 1.1400, delta=0.0001)

    def test_opus_reply(self):
        p = HEADER + b"\x10" + b"OPUS-QUAD".ljust(20, b"\0") + bytes([1, 0, 9, 0, 0])
        self.assertTrue(is_opus_reply(p))
        self.assertFalse(is_opus_reply(p[:10]))
        self.assertFalse(is_opus_reply(HEADER + b"\x06" + b"OPUS-QUAD".ljust(20, b"\0") + bytes([1, 0, 9, 0, 0])))


if __name__ == "__main__":
    unittest.main()
