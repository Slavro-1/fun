"""Unit tests for half-block and Kitty graphics renderers."""
from pathlib import Path
import random
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools' / 'rendering'))

from fun_app.renderers.half_block import Encoder
from fun_app.renderers.kitty import KittyGraphics, _PosixShm, _rgb_bytes, make_gfx_scene
from fun_app.renderers.playback import _shm_available
from fun_app.scenes.base import make_scene
from fun_app.scenes.registry import SCENES
from gfxdecode import Commands, Decoder, live_shm


_ANSI_TOKEN = re.compile(r'\x1b\[\?2026[hl]|\x1b\[(\d+);(\d+)H|\x1b\[([0-9;]+)m|([^\x1b])')


def _apply_ansi(screen, data, is_text=False):
    """Apply Encoder ANSI bytes onto a (rows x cols) virtual cell grid."""
    if not data:
        return
    text = data.decode('utf-8')
    row = col = 0
    fg = bg = 0
    for match in _ANSI_TOKEN.finditer(text):
        r_str, c_str, sgr, ch = match.groups()
        if r_str is not None:
            row = int(r_str) - 1
            col = int(c_str) - 1
        elif sgr is not None:
            parts = [int(p) for p in sgr.split(';')]
            i = 0
            while i < len(parts):
                code = parts[i]
                if code == 38 and i + 4 < len(parts) and parts[i + 1] == 2:
                    fg = (parts[i + 2] << 16) | (parts[i + 3] << 8) | parts[i + 4]
                    i += 5
                elif code == 48 and i + 4 < len(parts) and parts[i + 1] == 2:
                    bg = (parts[i + 2] << 16) | (parts[i + 3] << 8) | parts[i + 4]
                    i += 5
                else:
                    i += 1
        elif ch is not None:
            if is_text:
                screen[row][col] = (ch, fg if ch != ' ' else 0)
            else:
                if ch == ' ':
                    screen[row][col] = (bg, bg)
                elif ch == '▀':
                    screen[row][col] = (fg, bg)
                else:
                    raise AssertionError(f'unexpected glyph {ch!r}')
            col += 1


