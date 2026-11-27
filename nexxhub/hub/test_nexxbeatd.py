import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import nexxbeatd as nb
from beatclock import BeatClock
from djl_protocol import HEADER, Metadata, Status, parse_status

T = 0.341


def status(deck, playing=False, master=False, on_air=False, bpm=174.0, track=1,
           counter=0, t=0.0):
    return Status(
        deck=deck, deck_display=deck - 8, bpm_raw=int(round(bpm * 100)),
        pitch_raw=0x100000, bpm_eff=bpm, playing=playing, master=master,
        on_air=on_air, synced=False, beat_counter=counter, track_id=track,
        firmware="1.30", t_recv=t,
    )


def deck_state(deck, playing=False, master=False, on_air=False, last_playing_t=None,
               last_t=100.0):
    return SimpleNamespace(
        deck=deck,
        status=status(deck, playing=playing, master=master, on_air=on_air),
        last_playing_t=last_playing_t,
        last_t=last_t,
    )


def meta(deck, track, index, count, payload, subtype=2):
    return Metadata(deck=deck, subtype=subtype, track_id=track, index=index,
                    count=count, payload=payload)


class FakeCard:
    def __init__(self):
        self.updates = []
        self.heartbeats = 0
        self.removed = 0

    def update(self, deck_display, status, art_jpeg):
        self.updates.append((deck_display, status.track_id, art_jpeg))

    def heartbeat(self, t=None):
        self.heartbeats += 1

    def remove(self):
        self.removed += 1


