"""Now-playing card for the nexxvis visualizer.

Polls HiFiBerry AudioControl (/api/now-playing, which aggregates the MPRIS players: Spotify, AirPlay,
MPD, Bluetooth, ...) and renders title / artist / album (+ cover art when the player provides one)
into a raw RGBA file the visualizer shows bottom-left. The file is removed when nothing is playing,
which makes the visualizer fade the card out.

Card is drawn for a 2560-px-wide screen; nexxvis scales it to the actual mode.
"""
from __future__ import annotations

import io
import json
import os
import struct
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from card import palette_from_image, write_palette

API = "http://127.0.0.1:1080"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

CARD_W, CARD_H = 1180, 300
COVER = 240
PAD = 30


def _get_json(url: str, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


_mpris_cache: tuple[float, str, str] = (0.0, "", "")


def mpris_metadata() -> tuple[str, str]:
    """(cover art URL, mpris:trackid) from MPRIS, or ("", "")."""
    global _mpris_cache
    now = time.monotonic()
    if now - _mpris_cache[0] < 5.0:
        return _mpris_cache[1], _mpris_cache[2]
    art = ""
    track = ""
    for user in (False, True):
        base = ["busctl"] + (["--user"] if user else [])
        try:
            out = subprocess.run(base + ["list", "--no-legend"],
                                 capture_output=True, text=True, timeout=2)
            names = [ln.split()[0] for ln in out.stdout.splitlines()
                     if "org.mpris.MediaPlayer2." in ln]
        except Exception:
            names = []
        for name in names:
            try:
                r = subprocess.run(
                    base + ["--json=short", "get-property", name,
                            "/org/mpris/MediaPlayer2",
                            "org.mpris.MediaPlayer2.Player", "Metadata"],
                    capture_output=True, text=True, timeout=2)
                data = json.loads(r.stdout).get("data", {})
                a = data.get("mpris:artUrl", {}).get("data", "")
                t = data.get("mpris:trackid", {}).get("data", "")
                if isinstance(a, str) and a not in ("", "file://(null)", "(null)"):
                    art = a
                if isinstance(t, str):
                    track = t
                if art or track:
                    break
            except Exception:
                continue
        if art or track:
            break
    _mpris_cache = (now, art, track)
    return art, track


def mpris_art_url() -> str:
    return mpris_metadata()[0]


_soloist_cache: tuple[float, tuple[str, str, str] | None] = (0.0, None)


def soloist_current():
    """(title, artist, uri) of the current Spotify Soloist track, or None.

    AudioControl keeps shairport as the active player even while Soloist is
    playing, so the queue endpoint is the reliable per-player source.
    """
    global _soloist_cache
    now = time.monotonic()
    if now - _soloist_cache[0] < 2.0:
        return _soloist_cache[1]
    cur = None
    try:
        players = _get_json(f"{API}/api/players")
        playing = any(p.get("id") == "soloist" and p.get("state") == "playing"
                      for p in players.get("players", []))
        if playing:
            d = _get_json(f"{API}/api/player/soloist/queue")
            q = d.get("queue") or []
            if q and q[0].get("uri"):
                cur = (q[0].get("name") or "", q[0].get("artist") or "",
                       q[0].get("uri") or "")
    except Exception:
        cur = None
    _soloist_cache = (now, cur)
    return cur


def write_track_key(path: Path, key: str) -> None:
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        f.write(key.replace("\n", " ").replace("\r", " ") + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


class NowPlaying(threading.Thread):
    def __init__(self, out: Path, log, interval: float = 2.0):
        super().__init__(daemon=True, name="nowplaying")
        self.out = out
        self.log = log
        self.interval = interval
        self.key = ("<unset>",)      # what is currently rendered; sentinel forces the first write/removal
        self.cover_cache: dict[str, Image.Image | None] = {}
        self.fb = ImageFont.truetype(FONT_B, 58)
        self.fa = ImageFont.truetype(FONT_R, 44)
        self.fl = ImageFont.truetype(FONT_R, 34)
        self.fs = ImageFont.truetype(FONT_B, 24)
        self.errors = 0
        self.palette_out = Path(os.environ.get("NP_PALETTE", "/run/nexxhub/cover.colors"))
        self.track_key_path = Path(os.environ.get("NP_TRACK_KEY", "/run/nexxhub/trackkey"))
        self.track_key = "<unset>"

    # ------------------------------------------------------------- data
    def fetch(self) -> tuple | None:
        d = _get_json(f"{API}/api/now-playing")
        song = d.get("song") or {}
        state = str(d.get("state") or "").lower()
        title = (song.get("title") or "").strip()
        if not title or state not in ("playing", "paused"):
            return None
        player = (d.get("player") or {}).get("name") or ""
        cover = song.get("cover_art_url") or ""
        if not cover or cover in ("file://(null)", "(null)"):
            cover = mpris_art_url() or ""
        return (title, (song.get("artist") or "").strip(), (song.get("album") or "").strip(),
                cover, state, player)

    def cover(self, url: str) -> Image.Image | None:
        if not url:
            return None
        if url in self.cover_cache:
            return self.cover_cache[url]
        img = None
        try:
            full = url if url.startswith(("http://", "https://")) else f"{API}{url if url.startswith('/') else '/' + url}"
            if url.startswith("data:image"):
                import base64
                img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
            elif url.startswith("file://") or url.startswith("/") and os.path.exists(url):
                path = url[7:] if url.startswith("file://") else url
                img = Image.open(path)
            else:
                with urllib.request.urlopen(full, timeout=4) as r:
                    img = Image.open(io.BytesIO(r.read()))
            img = img.convert("RGB").resize((COVER, COVER), Image.LANCZOS)
        except Exception as e:
            self.log(f"nowplaying: cover fetch failed ({e})")
            img = None
        if len(self.cover_cache) > 32:
            self.cover_cache.clear()
        self.cover_cache[url] = img
        return img

    # ------------------------------------------------------------- render
    def render(self, title, artist, album, cover_url, state, player) -> Image.Image:
        card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        # soft shadowed glass panel
        shadow = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([12, 12, CARD_W - 12, CARD_H - 12], radius=34, fill=(0, 0, 0, 150))
        card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle([12, 12, CARD_W - 12, CARD_H - 12], radius=34, fill=(10, 12, 20, 165),
                            outline=(255, 255, 255, 28), width=2)

        x = PAD
        cov = self.cover(cover_url)
        cy = (CARD_H - COVER) // 2
        if cov is not None:
            mask = Image.new("L", (COVER, COVER), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, COVER - 1, COVER - 1], radius=22, fill=255)
            card.paste(cov, (x, cy), mask)
        else:
            d.rounded_rectangle([x, cy, x + COVER, cy + COVER], radius=22, fill=(40, 48, 70, 255))
            d.text((x + COVER / 2, cy + COVER / 2), "♪", font=ImageFont.truetype(FONT_B, 120),
                   fill=(150, 200, 255, 255), anchor="mm")
        tx = x + COVER + 36
        tw = CARD_W - tx - PAD - 10
        tag = ("PAUSED · " if state == "paused" else "NOW PLAYING · ") + player.upper()
        d.text((tx, 52), _fit(d, tag, self.fs, tw), font=self.fs, fill=(90, 190, 255, 255))
        d.text((tx, 92), _fit(d, title, self.fb, tw), font=self.fb, fill=(255, 255, 255, 255))
        if artist:
            d.text((tx, 168), _fit(d, artist, self.fa, tw), font=self.fa, fill=(215, 225, 245, 255))
        if album:
            d.text((tx, 224), _fit(d, album, self.fl, tw), font=self.fl, fill=(150, 165, 195, 255))
        if state == "paused":
            card.putalpha(card.getchannel("A").point(lambda a: int(a * 0.6)))
        return card

    def write(self, img: Image.Image | None) -> None:
        if img is None:
            try:
                self.out.unlink()
            except FileNotFoundError:
                pass
            return
        tmp = self.out.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(struct.pack("<II", img.width, img.height))
            f.write(img.tobytes())
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.out)

    # ------------------------------------------------------------- loop
    def run(self) -> None:
        while True:
            try:
                info = self.fetch()
                self.errors = 0
            except Exception as e:
                self.errors += 1
                if self.errors == 1:
                    self.log(f"nowplaying: AudioControl not reachable ({e})")
                info = None
            if info != self.key:
                self.key = info
                try:
                    self.write(self.render(*info) if info else None)
                    try:
                        cov = self.cover(info[3]) if info else None
                        pal = palette_from_image(cov) if cov is not None else None
                        if pal:
                            write_palette(self.palette_out, pal)
                        else:
                            try:
                                self.palette_out.unlink()
                            except FileNotFoundError:
                                pass
                    except Exception as e:
                        self.log(f"nowplaying: palette failed ({e})")
                    self.log(f"nowplaying: {info[4]} '{info[0]}' - {info[1]}" if info else "nowplaying: nothing")
                except Exception as e:
                    self.log(f"nowplaying: render failed ({e})")
            try:
                solo = soloist_current()
                if solo:
                    key = f"{solo[0]} | {solo[1]} | {solo[2]}"
                else:
                    _, mt = mpris_metadata()
                    key = (f"{info[0]} | {info[1]} | {mt}" if info else "")
                if key != self.track_key:
                    self.track_key = key
                    if key:
                        write_track_key(self.track_key_path, key)
                    else:
                        try:
                            self.track_key_path.unlink()
                        except FileNotFoundError:
                            pass
            except Exception as e:
                self.log(f"nowplaying: track key failed ({e})")
            time.sleep(self.interval)