def _ref_rgb_bytes(pixels, width, dither=False):
    out = bytearray(len(pixels) * 3)
    height = len(pixels) // width
    for y in range(height):
        for x in range(width):
            c = pixels[y * width + x]
            r = (c >> 16) & 255
            g = (c >> 8) & 255
            b = c & 255
            if dither and y < (height // 2) * 2:
                if (y & 1) == 0 and (x & 1) == 0:
                    r = 0 if r == 0 else min(255, r + 1)
                    g = 0 if g == 0 else min(255, g + 1)
                    b = 0 if b == 0 else min(255, b + 1)
                elif (y & 1) == 1 and (x & 1) == 1:
                    r = max(0, r - 1)
                    g = max(0, g - 1)
                    b = max(0, b - 1)
            idx = (y * width + x) * 3
            out[idx] = r
            out[idx + 1] = g
            out[idx + 2] = b
    return bytes(out)


class HalfBlockEncoderTests(unittest.TestCase):
    def test_blocks_visual_parity_across_diffs_masks_and_resizes(self):
        rng = random.Random(12345)
        enc = Encoder()
        for W, rows, mask in ((40, 12, 0xFFFFFF), (40, 12, 0xF8F8F8), (52, 16, 0xF0F0F0)):
            screen = [[(0, 0) for _ in range(W)] for _ in range(rows)]
            buf = [rng.randrange(0x1000000) for _ in range(W * rows * 2)]
            for step in range(5):
                if step == 1:
                    # Identical frame should emit empty bytes.
                    pkt = enc.blocks(buf, W, rows, mask)
                    self.assertEqual(pkt, b'')
                    continue
                if step > 1:
                    buf = buf[:]
                    for i in range(0, len(buf), 5):
                        buf[i] = rng.randrange(0x1000000)
                pkt = enc.blocks(buf, W, rows, mask)
                if pkt:
                    self.assertTrue(pkt.startswith(b'\x1b[?2026h'))
                    self.assertTrue(pkt.endswith(b'\x1b[?2026l'))
                _apply_ansi(screen, pkt, is_text=False)
                for cy in range(rows):
                    for x in range(W):
                        exp_top = buf[2 * cy * W + x] & mask
                        exp_bot = buf[(2 * cy + 1) * W + x] & mask
                        self.assertEqual(screen[cy][x], (exp_top, exp_bot))

    def test_text_visual_parity_with_unicode(self):
        enc = Encoder()
        W, rows = 30, 10
        screen = [[(' ', 0) for _ in range(W)] for _ in range(rows)]
        chars = [' '] * (W * rows)
        fgs = [0] * (W * rows)
        glyphs = ['A', 'ｦ', 'ﾊ', 'ﾐ', '9']
        rng = random.Random(99)
        for step in range(4):
            if step == 1:
                self.assertEqual(enc.text(chars, fgs, W, rows), b'')
                continue
            chars = chars[:]
            fgs = fgs[:]
            for i in range(0, W * rows, 3):
                chars[i] = rng.choice(glyphs) if rng.random() > 0.3 else ' '
                fgs[i] = rng.randrange(0x1000000)
            pkt = enc.text(chars, fgs, W, rows)
            _apply_ansi(screen, pkt, is_text=True)
            for cy in range(rows):
                for x in range(W):
                    c = chars[cy * W + x]
                    f = fgs[cy * W + x] if c != ' ' else 0
                    self.assertEqual(screen[cy][x], (c, f))

    def test_seeded_scene_blocks_and_text_parity(self):
        for name in ('aurora', 'koi', 'metropolis', 'matrix'):
            cls = SCENES[name]
            cols, rows = 60, 20
            scene = cls.__new__(cls)
            scene.W, scene.H = cols, rows if cls.text else rows * 2
            scene.rng = random.Random(41209)
            scene.setup()
            enc = Encoder()
            screen = [[(' ', 0) if cls.text else (0, 0) for _ in range(cols)] for _ in range(rows)]
            dt = min(0.1, 1.0 / scene.fps)
            for i in range(6):
                res = scene.frame(i * dt, dt)
                if cls.text:
                    pkt = enc.text(res[0], res[1], cols, rows)
                    _apply_ansi(screen, pkt, is_text=True)
                    for cy in range(rows):
                        for x in range(cols):
                            c = res[0][cy * cols + x]
                            f = res[1][cy * cols + x] if c != ' ' else 0
                            self.assertEqual(screen[cy][x], (c, f))
                else:
                    pkt = enc.blocks(res, cols, rows, scene.mask)
                    _apply_ansi(screen, pkt, is_text=False)
                    for cy in range(rows):
                        for x in range(cols):
                            et = res[2 * cy * cols + x] & scene.mask
                            eb = res[(2 * cy + 1) * cols + x] & scene.mask
                            self.assertEqual(screen[cy][x], (et, eb))


class KittyRendererTests(unittest.TestCase):
    def test_rgb_bytes_parity_even_and_odd_dimensions(self):
        rng = random.Random(7)
        for width, height in ((2, 2), (3, 3), (16, 8), (17, 9), (64, 31)):
            pixels = [rng.randrange(0x1000000) for _ in range(width * height)]
            pixels[0] = 0
            pixels[-1] = 0xFFFFFF
            for dither in (False, True):
                got = bytes(_rgb_bytes(pixels, width, dither=dither))
                exp = _ref_rgb_bytes(pixels, width, dither=dither)
                self.assertEqual(got, exp, f'mismatch for {width}x{height} dither={dither}')

    def test_zlib_packet_single_and_multi_chunk_roundtrip(self):
        kg = KittyGraphics()
        rng = random.Random(21)
        for width, height in ((8, 6), (120, 80)):
            pixels = [rng.randrange(0x1000000) for _ in range(width * height)]
            pkt = kg.packet(pixels, width, height, 80, 24, dither=False)
            self.assertTrue(pkt.startswith(b'\x1b[?2026h\x1b[H'))
            self.assertTrue(pkt.endswith(b'\x1b[?2026l'))
            commands = Commands()
            decoder = Decoder()
            frames = [decoder.frame(f, p) for f, p in commands.feed(pkt)]
            frames = [f for f in frames if f is not None]
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].size, (width, height))
            self.assertEqual(frames[0].pixels, _ref_rgb_bytes(pixels, width, dither=False))

    def test_shm_packet_roundtrip(self):
        if not _shm_available():
            self.skipTest('POSIX SHM unavailable')
        kg = KittyGraphics()
        kg.shm = _PosixShm()
        rng = random.Random(33)
        width, height = 64, 32
        pixels = [rng.randrange(0x1000000) for _ in range(width * height)]
        try:
            pkt = kg.packet(pixels, width, height, 80, 24, dither=True)
            commands = Commands()
            decoder = Decoder(live_shm)
            frames = [decoder.frame(f, p) for f, p in commands.feed(pkt)]
            frames = [f for f in frames if f is not None]
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].size, (width, height))
            self.assertEqual(frames[0].pixels, _ref_rgb_bytes(pixels, width, dither=True))
        finally:
            kg.shm.clear()


if __name__ == '__main__':
    unittest.main()