class DaemonCase(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.sent = []
        self.d = nb.BeatDaemon(
            run_dir=Path(self.td.name),
            announce_port=0, status_port=0, broadcast_addr="127.0.0.1",
            sender=lambda payload, addr: self.sent.append((payload, addr)),
            log=lambda m: None,
        )


class TestSelection(unittest.TestCase):
    def test_select_master(self):
        now = 100.0
        states = {
            9: deck_state(9, playing=True, master=True, last_playing_t=now),
            10: deck_state(10, playing=True, on_air=True, last_playing_t=now),
        }
        self.assertEqual(nb.select_deck(states, now), 9)

    def test_select_on_air_fallback(self):
        now = 100.0
        states = {
            10: deck_state(10, playing=True, on_air=True, last_playing_t=now),
            11: deck_state(11, playing=True, last_playing_t=now),
        }
        self.assertEqual(nb.select_deck(states, now), 10)

    def test_select_skips_stale_master(self):
        now = 100.0
        states = {
            9: deck_state(9, playing=True, master=True, last_playing_t=now, last_t=now - 2.0),
            10: deck_state(10, playing=True, last_playing_t=now, last_t=now),
        }
        self.assertEqual(nb.select_deck(states, now), 10)

    def test_select_hold(self):
        now = 100.0
        states = {9: deck_state(9, playing=False, last_playing_t=now - 2.0)}
        self.assertEqual(nb.select_deck(states, now), 9)
        states[9].last_playing_t = now - 6.0
        self.assertIsNone(nb.select_deck(states, now))

    def test_select_most_recent_while_playing(self):
        now = 100.0
        states = {
            10: deck_state(10, playing=True, last_playing_t=now - 3.0),
            11: deck_state(11, playing=True, last_playing_t=now - 1.0),
        }
        self.assertEqual(nb.select_deck(states, now), 11)


class TestStateLine(DaemonCase):
    def test_idle_line(self):
        line = self.d.state_line(123.456)
        fields = line.split()
        self.assertEqual(len(fields), 8)
        self.assertEqual(fields[:6], ["0", "0", "0", "0", "0", "0"])
        self.assertAlmostEqual(float(fields[6]), 123.456, places=3)
        self.assertEqual(fields[7], "0")

    def test_state_playing(self):
        for k in range(1, 8):
            self.d.handle_status(status(9, playing=True, counter=100 + k), k * T)
        now = 8 * T
        fields = self.d.state_line(now).split()
        self.assertEqual(fields[0], "2")
        self.assertEqual(fields[1], "1")
        self.assertAlmostEqual(float(fields[2]), 174.0, places=2)
        self.assertGreater(float(fields[4]), 0.3)
        self.assertEqual(fields[5], "1")
        self.assertEqual(fields[7], "1")

    def test_state_pause(self):
        for k in range(1, 8):
            self.d.handle_status(status(9, playing=True, counter=100 + k), k * T)
        self.d.handle_status(status(9, playing=False, counter=107, master=True), 8 * T)
        fields = self.d.state_line(8 * T).split()
        self.assertEqual(fields[0], "2")
        self.assertEqual(fields[5], "0")
        self.assertEqual(fields[4], "0.00")

    def test_hold_keeps_deck_but_not_playing(self):
        for k in range(1, 5):
            self.d.handle_status(status(9, playing=True, counter=100 + k), k * T)
        self.d.handle_status(status(9, playing=False, counter=104), 4 * T)
        fields = self.d.state_line(5 * T).split()
        self.assertEqual(fields[1], "1")   # deck still selected
        self.assertEqual(fields[5], "0")   # but not playing

    def test_stale_status_goes_idle(self):
        for k in range(1, 5):
            self.d.handle_status(status(9, playing=True, counter=100 + k), k * T)
        self.assertEqual(self.d.state_line(4 * T).split()[0], "2")
        self.assertEqual(self.d.state_line(4 * T + 2.0).split()[0], "0")

    def test_idle_after_hold(self):
        self.d.handle_status(status(9, playing=False), 0.0)
        self.d.handle_status(status(9, playing=True, counter=1), 0.1)
        self.d.handle_status(status(9, playing=False, counter=1), 1.0)
        fields = self.d.state_line(7.0).split()
        self.assertEqual(fields[0], "0")
        self.assertEqual(fields[1], "0")


class TestStateFile(DaemonCase):
    def test_atomic_state(self):
        path = Path(self.td.name) / "beat"
        stop = threading.Event()
        bad = []

        def reader():
            while not stop.is_set():
                try:
                    data = path.read_text()
                except FileNotFoundError:
                    continue
                if len(data.split()) != 8:
                    bad.append(data)

        th = threading.Thread(target=reader)
        th.start()
        for i in range(100):
            nb.write_state_file(
                path, nb.format_state(2, 1, 174.0, 0.5, 0.9, 1, float(i), 1217)
            )
        stop.set()
        th.join()
        self.assertEqual(bad, [])
        self.assertEqual(len(path.read_text().split()), 8)

    def test_write_state_creates_dir_and_file(self):
        self.d.handle_status(status(9, playing=True, counter=1), 0.1)
        self.d.write_state(0.2)
        p = Path(self.td.name) / "beat"
        self.assertTrue(p.exists())
        self.assertEqual(len(p.read_text().split()), 8)

    def test_write_state_creates_missing_run_dir(self):
        run = Path(self.td.name) / "nested" / "run"
        d = nb.BeatDaemon(
            run_dir=run, announce_port=0, status_port=0,
            sender=lambda p, a: None, log=lambda m: None,
        )
        d.write_state(0.0)
        self.assertTrue((run / "beat").exists())
        self.assertEqual(oct(run.stat().st_mode & 0o777), oct(0o755))


class TestProtocol(DaemonCase):
    def test_pitch_and_bpm(self):
        b = bytes.fromhex(
            (Path(__file__).parent / "fixtures" / "status9.hex").read_text()
        )
        s = parse_status(b, 0.0)
        self.d.handle_status(s, 0.0)
        self.assertAlmostEqual(self.d.decks[9].status.bpm_eff, 175.98, delta=0.02)

    def test_opus_ip_learned(self):
        pkt = HEADER + b"\x10" + b"OPUS-QUAD".ljust(20, b"\0") + bytes([1, 0, 9, 0, 0])
        self.d.handle_datagram(pkt, "10.0.0.5", 0.0)
        self.assertEqual(self.d.unit_ip, "10.0.0.5")
        self.sent.clear()
        self.d.send_handshake(1.0)
        self.assertEqual(self.sent[-1][1], ("10.0.0.5", 50002))
        self.assertEqual(len(self.sent[-1][0]), 296)
        self.d.handle_datagram(pkt, "10.0.0.6", 2.0)
        self.assertEqual(self.d.unit_ip, "10.0.0.6")

    def test_handshake_send_failure_is_survived(self):
        def boom(payload, addr):
            raise OSError("network unreachable")
        d = nb.BeatDaemon(
            run_dir=Path(self.td.name), announce_port=0, status_port=0,
            sender=boom, log=lambda m: None,
        )
        pkt = HEADER + b"\x10" + b"OPUS-QUAD".ljust(20, b"\0") + bytes([1, 0, 9, 0, 0])
        d.handle_datagram(pkt, "10.0.0.5", 0.0)
        self.assertEqual(d.unit_ip, "10.0.0.5")
        d.send_handshake(3.0)   # must not raise

    def test_malformed_ignored(self):
        self.d.handle_datagram(b"\x00" * 20, "10.0.0.5", 0.0)
        self.assertEqual(self.d.decks, {})
        self.assertIsNone(self.d.unit_ip)

    def test_track_change_resets_clock(self):
        for k in range(1, 6):
            self.d.handle_status(status(9, playing=True, counter=100 + k, track=1), k * T)
        clock = self.d.decks[9].clock
        self.d.handle_status(status(9, playing=True, counter=3, track=2), 6 * T)
        self.assertIsNone(clock.next_beat(6 * T))


class TestArtCache(unittest.TestCase):
    def test_art_reassembly(self):
        c = nb.ArtCache()
        for i, p in enumerate((b"a", b"b", b"c")):
            c.add(meta(9, 1217, i, 3, p), 0.0)
        self.assertEqual(c.get(9, 1217), b"abc")
        incomplete = nb.ArtCache()
        incomplete.add(meta(9, 1217, 0, 2, b"a"), 0.0)
        self.assertIsNone(incomplete.get(9, 1217))

    def test_art_per_deck(self):
        c = nb.ArtCache()
        c.add(meta(9, 1217, 0, 1, b"A"), 0.0)
        c.add(meta(10, 413, 0, 1, b"B"), 0.1)
        self.assertEqual(c.get(9, 1217), b"A")
        self.assertEqual(c.get(10, 413), b"B")

    def test_art_new_track_discards(self):
        c = nb.ArtCache()
        c.add(meta(9, 1217, 0, 3, b"a"), 0.0)
        c.add(meta(9, 999, 0, 1, b"Z"), 1.0)
        self.assertIsNone(c.get(9, 1217))
        self.assertEqual(c.get(9, 999), b"Z")

    def test_art_prune_after_10s(self):
        c = nb.ArtCache()
        c.add(meta(9, 1217, 0, 3, b"a"), 0.0)
        c.prune(10.5)
        c.add(meta(9, 1217, 1, 3, b"b"), 10.6)
        c.add(meta(9, 1217, 2, 3, b"c"), 10.7)
        self.assertIsNone(c.get(9, 1217))  # chunk 0 was pruned

    def test_art_new_track_keeps_other_deck(self):
        c = nb.ArtCache()
        c.add(meta(9, 1217, 0, 1, b"A"), 0.0)
        c.add(meta(10, 413, 0, 1, b"B"), 0.1)
        c.add(meta(11, 500, 0, 1, b"C"), 0.2)
        c.add(meta(12, 600, 0, 1, b"D"), 0.3)
        c.add(meta(10, 999, 0, 1, b"Z"), 0.4)   # deck 10 loads a new track
        self.assertEqual(c.get(9, 1217), b"A")
        self.assertEqual(c.get(10, 999), b"Z")

    def test_discard_deck_keeps_new_track(self):
        c = nb.ArtCache()
        c.add(meta(9, 1217, 0, 2, b"a"), 0.0)
        c.add(meta(9, 999, 0, 1, b"Z"), 1.0)
        c.discard_deck(9, keep_track=999)
        self.assertIsNone(c.get(9, 1217))
        self.assertEqual(c.get(9, 999), b"Z")


class TestCardPublisher(unittest.TestCase):
    def test_card_heartbeat(self):
        with tempfile.TemporaryDirectory() as td:
            p = nb.CardPublisher(Path(td))
            p.update(1, status(9, playing=True, bpm=174.0), None)
            path = Path(td) / "cdj.rgba"
            self.assertTrue(path.exists())
            past = time.time() - 10.0
            os.utime(path, (past, past))
            p.heartbeat(time.time())
            self.assertLess(time.time() - path.stat().st_mtime, 2.0)

    def test_card_removed(self):
        with tempfile.TemporaryDirectory() as td:
            p = nb.CardPublisher(Path(td))
            p.update(1, status(9, playing=True, bpm=174.0), None)
            path = Path(td) / "cdj.rgba"
            self.assertTrue(path.exists())
            p.remove()
            self.assertFalse(path.exists())
            p.remove()  # harmless

    def test_card_update_dedupes(self):
        with tempfile.TemporaryDirectory() as td:
            p = nb.CardPublisher(Path(td))
            st = status(9, playing=True, bpm=174.0)
            p.update(1, st, None)
            path = Path(td) / "cdj.rgba"
            mtime = path.stat().st_mtime_ns
            p.update(1, st, None)
            self.assertEqual(path.stat().st_mtime_ns, mtime)


class TestCardSelection(DaemonCase):
    def test_card_uses_selected_art(self):
        fake = FakeCard()
        self.d.card = fake
        for i, p in enumerate((b"a", b"b")):
            self.d.handle_metadata(meta(9, 1217, i, 2, p), 0.0)
        for i, p in enumerate((b"x", b"y")):
            self.d.handle_metadata(meta(10, 413, i, 2, p), 1.0)
        self.d.handle_status(status(9, playing=True, master=True, counter=1, track=1217), 2.0)
        self.d.handle_status(status(10, playing=True, on_air=True, counter=1, track=413), 2.1)
        self.d.update_card(2.2)
        self.assertTrue(fake.updates)
        deck, track, art = fake.updates[-1]
        self.assertEqual((deck, track, art), (1, 1217, b"ab"))

    def test_card_heartbeat_while_playing(self):
        fake = FakeCard()
        self.d.card = fake
        self.d.handle_status(status(9, playing=True, counter=1), 0.0)
        self.d.update_card(0.1)
        self.d.update_card(0.2)
        self.assertGreaterEqual(fake.heartbeats, 2)

    def test_card_removed_after_idle(self):
        fake = FakeCard()
        self.d.card = fake
        self.d.update_card(0.0)      # nothing selected
        self.d.update_card(5.5)      # >5 s idle
        self.assertGreaterEqual(fake.removed, 1)


class TestFormat(unittest.TestCase):
    def test_format_state(self):
        line = nb.format_state(2, 1, 176.07, 0.43123, 0.94, True, 123456.7894, 1217)
        self.assertEqual(line, "2 1 176.07 0.4312 0.94 1 123456.789 1217\n")

    def test_format_idle(self):
        self.assertEqual(
            nb.format_state(0, 0, 0.0, 0.0, 0.0, False, 1.0, 0),
            "0 0 0.00 0.0000 0.00 0 1.000 0\n",
        )


if __name__ == "__main__":
    unittest.main()
