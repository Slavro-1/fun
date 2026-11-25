#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extras.py - 43 terminal screensavers for the `fun` launcher.

    extras.py SCENE            run one scene   (q / Esc / Ctrl-C quits)
    extras.py --list           list scene names
    extras.py --selftest       headless test of every scene at several sizes
    extras.py --bench [SCENE]  headless half-block timing and output size
    extras.py --bench-gfx [SCENE]  headless kitty timing and output size
    extras.py --gfx-info       report viewport and graphics framebuffer sizes

Design notes
  * Scenes draw into a flat list of packed 0xRRGGBB ints, two pixels per
    terminal cell (upper-half-block glyph: fg = top pixel, bg = bottom pixel).
    Text scenes (matrix) fill a cell grid of characters instead.
  * The encoder diffs against the previous frame and only emits changed cell
    runs, reusing SGR colour state across the whole frame.
  * A duty-cycle governor keeps the script under ~35% of one core and also
    slows down automatically if the terminal cannot swallow output fast enough
    (this is what protects against the old "Ctrl+C does nothing" flood).
  * Terminal state (alt screen, cursor, autowrap, echo) is restored from
    finally / atexit / signal handlers.  SIGKILL cannot be caught; the
    launcher resets the terminal after any scene exits.
"""

import array
import atexit
import base64
import errno
import gc
import math
import os
from operator import itemgetter
from functools import lru_cache
import random
import re
import select
import signal
import struct
import sys
import time
import traceback
import zlib

try:
    import fcntl
    import termios
except ImportError:  # pragma: no cover
    fcntl = termios = None

sin = math.sin
cos = math.cos
sqrt = math.sqrt
atan2 = math.atan2
exp = math.exp
hypot = math.hypot
TAU = math.tau
PI = math.pi

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "fun")
LOG_FILE = os.path.join(CACHE_DIR, "errors.log")
DUTY = 0.35            # max fraction of one core a scene may use
MIN_COLS, MIN_ROWS = 24, 8


# ====================================================================== colour
def clamp8(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def rgb(r, g, b):
    return (clamp8(r) << 16) | (clamp8(g) << 8) | clamp8(b)


def shade(c, f):
    """Scale brightness of packed colour c by f/256 (f: int, clamped to 0..256)."""
    if f <= 0:
        return 0
    if f > 256:
        f = 256
    return ((((c & 0xFF00FF) * f) >> 8) & 0xFF00FF) | ((((c & 0x00FF00) * f) >> 8) & 0x00FF00)


def mix(c1, c2, f):
    """Linear blend c1 -> c2, f is int 0..256."""
    return shade(c1, 256 - f) + shade(c2, f)


def addp(a, b):
    """Saturating per-channel add of two packed colours."""
    s = a + b
    m = (s ^ a ^ b) & 0x1010100
    if m:
        s = (s | (m - (m >> 8))) & 0xFFFFFF
    return s


def gradient(stops, n):
    """stops: [(pos 0..1, (r,g,b)), ...] -> list of n packed colours."""
    out = []
    last = len(stops) - 1
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        k = 0
        while k < last - 1 and t > stops[k + 1][0]:
            k += 1
        p0, c0 = stops[k]
        p1, c1 = stops[k + 1]
        u = 0.0 if p1 <= p0 else min(1.0, max(0.0, (t - p0) / (p1 - p0)))
        out.append(rgb(c0[0] + (c1[0] - c0[0]) * u, c0[1] + (c1[1] - c0[1]) * u,
                       c0[2] + (c1[2] - c0[2]) * u))
    return out


def cospal(n, a, b, c, d):
    """Inigo-Quilez cosine palette; a,b,c,d are (r,g,b) triples in 0..1 units."""
    out = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        out.append(rgb(*[255 * (a[k] + b[k] * cos(TAU * (c[k] * t + d[k]))) for k in range(3)]))
    return out


def vgrad(W, H, stops):
    buf = []
    for c in gradient(stops, H):
        buf += [c] * W
    return buf


# ================================================================== primitives
def plot(buf, W, H, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        buf[y * W + x] = c


def plota(buf, W, H, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        i = y * W + x
        a = buf[i]
        s = a + c
        m = (s ^ a ^ c) & 0x1010100
        if m:
            s = (s | (m - (m >> 8))) & 0xFFFFFF
        buf[i] = s


def _line_steps(W, H, x0, y0, x1, y1):
    dx = x1 - x0
    dy = y1 - y0
    if dx != dx or dy != dy or abs(dx) > 1e5 or abs(dy) > 1e5:
        return 0
    if (x0 < 0 and x1 < 0) or (y0 < 0 and y1 < 0) or (x0 >= W and x1 >= W) or (y0 >= H and y1 >= H):
        return 0
    return int(max(abs(dx), abs(dy))) + 1


def line_add(buf, W, H, x0, y0, x1, y1, c):
    n = _line_steps(W, H, x0, y0, x1, y1)
    if not n:
        return
    sx = (x1 - x0) / n
    sy = (y1 - y0) / n
    x = x0 + 0.5
    y = y0 + 0.5
    for _ in range(n + 1):
        if 0 <= x < W and 0 <= y < H:
            i = int(y) * W + int(x)
            a = buf[i]
            s = a + c
            m = (s ^ a ^ c) & 0x1010100
            if m:
                s = (s | (m - (m >> 8))) & 0xFFFFFF
            buf[i] = s
        x += sx
        y += sy


def line_set(buf, W, H, x0, y0, x1, y1, c):
    n = _line_steps(W, H, x0, y0, x1, y1)
    if not n:
        return
    sx = (x1 - x0) / n
    sy = (y1 - y0) / n
    x = x0 + 0.5
    y = y0 + 0.5
    for _ in range(n + 1):
        if 0 <= x < W and 0 <= y < H:
            buf[int(y) * W + int(x)] = c
        x += sx
        y += sy


def _gfx_line_set(buf, W, H, x0, y0, x1, y1, c, width=1.):
    _gfx_line(buf,W,H,x0,y0,x1,y1,c,False,width)


def _gfx_line_add(buf, W, H, x0, y0, x1, y1, c, width=1.):
    _gfx_line(buf,W,H,x0,y0,x1,y1,c,True,width)


def _gfx_line(buf, W, H, x0, y0, x1, y1, c, additive, width):
    """Blend a thin stroke over the two nearest samples of its minor axis."""
    if not _line_steps(W,H,x0,y0,x1,y1):
        return
    steep = abs(y1-y0) > abs(x1-x0)
    if steep:
        x0,y0,x1,y1 = y0,x0,y1,x1
    if x0 > x1:
        x0,x1,y0,y1 = x1,x0,y1,y0
    span = x1-x0
    slope = (y1-y0)/span if span else 0.
    major,minor = (H,W) if steep else (W,H)
    fringe = min(128, max(0,round(128*(width-1.))))
    for x in range(max(0,round(x0)),min(major,round(x1)+1)):
        y = y0+(x-x0)*slope
        base = math.floor(y)
        alpha = int((y-base)*256)
        samples = ((base,256-alpha),(base+1,alpha))
        if fringe:
            samples += ((base-1,(fringe*(256-alpha))>>8),(base+2,(fringe*alpha)>>8))
        for yy,weight in samples:
            if weight and 0 <= yy < minor:
                i = x*W+yy if steep else yy*W+x
                buf[i] = addp(buf[i],shade(c,weight)) if additive else mix(buf[i],c,weight)


def _gfx_point_rim(buf,W,H,x,y,color):
    plota(buf,W,H,x-1,y,color)
    plota(buf,W,H,x+1,y,color)
    plota(buf,W,H,x,y-1,color)
    plota(buf,W,H,x,y+1,color)


def make_sprite(color, r, levels=8, power=2.0):
    """Soft glow sprites: list (per brightness level) of (dx, dy, colour)."""
    out = []
    for lv in range(levels):
        k = (lv + 1) / levels
        pts = []
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                d = sqrt(dx * dx + dy * dy) / (r + 0.35)
                if d < 1.0:
                    c = shade(color, int((1 - d) ** power * k * 256))
                    if c:
                        pts.append((dx, dy, c))
        out.append(pts)
    return out


def stamp(buf, W, H, x, y, pts):
    for dx, dy, c in pts:
        xx = x + dx
        yy = y + dy
        if 0 <= xx < W and 0 <= yy < H:
            i = yy * W + xx
            a = buf[i]
            s = a + c
            m = (s ^ a ^ c) & 0x1010100
            if m:
                s = (s | (m - (m >> 8))) & 0xFFFFFF
            buf[i] = s


def fill_row(buf, W, y, x0, x1, c):
    if x1 > x0:
        buf[y * W + x0:y * W + x1] = [c] * (x1 - x0)


def up2(f, sw, sh, W, H, pal):
    """Upscale an int field (sw x sh, values index `pal`) 2x with linear
    interpolation in index space -> flat list of W*H packed colours."""
    out = []
    ext = out.extend
    get = pal.__getitem__
    rows = []
    for y in range(sh):
        r = f[y * sw:(y + 1) * sw]
        h = [0] * (2 * sw)
        h[0::2] = r
        h[1::2] = [(a + b) >> 1 for a, b in zip(r, r[1:] + r[-1:])]
        rows.append(h)
    rows.append(rows[-1])
    n = 0
    for y in range(sh):
        a = rows[y][:W]
        ext(map(get, a))
        n += 1
        if n >= H:
            break
        b = rows[y + 1][:W]
        ext(map(get, [(p + q) >> 1 for p, q in zip(a, b)]))
        n += 1
        if n >= H:
            break
    return out


SIN256 = [int(127.5 + 127.5 * sin(i * TAU / 256)) for i in range(256)]


# ====================================================================== scene
class Scene:
    fps = 15
    text = False
    mask = 0xFFFFFF        # colour quantisation applied by the half-block encoder
    S = 1.0                 # physical pixel scale for scene details
    gfx = False
    gfx_reference = None    # prior medium grid for resolution-independent seeded detail
    gfx_pixels = 85_000     # prior medium ceiling used for the detail grid
    gfx_fps = 22
    gfx_dither = False

    def __init__(self, W, H, *, scale=1.0, gfx=False):
        self.W = W
        self.H = H
        self.S = scale
        self.gfx = gfx
        self.rng = random.Random()
        self.setup()

    def px(self, value):
        return max(1, round(self.S * value))

    @property
    def logical_area(self):
        if self.gfx_reference:
            w, h = self.gfx_reference
            logical_h = self.H / self.S
            return w / h * logical_h * logical_h
        return self.W * self.H / (self.S * self.S)

    @property
    def detail_scale(self):
        return self.H / self.gfx_reference[1] if self.gfx_reference else 1.

    def detail_coord(self, stop, vertical=False, reference_stop=None):
        if self.gfx_reference is None:
            return self.rng.randrange(stop)
        axis = int(vertical)
        size = self.H if vertical else self.W
        reference = self.gfx_reference[axis]
        limit = reference_stop if reference_stop is not None else max(1, round(stop*reference/size))
        return min(stop-1, int(self.rng.randrange(limit)*size/reference))

    def setup(self):
        pass

    def frame(self, t, dt):
        raise NotImplementedError


class Episode:
    """Time-addressable seeded story with a short dark seam between episodes."""

    def __init__(self, rng, stages, fade=2.0):
        self.seed = rng.getrandbits(64)
        self.stages = tuple(stages)  # (name, start, duration)
        self.length = max(start + duration for _, start, duration in stages)
        self.fade = fade

    def clock(self, t):
        span = self.length + self.fade
        number = max(0, int(t // span))
        local = max(0., t - number * span)
        opacity = max(0., 1. - max(0., local - self.length) / self.fade)
        return number, min(local, self.length), opacity

    def rng(self, number):
        return random.Random((self.seed + number * 0x9E3779B97F4A7C15) & ((1 << 64) - 1))

    def stage(self, t):
        _, local, _ = self.clock(t)
        for i in range(len(self.stages) - 1, -1, -1):
            _, start, duration = self.stages[i]
            if local >= start:
                return i, min(1., max(0., (local - start) / duration))
        return 0, 0.


# ===================================================================== encoder
class _Esc(dict):
    def __init__(self, code):
        dict.__init__(self)
        self.code = code

    def __missing__(self, c):
        if len(self) > 60000:      # bound memory
            self.clear()
        s = '\x1b[%s;2;%d;%d;%dm' % (self.code, c >> 16, (c >> 8) & 255, c & 255)
        self[c] = s
        return s


def _runs(idx, gap=4):
    runs = []
    s = p = idx[0]
    for x in idx[1:]:
        if x - p > gap:
            runs.append((s, p + 1))
            s = x
        p = x
    runs.append((s, p + 1))
    return runs


class Encoder:
    """Diffing ANSI encoder.  Returns bytes (or b'' when nothing changed)."""

    def __init__(self):
        self.fg = _Esc('38')
        self.bg = _Esc('48')
        self.prev = None
        self.prev2 = None

    def reset(self):
        self.prev = None
        self.prev2 = None

    def blocks(self, buf, W, rows, mask=0xFFFFFF):
        if mask != 0xFFFFFF:
            buf = [c & mask for c in buf]
        prev = self.prev
        FG = self.fg
        BG = self.bg
        out = []
        ap = out.append
        lf = lb = -1
        for cy in range(rows):
            a = 2 * cy * W
            m = a + W
            e = m + W
            top = buf[a:m]
            bot = buf[m:e]
            if prev is None:
                runs = ((0, W),)
            else:
                ptop = prev[a:m]
                pbot = prev[m:e]
                if top == ptop and bot == pbot:
                    continue
                idx = [x for x in range(W) if top[x] != ptop[x] or bot[x] != pbot[x]]
                runs = _runs(idx)
            for x0, x1 in runs:
                ap('\x1b[%d;%dH' % (cy + 1, x0 + 1))
                for x in range(x0, x1):
                    t = top[x]
                    b = bot[x]
                    if t == b:
                        if b != lb:
                            ap(BG[b])
                            lb = b
                        ap(' ')
                    else:
                        if t != lf:
                            ap(FG[t])
                            lf = t
                        if b != lb:
                            ap(BG[b])
                            lb = b
                        ap('▀')
        self.prev = buf[:]
        if not out:
            return b''
        return ('\x1b[?2026h' + ''.join(out) + '\x1b[?2026l').encode('utf-8')

    def text(self, chars, fgs, W, rows):
        prev = self.prev
        pch, pfg = self.prev2 if prev is not None else (None, None)
        FG = self.fg
        BG = self.bg
        out = []
        ap = out.append
        ap(BG[0])
        lf = -1
        for cy in range(rows):
            a = cy * W
            e = a + W
            ch = chars[a:e]
            fg = fgs[a:e]
            if prev is None:
                runs = ((0, W),)
            else:
                pc = pch[a:e]
                pf = pfg[a:e]
                if ch == pc and fg == pf:
                    continue
                idx = [x for x in range(W) if ch[x] != pc[x] or fg[x] != pf[x]]
                runs = _runs(idx)
            for x0, x1 in runs:
                ap('\x1b[%d;%dH' % (cy + 1, x0 + 1))
                for x in range(x0, x1):
                    c = ch[x]
                    if c == ' ':
                        ap(' ')
                    else:
                        f = fg[x]
                        if f != lf:
                            ap(FG[f])
                            lf = f
                        ap(c)
        self.prev = True
        self.prev2 = (chars[:], fgs[:])
        if len(out) <= 1:
            return b''
        return ('\x1b[?2026h' + ''.join(out) + '\x1b[?2026l').encode('utf-8')


# ================================================================= kitty graphics
_GFX_START = b'\x1b_G'
_GFX_END = b'\x1b\\'
_GFX_MAX_BPS = 1_200_000
# Each tier targets a linear fraction of the drawable viewport. Area ceilings
# reserve time for image packing and bound setup caches on large displays.
_GFX_LEVELS = {'low': (.23, 100_000), 'med': (.32, 180_000),
               'high': (.44, 300_000), 'ultra': (.60, 460_000)}
_GFX_DEFAULT = 'ultra'
_GFX_ZLIB_PIXELS = 68_000
_GFX_ZLIB_CAPS = {'Aurora': 51_000, 'Filings': 37_000, 'Lanterns': 52_000,
                  'Nebula': 48_000, 'Wormhole': 41_000, 'Streetlamp': 52_000,
                  'Mistwood': 51_000, 'Metropolis': 33_000}
_GFX_CAPS = {
    'Aurora': (44, 74, 104, 120),
    'Bokeh': (54, 99, 142, 179),
    'Dunes': (47, 86, 122, 153),
    'Constellation': (60, 104, 133, 170),
    'Donut': (26, 41, 54, 67),
    'Fire': (48, 91, 133, 171),
    'Filings': (32, 58, 75, 92),
    'Flyover': (35, 64, 91, 116),
    'Fractal': (64, 115, 166, 210),
    'Jellyfish': (38, 76, 100, 123),
    'Kaleido': (44, 80, 119, 157),
    'Koi': (43, 74, 105, 133),
    'Lanterns': (40, 72, 98, 108),
    'Lava': (45, 90, 133, 174),
    'Nebula': (38, 66, 105, 123),
    'Plexus': (72, 129, 177, 220),
    'Prism': (39, 65, 92, 117),
    'Silk': (48, 93, 140, 177),
    'Spiro': (42, 85, 130, 176),
    'Tesseract': (92, 155, 220, 310),
    'Thunder': (40, 74, 101, 129),
    'Wormhole': (30, 46, 61, 76),
    'Lighthouse': (62, 110, 150, 195),
    'Streetlamp': (54, 94, 124, 158),
    'Mistwood': (62, 103, 132, 160),
    'Metropolis': (63, 110, 151, 195),
}
_CELL_PIXELS = re.compile(rb'\x1b\[6;(\d+);(\d+)t')


def _gfx_command(fields, payload=b''):
    return _GFX_START + fields.encode('ascii') + b';' + payload + _GFX_END


def _gfx_size(cls, cols, rows, pixel_width, pixel_height, quality, transport='shm'):
    if not pixel_width or not pixel_height:
        pixel_width, pixel_height = cols * 10, rows * 20
    if quality not in _GFX_LEVELS:
        quality = _GFX_DEFAULT
    if transport == 'zlib' and quality in ('high', 'ultra'):
        quality = 'med'
    fraction, limit = _GFX_LEVELS[quality]
    if cls is not None:
        caps = _GFX_CAPS.get(cls.__name__)
        if caps is not None:
            limit = min(limit, 1000 * caps[tuple(_GFX_LEVELS).index(quality)])
    if transport == 'zlib':
        limit = min(limit, _GFX_ZLIB_CAPS.get(cls.__name__ if cls else '', _GFX_ZLIB_PIXELS))
    scale = min(fraction, sqrt(limit / (pixel_width * pixel_height)))
    return max(2, round(pixel_width * scale)), max(2, round(pixel_height * scale))


def _gfx_reference(cls, cols, rows, width, height):
    aspect = width / height if width and height else cols / (2*rows)
    h = min(4.5*rows, sqrt(cls.gfx_pixels/aspect), height or 4096, (width or 4096)/aspect)
    return max(2, round(h*aspect)), max(2, round(h))


def make_gfx_scene(cls, cols, rows, pixel_width=0, pixel_height=0, quality=_GFX_DEFAULT,
                   transport='shm'):
    if cls.text:
        return make_scene(cls, cols, rows)
    width, height = _gfx_size(cls, cols, rows, pixel_width, pixel_height, quality, transport)
    scene = cls.__new__(cls)
    scene.gfx_reference = _gfx_reference(cls, cols, rows, pixel_width, pixel_height)
    cls.__init__(scene, width, height, scale=height / (2 * rows), gfx=True)
    scene.fps = min(24, cls.gfx_fps)
    return scene


def _rgb_bytes(pixels, width, dither=False):
    # The strided channel copies run in C. The scene's packed-int API stays unchanged.
    packed = array.array('I', pixels)
    if packed.itemsize != 4:
        return bytes(value for pixel in pixels for value in (pixel >> 16, pixel >> 8 & 255, pixel & 255))
    data = packed.tobytes()
    raw = bytearray(len(pixels) * 3)
    offsets = (2, 1, 0) if sys.byteorder == 'little' else (1, 2, 3)
    for channel, offset in enumerate(offsets):
        plane = data[offset::4]
        if dither:
            # A fixed 2x2 pattern offsets two samples by one RGB level in opposite directions.
            plane = bytearray(plane)
            for begin in range(0, len(plane) - width, 2 * width):
                end = begin + width
                plane[begin:end:2] = plane[begin:end:2].translate(_DITHER_UP)
                plane[end+1:end+width:2] = plane[end+1:end+width:2].translate(_DITHER_DOWN)
        raw[channel::3] = plane
    return raw


_DITHER_UP = bytes(0 if i == 0 else min(255, i + 1) for i in range(256))
_DITHER_DOWN = bytes(max(0, i - 1) for i in range(256))


class _PosixShm:
    """Keep a small set of names until kitty takes ownership and unlinks them."""

    def __init__(self):
        import ctypes

        libraries = (None, 'librt.so.1') if sys.platform.startswith('linux') else (None,)
        for library in libraries:
            try:
                libc = ctypes.CDLL(library, use_errno=True)
                self.open, self.unlink = libc.shm_open, libc.shm_unlink
                break
            except (AttributeError, OSError):
                continue
        else:
            raise OSError('POSIX shared memory unavailable')
        self.open.argtypes = (ctypes.c_char_p, ctypes.c_int, ctypes.c_uint)
        self.open.restype = ctypes.c_int
        self.unlink.argtypes = (ctypes.c_char_p,)
        self.unlink.restype = ctypes.c_int
        self.errno = ctypes.get_errno
        self.prefix = b'/fun-' + os.urandom(6).hex().encode('ascii')
        self.serial = 0
        self.pending = set()

    def write(self, pixels):
        for name in tuple(self.pending):
            fd = self.open(name, os.O_RDONLY, 0)
            if fd >= 0:
                os.close(fd)
            elif self.errno() == errno.ENOENT:
                self.pending.remove(name)
            else:
                raise OSError(self.errno(), 'could not inspect shared frame')
        if len(self.pending) >= 4:
            raise OSError('kitty stopped consuming shared frames')
        self.serial += 1
        name = self.prefix + b'-' + str(self.serial).encode('ascii')
        self.pending.add(name)
        fd = self.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        if fd < 0:
            self.pending.remove(name)
            raise OSError(self.errno(), 'could not create shared frame')
        try:
            os.ftruncate(fd, len(pixels))
            remaining = memoryview(pixels)
            while remaining:
                count = os.write(fd, remaining)
                if not count:
                    raise OSError('short shared frame write')
                remaining = remaining[count:]
        except BaseException:
            self.unlink(name)
            self.pending.discard(name)
            raise
        finally:
            os.close(fd)
        return name

    def clear(self):
        for name in self.pending:
            self.unlink(name)
        self.pending.clear()


class KittyGraphics:
    """One image and placement per scene process, with a bounded SHM queue."""

    def __init__(self, term=None):
        self.term = term
        self.image_id = int.from_bytes(os.urandom(4), 'big') or 1
        self.shm = None
        self.active = False
        self.interrupted = False
        self.payload_prefix = f'a=T,i={self.image_id},p=1,f=24,q=2,C=1,'
        self.delete = _gfx_command(f'a=d,d=I,i={self.image_id},q=2')

    def _accepts(self, medium, payload):
        pattern = re.compile(rb'\x1b_Gi=' + str(self.image_id).encode('ascii') + rb';([ -~]{1,240})\x1b\\')
        request = _gfx_command(f'a=q,i={self.image_id},s=1,v=1,f=24,t={medium}', payload)
        reply = self.term.reply(request, pattern, .22)
        return reply is not None and reply[1] == b'OK'

    @staticmethod
    def local_terminal():
        env = os.environ
        name = env.get('TERM', '')
        if (name.startswith(('screen', 'tmux'))
                or any(env.get(key) for key in ('TMUX', 'STY', 'SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY'))):
            return False
        return bool(name == 'xterm-kitty' or env.get('KITTY_WINDOW_ID') or env.get('TERM_PROGRAM') == 'kitty')

    @classmethod
    def detect(cls, term):
        if os.environ.get('FUN_GFX', 'auto') == '0' or not term.tty_in or not cls.local_terminal():
            return None
        backend = cls(term)
        if not backend._accepts('d', b'AAAA'):
            return None
        try:
            backend.shm = _PosixShm()
            name = backend.shm.write(b'\0\0\0')
            if not backend._accepts('s', base64.b64encode(name)):
                backend.shm.clear()
                backend.shm = None
        except OSError:
            if backend.shm:
                backend.shm.clear()
            backend.shm = None
        except BaseException:
            backend.close()
            raise
        return backend

    def packet(self, pixels, width, height, cols, rows, dither=False):
        fields = self.payload_prefix + f's={width},v={height},c={cols},r={rows}'
        raw = _rgb_bytes(pixels, width, dither and self.shm is not None)
        if self.shm is not None:
            try:
                name = self.shm.write(raw)
            except OSError:
                # The terminal may be lagging or may have lost access to our SHM namespace.
                self.shm.clear()
                self.shm = None
            else:
                return b'\x1b[?2026h\x1b[H' + _gfx_command(fields + f',t=s,S={len(raw)}',
                                                         base64.b64encode(name)) + b'\x1b[?2026l'
        compressed = base64.b64encode(zlib.compress(raw, 1))
        chunks = []
        for start in range(0, len(compressed), 4096):
            more = int(start + 4096 < len(compressed))
            header = f'm={more}' if start else fields + f',t=d,o=z,m={more}'
            chunks.append(_gfx_command(header, compressed[start:start + 4096]))
        return b'\x1b[?2026h\x1b[H' + b''.join(chunks) + b'\x1b[?2026l'

    def show(self, frame, scene, cols, rows):
        data = self.packet(frame, scene.W, scene.H, cols, rows, scene.gfx_dither)
        self.active = self.interrupted = True
        self.term.write(data)
        self.interrupted = False
        return len(data)

    def close(self):
        try:
            if self.active and self.term is not None:
                # Finish an interrupted APC before deleting the placement on the alt screen.
                tail = _GFX_END + _gfx_command('m=0,q=2') if self.interrupted else b''
                self.term.write(tail + self.delete + (b'\x1b[?2026l' if self.interrupted else b''))
        finally:
            self.active = self.interrupted = False
            if self.shm is not None:
                self.shm.clear()


# ==================================================================== terminal
class Terminal:
    ENTER = b'\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[0m\x1b[2J\x1b[H'
    LEAVE = b'\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l'

    def __init__(self):
        self.fd = 1
        self.in_fd = 0
        self.active = False
        self.saved = None
        self.winch = True
        self.tty_in = False
        self.sync_pending = False
        self.stop = False

    def pixels(self):
        if fcntl is not None:
            try:
                _, _, width, height = struct.unpack('HHHH',
                    fcntl.ioctl(self.fd, termios.TIOCGWINSZ, bytes(8)))
                return width, height
            except OSError:
                pass
        return 0, 0

    def cell_pixels(self):
        reply = self.reply(b'\x1b[16t', _CELL_PIXELS, .12)
        if reply:
            height, width = map(int, reply.groups())
            return width, height
        return 0, 0

    def reply(self, request, pattern, timeout):
        self.write(request)
        deadline = time.monotonic() + timeout
        data = b''
        while time.monotonic() < deadline and len(data) < 4096:
            ready, _, _ = select.select([self.in_fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            part = os.read(self.in_fd, 256)
            if not part:
                break
            data += part
            match = pattern.search(data)
            if match:
                other = data[:match.start()] + data[match.end():]
                self.stop |= other.strip() in (b'q', b'Q', b'\x1b')
                return match
            if data in (b'q',b'Q'):
                self.stop = True
                break
        self.stop |= data == b'\x1b'
        return None

    def size(self):
        for fd in (self.fd, 2, 0):
            try:
                c, r = os.get_terminal_size(fd)
                if c > 0 and r > 0:
                    return c, r
            except OSError:
                pass
        return 80, 24

    def write(self, data):
        if not data:
            return
        if data.startswith(b'\x1b[?2026h'):
            self.sync_pending = True
        mv = memoryview(data)
        while mv:
            try:
                n = os.write(self.fd, mv)
            except BlockingIOError:
                select.select([], [self.fd], [], 0.5)
                continue
            except OSError:
                raise SystemExit(0)       # terminal went away
            mv = mv[n:]
        if data.endswith(b'\x1b[?2026l'):
            self.sync_pending = False

    def enter(self):
        if self.active:
            return
        self.active = True
        try:
            self.tty_in = os.isatty(self.in_fd) and termios is not None
            if self.tty_in:
                self.saved = termios.tcgetattr(self.in_fd)
                new = termios.tcgetattr(self.in_fd)
                new[3] &= ~(termios.ECHO | termios.ICANON)      # keep ISIG (Ctrl+C)
                new[6][termios.VMIN] = 0
                new[6][termios.VTIME] = 0
                termios.tcsetattr(self.in_fd, termios.TCSADRAIN, new)
        except Exception:
            self.saved = None
        self.write(self.ENTER)

    def leave(self):
        if not self.active:
            return
        self.active = False
        try:
            self.write((b'\x1b[?2026l' if self.sync_pending else b'') + self.LEAVE)
        except BaseException:
            pass
        try:
            if self.saved is not None:
                termios.tcsetattr(self.in_fd, termios.TCSAFLUSH, self.saved)
        except Exception:
            pass

    def wait(self, timeout):
        """Sleep up to `timeout` s; return True if the user pressed q / Esc."""
        if self.stop:
            return True
        if timeout < 0:
            timeout = 0
        if not self.tty_in:
            time.sleep(timeout)
            return False
        try:
            r, _, _ = select.select([self.in_fd], [], [], timeout)
            if r:
                data = os.read(self.in_fd, 64)
                if b'q' in data or b'Q' in data or data == b'\x1b':
                    return True
        except (OSError, ValueError):
            pass
        return False


def _on_term(signum, frame):
    raise SystemExit(0)


def log_error(name, size, exc_text):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(LOG_FILE, 'a') as fh:
            fh.write('[%s] scene=%s size=%s\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'),
                                                     name, size, exc_text))
    except OSError:
        pass


class SceneFailure(Exception):
    pass


def make_scene(cls, cols, rows):
    if cls.text:
        return cls(cols, rows)
    return cls(cols, rows * 2)


def run(name):
    cls = SCENES[name]
    term = Terminal()
    term.winch = True

    def on_winch(signum, frame):
        term.winch = True

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, _on_term)
    signal.signal(signal.SIGWINCH, on_winch)
    atexit.register(term.leave)
    gc.disable()                       # frame data is acyclic; collect manually
    graphics = None
    try:
        term.enter()
        if not cls.text:
            graphics = KittyGraphics.detect(term)
        _loop(term, cls, name, graphics)
    finally:
        try:
            if graphics is not None:
                graphics.close()
        finally:
            term.leave()


def _loop(term, cls, name, graphics=None):
    enc = Encoder()
    scene = None
    size = None
    t0 = last = time.perf_counter()
    fails = 0
    good = 0
    nframes = 0
    next_size_check = 0.0
    geometry = None
    resize_due = 0.0
    transport = None
    quality = os.environ.get('FUN_RES', _GFX_DEFAULT)
    while not term.stop:
        fs = time.perf_counter()
        medium = ('shm' if graphics.shm is not None else 'zlib') if graphics else None
        if graphics and term.winch and geometry is not None:
            term.winch = False
            resize_due = fs + .09
        if resize_due and fs < resize_due:
            if term.wait(resize_due - fs):
                return
            continue
        if term.winch or resize_due or fs >= next_size_check or medium != transport:
            resized = term.winch or bool(resize_due)
            term.winch = False
            resize_due = 0.0
            next_size_check = fs + 2.0
            cols, rows = term.size()
            dimensions = (cols, rows)
            if graphics is not None:
                width, height = term.pixels()
                if not width or not height:
                    if resized or size != (cols, rows):
                        cw, ch = term.cell_pixels()
                        width, height = cols * cw, rows * ch
                    elif geometry is not None:
                        width, height = geometry[2:]
                dimensions = (cols, rows, width, height)
            if dimensions != geometry or medium != transport:
                if graphics is not None:
                    graphics.close()
                geometry = dimensions
                transport = medium
                size = (cols, rows)
                scene = None
                enc.reset()
                term.write(b'\x1b[0m\x1b[2J\x1b[H')
                if cols >= MIN_COLS and rows >= MIN_ROWS:
                    try:
                        scene = make_gfx_scene(cls, *geometry, quality, transport) if graphics is not None else make_scene(cls, *size)
                    except Exception:
                        log_error(name, size, traceback.format_exc())
                        raise SceneFailure('could not initialise at %dx%d' % size)
                else:
                    msg = 'terminal too small (%dx%d)' % size
                    term.write(('\x1b[1;1H\x1b[38;2;200;200;200m' + msg[:cols]).encode())
        if scene is None:
            if term.wait(0.25):
                return
            continue

        dt = min(0.1, fs - last)
        last = fs
        t = fs - t0
        payload_size = 0
        try:
            res = scene.frame(t, dt)
            if graphics is not None:
                payload_size = graphics.show(res, scene, *size)
                data = b''
            elif scene.text:
                data = enc.text(res[0], res[1], size[0], size[1])
            else:
                data = enc.blocks(res, size[0], size[1], scene.mask)
        except Exception:
            fails += 1
            log_error(name, size, traceback.format_exc())
            if fails >= 3:
                raise SceneFailure('scene crashed 3 times in a row')
            scene = None
            if graphics is not None:
                graphics.close()
            try:
                scene = make_gfx_scene(cls, *geometry, quality, transport) if graphics is not None else make_scene(cls, *size)
            except Exception:
                raise SceneFailure('scene could not be re-created')
            enc.reset()
            continue
        good += 1
        if good > 60:
            fails = 0
        term.write(data)
        nframes += 1
        if nframes % 600 == 0:
            gc.collect()
        work = time.perf_counter() - fs
        period = max(1.0 / scene.fps, work / DUTY, payload_size / _GFX_MAX_BPS)
        if term.wait(period - work):
            return


# ================================================================== test tools
def _headless(name, cols, rows, nframes, dt=None, t_start=0.0, gfx=False):
    """Run a scene without a terminal. Returns (ms_per_frame, bytes_per_frame)."""
    cls = SCENES[name]
    scene = (make_gfx_scene(cls, cols, rows, quality=os.environ.get('FUN_RES', _GFX_DEFAULT),
                            transport='shm' if gfx == 'shm' else 'zlib')
             if gfx else make_scene(cls, cols, rows))
    enc = Encoder()
    graphics = KittyGraphics() if gfx and not cls.text else None
    if gfx == 'shm' and graphics is not None:
        graphics.shm = _PosixShm()
    dt = dt or min(.1, 1.0 / scene.fps)
    t = t_start
    tot = 0.0
    nbytes = 0
    N = scene.W * scene.H
    for i in range(nframes):
        s = time.perf_counter()
        res = scene.frame(t, dt)
        if cls.text:
            chars, fgs = res
            assert len(chars) == N and len(fgs) == N, 'text buffer size'
            data = enc.text(chars, fgs, cols, rows)
        else:
            assert len(res) == N, 'buffer size %d != %d' % (len(res), N)
            if graphics is None:
                data = enc.blocks(res, cols, rows, scene.mask)
            elif graphics.shm is not None:
                try:
                    data = graphics.packet(res, scene.W, scene.H, cols, rows, scene.gfx_dither)
                finally:
                    graphics.shm.clear()
            else:
                data = graphics.packet(res, scene.W, scene.H, cols, rows)
        tot += time.perf_counter() - s
        if i >= 2:
            nbytes += len(data)
        t += dt
    # sanity of colours
    if not cls.text:
        bad = [c for c in res if not (0 <= c <= 0xFFFFFF) or not isinstance(c, int)]
        assert not bad, 'invalid colour value %r' % (bad[:1],)
    return tot / nframes * 1000.0, nbytes / max(1, nframes - 2)


def selftest():
    sizes = [(118, 49), (80, 24), (240, 60), (40, 12), (24, 8)]
    fails = 0
    for name in SCENES:
        for (c, r) in sizes:
            for gfx in (False, True):
                try:
                    _headless(name, c, r, 30, gfx=gfx)
                    _headless(name, c, r, 3, dt=0.1, t_start=100000.0, gfx=gfx)
                except Exception:
                    fails += 1
                    print('%-14s %3dx%-3d %s FAIL\n%s' %
                          (name, c, r, 'gfx' if gfx else 'text/blocks', traceback.format_exc()))
        else:
            pass
        print('%-14s ok' % name if not fails else '%-14s done' % name)
    print('\nselftest:', 'ALL PASSED' if not fails else '%d FAILURES' % fails)
    return 1 if fails else 0


def bench(only=None, gfx=False):
    only = ALIASES.get(only, only)
    if only is not None and only not in SCENES:
        sys.stderr.write(f'extras.py: scene {only!r} is unavailable; use --list for active scenes\n')
        return 1
    modes = (('shm', 'zlib') if _shm_available() else ('zlib',)) if gfx else ('blocks',)
    for mode in modes:
        if gfx:
            print('kitty graphics · ' + mode)
        _bench_mode(only, mode)
    return 0


def _shm_available():
    try:
        shm = _PosixShm()
        shm.write(b'x')
    except OSError:
        return False
    shm.clear()
    return True


def _bench_mode(only, mode):
    print('%-14s %-8s %9s %9s %7s %9s' % ('scene', 'size', 'ms/frame', 'KB/frame', 'fps', 'cpu%@fps'))
    for name in ([only] if only else list(SCENES)):
        for (c, r) in ((118, 49), (240, 60)):
            cls = SCENES[name]
            is_gfx = mode != 'blocks' and not cls.text
            ms, nb = _headless(name, c, r, 40, gfx=mode if is_gfx else False)
            fps = min(24, cls.gfx_fps) if is_gfx else cls.fps
            eff = min(fps, 1000.0 * DUTY / ms) if ms > 0 else fps
            if is_gfx and nb:
                eff = min(eff, _GFX_MAX_BPS / nb)
            print('%-14s %3dx%-4d %9.2f %9.1f %7.1f %8.1f%%' % (name, c, r, ms, nb / 1024.0, eff, ms * eff / 10.0))
    return 0


def gfx_info():
    term = Terminal()
    cols, rows = term.size()
    width, height = term.pixels()
    cw = ch = 0
    if termios and os.isatty(term.in_fd) and os.isatty(term.fd) and KittyGraphics.local_terminal():
        saved = termios.tcgetattr(term.in_fd)
        attrs = termios.tcgetattr(term.in_fd)
        attrs[3] &= ~(termios.ECHO | termios.ICANON)
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        try:
            termios.tcsetattr(term.in_fd, termios.TCSANOW, attrs)
            cw, ch = term.cell_pixels()
        finally:
            termios.tcsetattr(term.in_fd, termios.TCSANOW, saved)
    print(f'Terminal grid: {cols} x {rows} cells')
    print(f'Viewport ioctl: {width} x {height} px' if width and height else 'Viewport ioctl: unavailable')
    if cw and ch:
        print(f'Cell reply: {cw} x {ch} px; cell grid: {cols*cw} x {rows*ch} px')
    else:
        print('Cell reply: unavailable')
    if not width or not height:
        width, height = (cols*cw, rows*ch) if cw and ch else (cols*10, rows*20)
        print(f'Using {width} x {height} px ({"cell reply" if cw and ch else "modeled 10 x 20 px cells"})')
    elif not cw or not ch:
        print(f'Cell size from ioctl: {width/cols:.2f} x {height/rows:.2f} px')
    print(f'Default tier: {_GFX_DEFAULT}. Requested tier: {os.environ.get("FUN_RES", _GFX_DEFAULT)}.')
    def sizes(cls, medium):
        return '  '.join('x'.join(map(str, _gfx_size(cls, cols, rows, width, height, tier, medium)))
                         for tier in _GFX_LEVELS)
    print('                    low        med       high      ultra')
    print('SHM target:         ' + sizes(None, 'shm'))
    print('Compressed target:  ' + sizes(None, 'zlib'))
    print('Per-scene ceilings (SHM; direct transport additionally uses the compressed limit):')
    for name, cls in SCENES.items():
        if cls.text:
            print(f'  {name:<16} text')
        elif cls.__name__ in _GFX_CAPS:
            caps = '/'.join(map(str, _GFX_CAPS[cls.__name__]))
            direct = _GFX_ZLIB_CAPS.get(cls.__name__)
            zlib = f'; compressed ceiling {direct//1000} kpx' if direct else ''
            print(f'  {name:<16} {sizes(cls, "shm")} px ({caps} kpx caps{zlib})')
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        sys.stderr.write(__doc__ + '\nscenes: ' + ', '.join(SCENES) + '\n')
        return 0 if args else 1
    if args[0] == '--list':
        print('\n'.join(SCENES))
        return 0
    if args[0] == '--gfx-info':
        return gfx_info()
    if args[0] == '--selftest':
        return selftest()
    if args[0] in ('--bench', '--bench-gfx'):
        return bench(args[1] if len(args) > 1 else None, gfx=args[0] == '--bench-gfx')
    name = ALIASES.get(args[0], args[0])
    if name not in SCENES:
        sys.stderr.write('extras.py: scene %r is unavailable; use --list for active scenes\n' % args[0])
        return 1
    if not sys.stdout.isatty():
        sys.stderr.write('extras.py: stdout is not a terminal\n')
        return 2
    try:
        run(name)
    except SceneFailure as e:
        sys.stderr.write('extras.py: scene %r failed: %s\n  details: %s\n' % (name, e, LOG_FILE))
        return 3
    except SystemExit:
        raise
    except Exception:
        log_error(name, None, traceback.format_exc())
        sys.stderr.write('extras.py: scene %r crashed; traceback in %s\n' % (name, LOG_FILE))
        return 3
    return 0


# ============================================================================
# SCENES
# ============================================================================

# ------------------------------------------------------------------- aurora
class Aurora(Scene):
    """Layered curtains of northern lights over snowy mountains."""
    fps = 9
    mask = 0xF8F8F8
    gfx_fps = 20
    gfx_pixels = 69000
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.Lmax = L = max(12, int(H * 0.40))
        bg = vgrad(W, H, [(0.0, (3, 4, 16)), (0.45, (6, 10, 34)), (0.75, (9, 24, 50)), (1.0, (16, 40, 66))])
        ph = [rng.uniform(0, 6.3) for _ in range(8)]
        far_c = rgb(9, 17, 36)
        rim_c = rgb(34, 58, 92)
        near_c = rgb(2, 4, 8)
        ridge2 = []
        for x in range(W):
            u = x / W
            ry = int(H * 0.85 - H * (0.05 * sin(u * 9 + ph[0]) + 0.03 * sin(u * 23 + ph[1]) + 0.012 * sin(u * 61 + ph[2])))
            ry = max(0, min(H - 1, ry))
            bg[ry * W + x::W] = [far_c] * (H - ry)
            bg[ry * W + x] = rim_c
        sample_w, sample_h = self.gfx_reference or (W,H)
        edge = [rng.random()*2.4 if x%2 == 0 else 0 for x in range(sample_w)]
        for x in range(W):
            u = x / W
            ry = H * 0.94 - H * (0.03 * sin(u * 14 + ph[3]) + 0.015 * sin(u * 40 + ph[4]))
            ry = int(ry - edge[x*sample_w//W]*self.detail_scale)
            ry = max(0, min(H - 1, ry))
            ridge2.append(ry)
            bg[ry * W + x::W] = [near_c] * (H - ry)
        cx = int(W * 0.72)           # tiny cabin with a warm window
        cy = ridge2[cx] + self.px(2)
        pane = max(1,round(self.detail_scale))
        for dx, c in ((0, rgb(255, 200, 100)), (1, rgb(255, 190, 90))):
            for xx in range(pane):
                for yy in range(pane):
                    plota(bg, W, H, cx + dx*pane+xx, cy+yy, c)
        for dx, dy in ((-1, 0), (2, 0), (0, -1), (1, -1), (0, 1), (1, 1)):
            plota(bg, W, H, cx + dx, cy + dy, rgb(60, 42, 14))
        self.bg = bg
        starc = [rgb(200, 210, 255), rgb(255, 245, 220), rgb(255, 220, 200)]
        self.stars = [(self.detail_coord(W), self.detail_coord(max(1,int(H*.72)), True, max(1,int(sample_h*.72))), rng.choice(starc),
                       rng.uniform(0, 6.3), rng.uniform(0.6, 2.4)) for _ in range(int(self.logical_area // 110))]
        # curtain ramps: [layer][hue variant][intensity level] -> colours top..bottom
        specs = [  # (centre frac, palettes per hue variant, sway speed)
            (0.40, [[(70, 210, 170), (40, 130, 170), (50, 60, 150)],
                    [(110, 220, 170), (60, 150, 190), (60, 70, 160)],
                    [(60, 200, 200), (30, 120, 190), (40, 60, 160)]], 0.8),
            (0.53, [[(150, 255, 150), (60, 230, 110), (30, 140, 120), (40, 60, 150)],
                    [(200, 255, 130), (90, 240, 100), (40, 160, 110), (40, 70, 150)],
                    [(110, 255, 190), (40, 230, 140), (30, 150, 140), (40, 70, 160)]], 1.0),
            (0.57, [[(255, 110, 190), (190, 60, 220), (70, 50, 170)],
                    [(255, 90, 150), (200, 60, 200), (80, 50, 170)],
                    [(230, 110, 230), (150, 70, 230), (60, 50, 180)]], 1.3),
        ]
        self.layers = []
        for li, (f0, pals, spd) in enumerate(specs):
            ramps = []
            for hue in range(17):
                lower = min(1,hue//8)
                upper = lower+1
                weight = (hue-lower*8)*32
                colors = [mix(rgb(*a),rgb(*b),weight) for a,b in zip(pals[lower],pals[upper])]
                stops = [(i/(len(colors)-1),(c>>16,c>>8&255,c&255)) for i,c in enumerate(colors)]
                base = gradient(stops, L)
                per_q = []
                for q in range(8):
                    lv = (q + 1) / 8.0
                    col = []
                    for d in range(L):             # d = distance above the lower edge
                        edge = min(1.0, (d + self.S) / (3 * self.S))
                        prof = exp(-d / (0.30 * L)) * edge
                        col.append(shade(base[min(L - 1, d * 2)],
                                         int(256 * min(1.0, prof * lv * 1.35))))
                    col.reverse()                  # top -> bottom
                    per_q.append(col)
                ramps.append(per_q)
            self.layers.append((f0, 0.07 if li < 2 else 0.05, 0.04, 0.02,
                                rng.uniform(0, 6.3), rng.uniform(0, 6.3), rng.uniform(0, 6.3),
                                rng.uniform(0, 6.3), rng.uniform(0, 6.3), ramps, rng.uniform(0, 6.3), spd))

    def frame(self, t, dt):
        W, H, L = self.W, self.H, self.Lmax
        buf = self.bg[:]
        bg = self.bg
        hymax = int(H * 0.70)
        t *= .78
        for x in range(W):
            u = x / W
            ymin = H
            ymax = 0
            items = []
            for (f0, a1, a2, a3, p0, p1, p2, p3, pr, ramps, hoff, spd) in self.layers:
                by = H * (f0 + a1 * sin(u * 5.0 + t * 0.31 * spd + p0) + a2 * sin(u * 11.0 - t * 0.47 * spd + p1)
                          + a3 * sin(u * 23.0 + t * 0.8 * spd + p2))
                env = 0.5 + 0.5 * sin(u * 3.2 + t * 0.21 * spd + p3)
                ray = 0.5 + 0.5 * sin(x * 0.42 / self.S + t * 1.3 * spd + pr + 2.6 * sin(x * 0.09 / self.S - t * 0.5))
                inten = min(1.0, (0.25 + 0.95 * env) * (0.45 + 0.55 * ray))
                q = int(inten * 7.99)
                if q <= 0:
                    continue
                n = int(L * (0.3 + 0.7 * inten))
                by = int(by)
                if by > hymax:
                    by = hymax
                y1 = by + 1
                y0 = y1 - n
                hq = round(8+8*sin(u*2.1+t*.045+hoff))
                seg = ramps[hq][q][L - n:]
                if y0 < 0:
                    seg = seg[-y0:]
                    y0 = 0
                if not seg:
                    continue
                items.append((y0, y1, seg))
                if y0 < ymin:
                    ymin = y0
                if y1 > ymax:
                    ymax = y1
            if not items:
                continue
            col = bg[ymin * W + x:ymax * W + x:W]
            for (y0, y1, seg) in items:
                o = y0 - ymin
                n = y1 - y0
                col[o:o + n] = map(addp, col[o:o + n], seg)
            buf[ymin * W + x:ymax * W + x:W] = col
        for (x, y, c, p, s) in self.stars:
            f = int(256 * (.65+.27*sin(t*s*.45+p)))
            plota(buf, W, H, x, y, shade(c, f))
        return buf


# ------------------------------------------------------------------ ripples
class Ripples(Scene):
    """Raindrops on a moonlit pond."""
    fps = 15
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (4, 12, 28)), (0.5, (7, 24, 44)), (1.0, (4, 16, 30))])
        mx = int(W * 0.68)
        self.reflection = []
        for y in range(int(H * 0.08), H, self.px(2)):               # moon-path glitter
            w = self.px(3) + int(y * 0.10)
            for _ in range(2):
                dx = int(rng.gauss(0, w))
                ln = rng.randint(self.px(1), self.px(2) + w // 3)
                c = shade(rgb(190, 215, 235), rng.randint(40, 130))
                for k in range(ln):
                    self.reflection.append((mx+dx+k,y,shade(c,128),rng.random()*TAU))
        for _ in range(max(3, int(W / self.S) // 16)):                    # lily pads
            px, py = rng.randrange(W), rng.randrange(int(H * 0.25), H)
            rx = self.px(rng.randint(3, 6))
            ry = max(1, rx // 2)
            ang = rng.uniform(0, 6.3)
            for yy in range(-ry, ry + 1):
                for xx in range(-rx, rx + 1):
                    if (xx / rx) ** 2 + (yy / ry) ** 2 <= 1.0:
                        if abs((atan2(yy,xx)-ang+PI)%TAU-PI) < .29:
                            continue
                        edge = (xx / rx) ** 2 + (yy / ry) ** 2 > 0.6
                        plot(bg, W, H, px + xx, py + yy, rgb(34, 92, 62) if edge else rgb(18, 62, 42))
            if rng.random() < 0.35:
                plot(bg, W, H, px, py, rgb(255, 160, 195))
                plot(bg, W, H, px + 1, py, rgb(255, 215, 230))
        self.bg = bg
        self.rips = []
        self.acc = 0.0
        self.next = 0.2
        self.ring = [shade(rgb(150, 215, 245), int(256 * i / 31.0)) for i in range(32)]

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        for x,y,c,phase in self.reflection:
            drift = round(self.S*(1+2*y/H)*sin(t*.51+phase+y*.15))
            plota(buf,W,H,x+drift,y,shade(c,int(124+83*sin(t*.87+phase))))
        self.acc += dt
        if self.acc >= self.next and len(self.rips) < 9:
            self.acc = 0.0
            self.next = rng.uniform(0.25, 0.9)
            y = rng.uniform(H * 0.2, H * 0.97)
            s = 0.45 + 0.9 * (y / H)
            self.rips.append([rng.uniform(W * 0.04, W * 0.96), y, 0.0, rng.uniform(3.0, 4.6),
                              H * 0.28 * s * rng.uniform(0.7, 1.15)])
        keep = []
        ring = self.ring
        for rp in self.rips:
            rp[2] += dt
            age = rp[2] / rp[3]
            if age >= 1.0:
                continue
            keep.append(rp)
            x0, y0 = rp[0], rp[1]
            amp = (1.0-age)**1.6 * _ambient_smooth(age/.13)
            rr = rp[4] * age ** 0.7
            if rp[2] < 0.15:                                    # the falling drop
                yy = y0 + self.S*(-14 + rp[2] * 90)
                line_add(buf, W, H, x0, yy - self.px(3), x0, yy, shade(0xABC4D7,int(119*sin(PI*rp[2]/.15))))
            for k, (rf, af) in enumerate(((1.0, 1.0), (0.76, 0.6), (0.54, 0.35))):
                r = rr * rf
                if r < 1.2:
                    continue
                n = int(TAU * r * 0.9) + 8
                a = amp * af
                step = TAU / n
                for i in range(n):
                    ang = i * step
                    lf = 0.55 + 0.45 * cos(ang + 2.2)
                    c = ring[int(31 * min(1.0, a * lf))]
                    xx = int(x0 + r * cos(ang))
                    yy = int(y0 + 0.5 * r * sin(ang))
                    if 0 <= xx < W and 0 <= yy < H:
                        j = yy * W + xx
                        q = buf[j]
                        s = q + c
                        m = (s ^ q ^ c) & 0x1010100
                        if m:
                            s = (s | (m - (m >> 8))) & 0xFFFFFF
                        buf[j] = s
        self.rips = keep
        return buf


# --------------------------------------------------------------- fireflies
class Fireflies(Scene):
    """Summer-night meadow with softly pulsing fireflies."""
    fps = 18
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (6, 8, 26)), (0.5, (14, 22, 44)), (0.78, (14, 34, 40)), (1.0, (6, 16, 14))])
        for _ in range(int(self.logical_area // 400)):
            plot(bg, W, H, rng.randrange(W), rng.randrange(int(H * 0.5)), rgb(150, 160, 200))
        # crescent moon
        mx, my, mr = int(W * 0.14), int(H * 0.17), max(3, int(H * 0.06))
        halo = self.px(6)
        for yy in range(-mr - halo, mr + halo + 1):
            for xx in range(-mr - halo, mr + halo + 1):
                d = sqrt(xx * xx + yy * yy)
                d2 = sqrt((xx - mr * 0.55) ** 2 + (yy + mr * 0.2) ** 2)
                if d < mr and d2 >= mr * 0.92:
                    plot(bg, W, H, mx + xx, my + yy, rgb(250, 240, 200))
                elif mr <= d < mr + halo:
                    plota(bg, W, H, mx + xx, my + yy, shade(rgb(70, 70, 40), int(256 * (1 - (d - mr) / halo) ** 2)))
        for layer, (base, amp, col) in enumerate(((0.62, 0.05, (10, 20, 30)), (0.74, 0.06, (7, 15, 20)))):
            ph = rng.uniform(0, 6.3)
            for x in range(W):
                u = x / W
                ry = int(H * base + H * amp * (sin(u * 11 + ph) * 0.6 + sin(u * 29 + ph * 2) * 0.4)) + rng.randint(0, 1)
                if ry < H:
                    bg[ry * W + x::W] = [rgb(*col)] * (H - ry)
        self.bg = bg
        n = max(30, min(150, int(self.logical_area // 170)))
        self.flies = []
        for i in range(n):
            far = rng.random() < 0.3
            self.flies.append((rng.uniform(0, W), rng.uniform(H * 0.28, H * 0.9),
                               self.S * rng.uniform(3, 12), self.S * rng.uniform(2, 8), rng.uniform(0.15, 0.5), rng.uniform(0.2, 0.7),
                               rng.uniform(0, 6.3), rng.uniform(0, 6.3), rng.uniform(2.4, 6.0), rng.uniform(0, 1),
                               far))
        col = rgb(205, 255, 90)
        self.sp_big = make_sprite(col, self.px(3), 8, 2.2)
        self.sp_small = make_sprite(col, self.px(1), 8, 1.5)
        self.blades = []
        x = 0
        while x < W:
            h = rng.randint(max(2, int(H * 0.05)), max(3, int(H * 0.19)))
            self.blades.append((x, h, rng.uniform(0, 6.3), rng.uniform(0.8, 1.8)))
            x += self.px(rng.choice((1, 1, 2)))
        self.gcols = [rgb(5 + k / (2*self.S), 14 + k/self.S, 11 + k/(2*self.S)) for k in range(max(b[1] for b in self.blades) + 1)]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for (hx, hy, a1, a2, w1, w2, p1, p2, per, ph, far) in self.flies:
            x = hx + a1 * sin(t * w1 + p1) + 0.4 * a1 * sin(t * w1 * 2.7 + p2)
            y = hy + a2 * sin(t * w2 + p2) + 0.4 * a2 * sin(t * w2 * 2.3 + p1)
            s = sin(TAU * (t / per + ph))
            if s <= 0:
                s = 0.04
            e = s * s * s
            lv = min(7, int(e * 7.99))
            xi = int(x % W)
            yi = int(y)
            if far:
                stamp(buf, W, H, xi, yi, self.sp_small[lv])
            else:
                stamp(buf, W, H, xi, yi, self.sp_big[lv])
                if lv >= 5:
                    plota(buf, W, H, xi, yi, rgb(255, 255, 200))
        gc_ = self.gcols
        for (x, h, ph, sp) in self.blades:
            for k in range(h):
                off = int(sin(t * sp + ph + x * 0.05 / self.S) * (3.0*self.S) * (k / h) ** 2)
                xx = x + off
                if 0 <= xx < W:
                    buf[(H - 1 - k) * W + xx] = gc_[k]
        return buf


# --------------------------------------------------------------------- snow
class Snow(Scene):
    """Quiet snowfall over a pine forest, with a pale moon."""
    fps = 20
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (6, 10, 30)), (0.55, (18, 30, 66)), (0.85, (60, 84, 128)), (1.0, (110, 130, 170))])
        sample_w, sample_h = self.gfx_reference or (W,H)
        for _ in range(int(self.logical_area // 140)):
            plot(bg, W, H, self.detail_coord(W), self.detail_coord(max(1,int(H*.55)), True, max(1,int(sample_h*.55))), shade(rgb(190, 200, 235), rng.randint(60, 200)))
        mx, my, mr = int(W * 0.8), int(H * 0.2), max(3, int(H * 0.065))
        for yy in range(-mr * 4, mr * 4 + 1):
            for xx in range(-mr * 4, mr * 4 + 1):
                d = sqrt(xx * xx + yy * yy)
                if d < mr:
                    plot(bg, W, H, mx + xx, my + yy, rgb(245, 245, 225))
                elif d < mr * 4:
                    plota(bg, W, H, mx + xx, my + yy, shade(rgb(60, 70, 110), int(256 * (1 - (d - mr) / (3.0 * mr)) ** 2)))
        for (base, amp, col, rim) in ((0.70, 0.12, (36, 52, 92), (120, 140, 180)),
                                      (0.79, 0.08, (24, 38, 72), (90, 110, 150))):
            ph = [rng.uniform(0, 6.3) for _ in range(3)]
            for x in range(W):
                u = x / W
                ry = int(H * base - H * amp * (0.5 * abs(sin(u * 5 + ph[0])) + 0.3 * abs(sin(u * 13 + ph[1])) + 0.2 * sin(u * 31 + ph[2])))
                ry = max(0, min(H - 1, ry))
                bg[ry * W + x::W] = [rgb(*col)] * (H - ry)
                bg[ry * W + x] = rgb(*rim)
        gy = int(H * 0.86)
        for y in range(gy, H):
            f = (y - gy) / max(1, H - gy)
            fill_row(bg, W, y, 0, W, rgb(205 - 50 * f, 220 - 50 * f, 245 - 40 * f))
        sample_ground = int(sample_h*.86)
        for x in range(sample_w):
            if rng.random() < 0.12:
                y = rng.randrange(sample_ground,sample_h)
                plot(bg, W, H, x*W//sample_w, y*H//sample_h, 0xFFFFFF)
        dark = rgb(7, 16, 28)
        lit = rgb(55, 80, 112)
        ref_scale = self.S/self.detail_scale
        pad, offset = max(1,round(3*ref_scale)), max(1,round(4*ref_scale))
        trees = sorted(((rng.randrange(-pad,sample_w+pad)*W//sample_w,
                         rng.randint(int(sample_h*.12),int(sample_h*.30))*H//sample_h,
                         rng.randint(0,offset)*H//sample_h)
                        for _ in range(max(6,int(sample_w/ref_scale)//8))), key=lambda a: a[2])
        mark_interval = max(1,round(3*self.detail_scale))
        for (tx, th, off) in trees:
            base = gy + off
            tiers = 4
            for k in range(tiers):
                top = base - th + int(k * th * 0.2)
                bot = base - int(th * (tiers - 1 - k) * 0.17) - int(th * 0.05)
                wmax = max(2, int(th * (0.26 + 0.07 * k)))
                for y in range(top, bot):
                    half = int(wmax * (y - top) / max(1, bot - top))
                    if 0 <= y < H:
                        x0 = max(0, tx - half)
                        x1 = min(W, tx + half + 1)
                        fill_row(bg, W, y, x0, x1, dark)
                        if 0 <= tx - half < W and (y - top) % mark_interval == 0:
                            bg[y * W + tx - half] = lit
            for y in range(base - self.px(3), min(H, base + self.px(2))):
                plot(bg, W, H, tx, y, rgb(30, 20, 18))
        # A single lit pane at the foot of the trees.
        wx, wy = round(W*.29), round(H*.80)
        pane_w = max(2, self.px(1.8))
        pane_h = max(2, self.px(1.35))
        spill = make_sprite(0x9A441E, max(3, self.px(2.6)), 1, 2.7)[0]
        stamp(bg, W, H, wx, wy, spill)
        for y in range(wy-pane_h//2, wy-pane_h//2+pane_h):
            for x in range(wx-pane_w//2, wx-pane_w//2+pane_w):
                plot(bg, W, H, x, y, 0xE7AC61 if y == wy-pane_h//2 else 0xB96936)
        self.bg = bg
        n = max(60, int(self.logical_area // 55))
        layers = ((0.50, 7.0, 3.0, rgb(115, 135, 175)), (0.33, 15.0, 5.0, rgb(200, 215, 240)),
                  (0.17, 26.0, 8.0, rgb(255, 255, 255)))
        self.flakes = []
        for i in range(n):
            li = 0 if i < n * 0.5 else (1 if i < n * 0.83 else 2)
            self.flakes.append([rng.uniform(0, W), rng.uniform(0, H), li, rng.uniform(0, 6.3),
                                rng.uniform(1.0, 2.2), rng.uniform(0.85, 1.15)])
        self.layers = layers
        self.flake_glow = make_sprite(0xCAD8EF,self.px(2),4,1.45)[-1] if self.gfx else None

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        wind = 6.0 * sin(t * 0.23) + 4.0 * sin(t * 0.51 + 1.3)
        layers = self.layers
        for f in self.flakes:
            li = f[2]
            vy, amp, col = layers[li][1], layers[li][2], layers[li][3]
            f[3] += dt * f[4]
            f[1] += vy * f[5] * dt * self.S
            f[0] += (wind * (0.4 + 0.5 * li) + sin(f[3]) * amp) * dt * self.S
            if f[1] >= H:
                f[1] -= H + self.px(4)
                f[0] = rng.uniform(0, W)
            x = int(f[0]) % W
            y = int(f[1])
            if 0 <= y < H:
                buf[y * W + x] = col
                if self.flake_glow and li==2:
                    stamp(buf,W,H,x,y,self.flake_glow)
                elif li == 2:
                    xr = (x + 1) % W
                    buf[y * W + xr] = col
                    if y + 1 < H:
                        buf[(y + 1) * W + x] = col
                        buf[(y + 1) * W + xr] = shade(col, 170)
        return buf


# --------------------------------------------------------------------- lava
class Lava(Scene):
    """An amber-wax lava lamp in a dark brass case."""
    fps = 10
    mask = 0xF8F8F8
    gfx_fps = 20
    gfx_pixels = 68000
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.left = max(0, round(W*.5-min(W*.48,H*.235)))
        self.top = round(H*.235)
        self.width = W-2*self.left
        self.height = round(H*.765)-self.top
        width,height = self.width,self.height
        self.sw,self.sh = _ambient_grid(width,height,2)
        self.pal = _ambient_palette(((0,0x100D21),(.35,0x251329),(.47,0x431B30),
                                     (.54,0xA72E21),(.58,0xDC5529),(.75,0xF88B3B),
                                     (1,0xFFCA76)))
        self.bg = []
        for y in range(H):
            v = y/H
            for x in range(W):
                u = (x-W*.5)/H
                spill = exp(-((u/.44)**2+((v-.73)/.39)**2)*1.55)
                wall = shade(0x1D1F2A,int(124+56*v))
                self.bg.append(addp(wall,shade(0xB54D25,int(spill*90))))
        self.glass = []
        for y in range(height):
            u = y/max(1,height-1)
            taper = .69+.20*_ambient_smooth(u/.91)
            shoulder = .19*(1-_ambient_smooth(u/.16))+.17*_ambient_smooth((u-.88)/.12)
            half = max(1,round(width*(taper-shoulder)*.5))
            left,right = width//2-half,min(width,width//2+half)
            rim = max(1,round(self.S*.85))
            row = (self.top+y)*W+self.left
            for x in range(left,right):
                if x-left < rim or right-1-x < rim:
                    warm = int(128+87*u)
                    self.bg[row+x] = shade(0x917063 if x-left < rim else 0x674A52,warm)
            lo,hi = left+rim,right-rim
            # The mask uses contiguous spans so clipping never touches the wall or metal.
            if lo<hi:
                self.glass.append((y,lo,hi))
        self.glints = []
        for y,lo,hi in self.glass:
            u = y/max(1,height-1)
            strip = min(hi-lo,max(1,round(1.4*self.S)))
            strength = int(46*sin(PI*u)**.65)
            for d in range(strip):
                self.glints.append(((self.top+y)*W+self.left+lo+d,
                                    shade(0xE2AAC5,strength//(d+1))))
        self._brass(round(H*.155),self.top, .22,.31)
        self._brass(round(H*.765),round(H*.917), .36,.47)
        self.blobs = [(rng.uniform(-.23,.23),rng.uniform(.03,.14),
                       rng.uniform(.075,.16),rng.random()*TAU,rng.random()*TAU)
                      for _ in range(7)]

    def _brass(self, top, bottom, narrow, wide):
        W = self.W
        for y in range(top,bottom):
            v = (y-top)/max(1,bottom-top-1)
            half = round(self.width*(narrow+(wide-narrow)*v))
            for dx in range(-half,half+1):
                if 0 <= W//2+dx < W:
                    u = dx/max(1,half)
                    curve = sqrt(max(0.,1-u*u))
                    spec = exp(-((u+.36)/.27)**2)
                    seam = .62 if y in (top,bottom-1) else 1.
                    lighting = int(seam*(45+70*curve+65*spec))
                    self.bg[y*W+W//2+dx] = shade(0xAB7843,lighting)

    def frame(self,t,dt):
        W,sw,sh = self.W,self.sw,self.sh
        heat = exp(-((t-300)/146)**2)
        travel = .19*t+102*(1+math.erf((t-300)/146))
        field = []
        for y in range(sh):
            depth = y/max(1,sh-1)
            field.extend([1.64*max(0.,(depth-.82)/.18)**2]*sw)
        for drift,rate,radius,phase,sway in self.blobs:
            lift = .5-.5*cos(travel*rate+phase)
            x = sw*(.5+drift+.13*sin(travel*.102+sway))
            y = sh*(.91-lift*(.29+.61*heat))
            r = max(1.1,min(sw,sh)*radius*2.1)
            ir = 1/(r*r)
            lo,hi = max(0,int(x-r)),min(sw,int(x+r)+1)
            xd = [(j-x)**2*ir for j in range(lo,hi)]
            for yy in range(max(0,int(y-r)),min(sh,int(y+r)+1)):
                a = 1-(yy-y)**2*ir
                base = yy*sw+lo
                for j,b in enumerate(xd):
                    k = a-b
                    if k>0:
                        field[base+j] += 2.38*k*k
        indices = [min(255,int(255*v/(.97+v))) for v in field]
        wax = up2(indices,sw,sh,self.width,self.height,self.pal)
        buf = self.bg[:]
        for row,lo,hi in self.glass:
            source = row*self.width
            dest = (self.top+row)*W+self.left
            buf[dest+lo:dest+hi] = wax[source+lo:source+hi]
        for i,color in self.glints:
            buf[i] = addp(buf[i],color)
        return buf


# -------------------------------------------------------------------- waves
class Waves(Scene):
    """Layered ocean swells at sunset."""
    fps = 16
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        hy = int(H * 0.50)
        self.hy = hy
        sky = gradient([(0.0, (18, 10, 52)), (0.35, (80, 20, 110)), (0.65, (210, 60, 110)),
                        (0.85, (255, 140, 90)), (1.0, (255, 210, 140))], hy)
        bg = []
        for c in sky:
            bg += [c] * W
        bg += [rgb(255, 210, 140)] * (W * (H - hy))
        self.sx = int(W * 0.68)
        sr = max(3, int(H * 0.11))
        for y in range(max(0, hy - sr * 3), hy):
            for x in range(max(0, self.sx - sr * 3), min(W, self.sx + sr * 3)):
                d = hypot(x - self.sx, y - (hy - sr * 0.2))
                j = y * W + x
                if d < sr:
                    bg[j] = rgb(255, 238, 180)
                elif d < sr * 3:
                    bg[j] = addp(bg[j], shade(rgb(255, 150, 90), int(256 * (1 - (d - sr) / (2.0 * sr)) ** 2 * 0.8)))
        for _ in range(6):                                          # streaky clouds
            cx, cy = rng.uniform(0, W), rng.uniform(H * 0.06, H * 0.4)
            rx, ry = rng.uniform(W * 0.08, W * 0.22), rng.uniform(0.8, 1.8)*self.S
            for y in range(int(cy-self.px(3)),int(cy+self.px(4))):
                for x in range(int(cx - rx), int(cx + rx)):
                    q = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                    if q < 1 and 0 <= x < W and 0 <= y < hy:
                        j = y * W + x
                        bg[j] = mix(bg[j], rgb(255, 170, 160), int(110 * (1 - q)))
        self.bg = bg
        n = 10
        self.layers = []
        for i in range(n):
            d = i / (n - 1)
            base = hy + self.px(2) + (H - hy - self.px(2)) * d ** 1.35
            col = mix(rgb(226, 112, 128), rgb(6, 26, 58), int(256 * d ** 0.7))
            crest = mix(col, rgb(255, 205, 175), int(256 * (0.42 * (1 - d) + 0.12)))
            ramp = [crest]*self.px(2) + [mix(crest, col, 128)]*self.px(1) + [shade(col, int(256 * (1.0 - 0.35 * min(1.0, k / (28.0*self.S))))) for k in range(H)]
            self.layers.append((base, (0.006 + 0.05 * d) * H, (0.09 * (1 - 0.7 * d) + 0.02)/self.S, (0.7 + 1.0 * d) * (1 if i % 2 else -1),
                                rng.uniform(0, 6.3), ramp, d))

    def frame(self, t, dt):
        W, H, hy, rng = self.W, self.H, self.hy, self.rng
        buf = self.bg[:]
        sx = self.sx
        for (base, amp, k, w, ph, ramp, d) in self.layers:
            for x in range(W):
                y = int(base + amp * (sin(k * x + w * t + ph) + 0.45 * sin(2.1 * k * x - 1.3 * w * t + 2 * ph)))
                if y >= H:
                    continue
                if y < hy:
                    y = hy
                n = H - y
                buf[y * W + x::W] = ramp[:n]
        for li, (base, amp, k, w, ph, ramp, d) in enumerate(self.layers):
            gw = int(self.S*(3+12*d))
            for x in range(sx-gw,sx+gw,self.px(1)):
                if 0 <= x < W and (sin(x/self.S*1.3+t*2.1+li*.83)>.61 if self.gfx else rng.random() < .32):
                    y = int(base + amp * (sin(k * x + w * t + ph) + 0.45 * sin(2.1 * k * x - 1.3 * w * t + 2 * ph)))
                    if hy <= y < H:
                        buf[y * W + x] = rgb(255, 225, 170)
        return buf


# ------------------------------------------------------------------- galaxy
class Galaxy(Scene):
    """Slowly rotating spiral galaxy over a twinkling star field."""
    fps = 12
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.cx, self.cy = W * .45, H * .53
        self.R = 1.30 * min(W * 0.46, H * 0.47)
        bg = vgrad(W, H, [(0.0, (1, 1, 6)), (0.5, (3, 4, 14)), (1.0, (1, 1, 6))])
        self.bgstars = []
        for _ in range(int(self.logical_area // 60)):
            x, y = self.detail_coord(W), self.detail_coord(H, True)
            c = shade(rgb(*rng.choice(((200, 210, 255), (255, 245, 225), (255, 215, 190)))), rng.randint(40, 230))
            self.bgstars.append((x, y, c, rng.uniform(0, 6.3), rng.uniform(0.5, 3.0), rng.random() < 0.18))
        for (x, y, c, p, s, tw) in self.bgstars:
            if not tw:
                bg[y * W + x] = c
        self.bgtw = [s for s in self.bgstars if s[5]]
        cr = max(3, int(self.R * 0.22))                                    # core glow
        for y in range(-cr * 2, cr * 2 + 1):
            for x in range(-cr * 2, cr * 2 + 1):
                d = hypot(x, y) / cr
                if d < 2:
                    plota(bg, W, H, int(self.cx) + x, int(self.cy) + y, shade(rgb(255, 215, 150), int(256 * 0.75 * (1 - d / 2) ** 2.4)))
        self.bg = bg
        stars = []
        for _ in range(1800 if not self.gfx else min(3050,int(1800*sqrt(self.S/self.detail_scale)))):
            k = rng.random()
            if k < 0.52:                              # spiral arms
                r = 0.10 + 0.9 * rng.random() ** 0.8
                arm = 0 if rng.random() < 0.5 else 1
                th = arm * PI + 2.2 * math.log(1 + r * 8.0) + rng.gauss(0, 0.20 + 0.16 * (1 - r))
                tight = abs(th - (arm * PI + 2.2 * math.log(1 + r * 8.0)))
                if rng.random() < 0.07 and tight < 0.15:
                    col = rgb(255, 120, 175)
                else:
                    col = rgb(175, 205, 255)
                lv = (0.30 + 0.7 * rng.random() ** 2) * (1.0 - 0.55 * r)
            elif k < 0.78:                            # diffuse disc
                r = rng.random() ** 0.85
                th = rng.uniform(0, TAU)
                col = rgb(235, 215, 195)
                lv = (0.18 + 0.4 * rng.random()) * (1.0 - 0.6 * r)
            else:                                     # bulge
                r = abs(rng.gauss(0, 0.11))
                th = rng.uniform(0, TAU)
                col = rgb(255, 225, 170)
                lv = .24+.52*rng.random()
            stars.append((r * cos(th), r * sin(th), shade(col, int(256 * lv)), lv))
        self.stars = stars
        self.big = [s for s in stars if s[3] > .63][:170]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for (x, y, c, p, s, tw) in self.bgtw:
            buf[y * W + x] = shade(c, int(256 * (0.35 + 0.65 * (0.5 + 0.5 * sin(t * s + p)))))
        th = t * 0.10
        psi = 0.5 + 0.35 * sin(t * 0.023)
        ci = 0.44 + 0.08 * sin(t * 0.017)
        ct, st = cos(th), sin(th)
        cp, sp = cos(psi), sin(psi)
        m00 = cp * ct - sp * ci * st
        m01 = -cp * st - sp * ci * ct
        m10 = sp * ct + cp * ci * st
        m11 = -sp * st + cp * ci * ct
        cx, cy, R = self.cx, self.cy, self.R
        # Grow subpixel coverage with output area while keeping each star's core color.
        detail = self.detail_scale
        rim = min(132, round(64*max(0., detail**2-1.)))
        corner = min(104, round(78*max(0., detail-1.45)))
        for (bx, by, c, lv) in self.stars:
            x = int(cx + R * (m00 * bx + m01 * by))
            y = int(cy + R * (m10 * bx + m11 * by))
            if 0 <= x < W and 0 <= y < H:
                i = y * W + x
                a = buf[i]
                s = a + c
                m = (s ^ a ^ c) & 0x1010100
                if m:
                    s = (s | (m - (m >> 8))) & 0xFFFFFF
                buf[i] = s
                if rim:
                    _gfx_point_rim(buf,W,H,x,y,shade(c,rim))
                if corner:
                    soft = shade(c,corner)
                    plota(buf,W,H,x-1,y-1,soft)
                    plota(buf,W,H,x+1,y-1,soft)
                    plota(buf,W,H,x-1,y+1,soft)
                    plota(buf,W,H,x+1,y+1,soft)
        halo = self.px(1)
        for (bx, by, c, lv) in self.big:
            x = int(cx + R * (m00 * bx + m01 * by))
            y = int(cy + R * (m10 * bx + m11 * by))
            g = shade(c, 70)
            plota(buf, W, H, x + halo, y, g)
            plota(buf, W, H, x - halo, y, g)
            plota(buf, W, H, x, y + halo, g)
            plota(buf, W, H, x, y - halo, g)
        return buf


# ------------------------------------------------------------------- plexus
class Plexus(Scene):
    """Drifting glowing nodes joined by fading links, with a roaming hub."""
    fps = 12
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = []
        cx, cy = W / 2.0, H / 2.0
        md = hypot(cx, cy)
        for y in range(H):
            for x in range(W):
                d = hypot(x - cx, y - cy) / md
                bg.append(rgb(11 - 9 * d, 15 - 12 * d, 38 - 30 * d))
        self.bg = bg
        nx = max(5,min(11,int(W/self.S)//14))
        ny = max(4,min(8,int(H/self.S)//14))
        self.nx = nx
        self.pts = [(W*(x+rng.uniform(.25,.75))/nx,H*(y+rng.uniform(.25,.75))/ny,
                     rng.random()*TAU,rng.uniform(.13,.30))
                    for y in range(ny) for x in range(nx)]
        self.pal = _ambient_palette(((0,0x5486A4),(.48,0xB58CC5),(1,0xBA8A76)),64)
        self.link = max(6.*self.S,min(25.*self.S,hypot(W/nx,H/ny)*1.28))
        self.swing = min(W/nx,H/ny)*.64
        self.sp = make_sprite(0x70A6C2, self.px(2), 8, 2.0)
        self.hubsp = make_sprite(rgb(190, 215, 255), self.px(4), 8, 2.4)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        hx = W * (.5 + .34 * sin(t * .11))
        hy = H * (.5 + .31 * sin(t * .093 + 1))
        pts = []
        for x,y,a,speed in self.pts:
            wave = t*speed+a
            motion = self.swing * (.78+.22*sin(t*.021+a))
            x += sin(wave)*motion
            y += cos(wave*.79+a)*motion
            dx,dy = hx-x,hy-y
            bend = .24*exp(-(dx*dx+dy*dy)/(2.5*self.link**2))
            pts.append((x+dx*bend,y+dy*bend,a))
        pal = self.pal
        np_ = len(pal)
        thr2 = self.link * self.link
        n = len(pts)
        cols = [pal[int((np_-1)*(.5+.5*sin(t*.045+p[2])))] for p in pts]
        for i in range(n):
            pi = pts[i]
            xi, yi = pi[0], pi[1]
            for j in range(i+1,min(i+2*self.nx+1,n)):
                pj = pts[j]
                dx = pj[0] - xi
                dy = pj[1] - yi
                d2 = dx * dx + dy * dy
                if d2 < thr2:
                    a = 1.0 - d2 / thr2
                    c = shade(mix(cols[i], cols[j], 128), int(111 * a))
                    line_add(buf, W, H, xi, yi, pj[0], pj[1], c)
        hub2 = (self.link * 1.5) ** 2
        for i in range(n):
            pi = pts[i]
            dx = hx - pi[0]
            dy = hy - pi[1]
            d2 = dx * dx + dy * dy
            if d2 < hub2:
                a = 1.0 - d2 / hub2
                line_add(buf, W, H, hx, hy, pi[0], pi[1], shade(0x87A4CA, int(112 * a)))
        for i in range(n):
            p = pts[i]
            stamp(buf, W, H, int(p[0]), int(p[1]), self.sp[5])
            plota(buf, W, H, int(p[0]), int(p[1]), cols[i])
        stamp(buf, W, H, int(hx), int(hy), self.hubsp[3])
        return buf


# -------------------------------------------------------------------- spiro
class Spiro(Scene):
    """Three nested hypotrochoid rosettes, counter-rotating, with flowing colour."""
    fps = 14
    mask = 0xF8F8F8

    def setup(self):
        W, H = self.W, self.H
        self.pal = _ambient_palette(((0,0x526B92),(.34,0x4DADA8),(.68,0xA977AA),
                                     (1,0xE8AE78)),128)
        self.R = min(W * 0.5, H * 0.5) * 0.93
        self.bg = vgrad(W, H, [(0.0, (5, 3, 14)), (0.5, (9, 5, 22)), (1.0, (5, 3, 14))])
        self.curves = [(7, 3, 1.00, 1.0), (9, 4, 0.72, -1.3), (8, 3, 0.46, 0.8)]   # (R, r, scale, spin)
        self.geometry = []
        for outer,inner,_,_ in self.curves:
            count = min(460,max(150,int(7*self.R)))
            period = TAU*inner
            k = (outer-inner)/inner
            self.geometry.append([(cos(a)*(outer-inner),sin(a)*(outer-inner),cos(k*a),-sin(k*a))
                                  for a in (i*period/count for i in range(count+1))])

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        cx, cy = W / 2.0, H / 2.0
        stroke = _gfx_line_set if self.gfx else line_set
        pal = self.pal
        for ci, (Rr, r, scl, spin) in enumerate(self.curves):
            d = r*(.93+.42*sin(t*.057+ci*2.1)+.12*sin(t*.021+ci))
            sc = self.R * scl / ((Rr - r) + d)
            shape = self.geometry[ci]
            n = len(shape)-1
            rot = t * .092 * spin
            cr, sr = cos(rot), sin(rot)
            px = py = None
            for i,(u,v,dx,dy) in enumerate(shape):
                x,y = u+d*dx,v+d*dy
                xx = cx + (x * cr - y * sr) * sc * 1.0
                yy = cy + (x * sr + y * cr) * sc * 1.0
                if px is not None:
                    color = pal[int(63.5+63.5*sin(i*TAU/n+t*.071+ci*2))]
                    stroke(buf,W,H,px,py,xx,yy,shade(color,211-ci*20))
                px, py = xx, yy
        return buf


# ------------------------------------------------------------------- school
class School(Scene):
    """A school of fish with real flocking, over light shafts and plankton."""
    fps = 15

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W,H,((0,(47,118,134)),(.10,(14,79,108)),(.46,(5,40,73)),(1,(2,11,31))))
        for y in range(max(1,round(H*.20))):
            for x in range(W):
                u,v = x/W,y/H
                wave = .5+.5*sin(39*u+92*v+1.3*sin(15*u-64*v))
                glow = int(115*wave**6*exp(-v*17))
                self.bg[y*W+x] = addp(self.bg[y*W+x],shade(0xB7ECD1,glow))
        self.kelp = [(W*u,H*h,rng.random()*TAU,depth)
                     for u,h,depth in ((.045,.49,0),(.111,.29,1),(.018,.36,2),
                                       (.918,.36,1),(.969,.63,0),(.992,.47,2))]
        for i in range(5):                                                  # light shafts
            x0 = rng.uniform(W * 0.1, W * 0.9)
            sl = rng.uniform(0.2, 0.5)
            wd = rng.uniform(3, 8)*self.S
            for y in range(int(H * 0.75)):
                xc = x0 + y * sl
                a = (1 - y / (H * 0.75)) * 0.10
                for x in range(int(xc - wd), int(xc + wd)):
                    if 0 <= x < W:
                        j = y * W + x
                        self.bg[j] = addp(self.bg[j], shade(rgb(120, 190, 220), int(256 * a * (1 - abs(x - xc) / wd))))
        n = max(30, min(90, int(self.logical_area // 130)))
        self.fish = []
        for i in range(n):
            a = rng.uniform(0, TAU)
            self.fish.append([rng.uniform(W * 0.3, W * 0.7), rng.uniform(H * 0.3, H * 0.7),
                              cos(a)*8*self.S, sin(a)*6*self.S, rng.uniform(0, 6.3), rng.uniform(0.8, 1.2), 0.])
        self.motes = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(0.5, 2.0), rng.uniform(0, 6.3)) for _ in range(int(self.logical_area // 110))]
        self.pal = (0xD8B478,0xBC8057,0xDECDA0,0x82BCCC)
        self.silver = 0xD5EEED

    def _seaweed(self,buf,t):
        W,H = self.W,self.H
        for origin,height,phase,depth in self.kelp:
            ink = (0x061D29,0x092734,0x0E3640)[depth]
            previous = None
            for k in range(13):
                u = k/12
                x = origin+sin(t*.34+phase+u*3.4)*height*.27*u
                y = H-1-u*height
                if previous:
                    line_set(buf,W,H,*previous,x,y,ink)
                    if self.S>1.2:
                        line_set(buf,W,H,previous[0]+self.S*.55,previous[1],x+self.S*.55,y,ink)
                previous = x,y
                if 1<k<12 and k%2==0:
                    side = -1 if k%4==0 else 1
                    reach = side*height*(.31-.18*u)
                    old = None
                    for j in range(6):
                        v = j/5
                        xx = x+reach*v+sin(t*.34+phase+v*2)*height*.10*u*v
                        yy = y-height*(.13*v+.065*sin(v*PI))
                        if old:
                            leaf = max(1,round(height*.036*sin(v*PI)))
                            _ambient_disc(buf,W,H,xx,yy,leaf,ink)
                            line_set(buf,W,H,*old,xx,yy,ink)
                        old = xx,yy

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        self._seaweed(buf,t)
        for (x, y, s, p) in self.motes:
            xx = int(x + 3*self.S*sin(t * 0.3 + p)) % W
            yy = int((y - t * s * 1.5*self.S) % H)
            plota(buf, W, H, xx, yy, rgb(30, 60, 80))
        fish = self.fish
        n = len(fish)
        gx = hx = 0.0
        gy = hy = 0.0
        for f in fish:
            gx += f[0]
            gy += f[1]
            hx += f[2]
            hy += f[3]
        gx /= n
        gy /= n
        hx /= n
        hy /= n
        px = W*(.5+.116*sin(t*.094))
        py = H*(.46+.126*sin(t*.131+1))
        margin_x,margin_y = W*.24,H*.22
        scale = self.S
        base_sq = scale*scale
        choose_distance, minimum_distance = 60*base_sq,2*base_sq
        speed_limit = min(10.8*scale,max(4.*scale,min(W,H)*.21))
        for i in range(n):
            f = fish[i]
            ax = (gx - f[0]) * 0.10 + (hx - f[2]) * 0.9 + (px - f[0]) * 0.22
            ay = (gy - f[1])*.13+(hy-f[3])*.96+(py-f[1])*.24
            ax += 3.4*(max(0.,margin_x-f[0])-max(0.,f[0]-W+margin_x))
            ay += 3.1*(max(0.,margin_y-f[1])-max(0.,f[1]-H+margin_y))
            for j in range(i + 1, min(n, i + 12)):                    # cheap separation on a window
                o = fish[j]
                dx = f[0] - o[0]
                dy = f[1] - o[1]
                d2 = dx * dx + dy * dy
                if d2 < choose_distance and d2 > 1e-3:
                    k = 62.0*base_sq/max(minimum_distance,d2)
                    ax += dx * k
                    ay += dy * k
                    o[2] -= dx * k * dt
                    o[3] -= dy * k * dt
            vx,vy = f[2],f[3]
            f[2] += ax * dt
            f[3] += ay * dt
            turn = abs(vx*f[3]-vy*f[2])/max(base_sq,vx*vx+vy*vy)
            f[6] = min(1.,max(0.,f[6]-2.4*dt)+max(0.,turn-.052)*2.3)
            sp = sqrt(f[2] * f[2] + f[3] * f[3]) + 1e-6
            mx = speed_limit*f[5]
            if sp > mx:
                f[2] *= mx / sp
                f[3] *= mx / sp
            elif sp < 3*scale:
                f[2] *= 3*scale/sp
                f[3] *= 3*scale/sp
            f[0] += f[2] * dt
            f[1] += f[3] * dt * 0.8
            f[4] += dt * (4 + sp * 0.5/scale)
            for axis,limit in enumerate((W,H)):
                if f[axis] < 2 or f[axis] > limit-3:
                    f[axis] = max(2.,min(limit-3.,f[axis]))
                    f[axis+2] *= -.45
        for i in range(n):
            f = fish[i]
            ang = atan2(f[3], f[2])
            ca, sa = cos(ang), sin(ang)
            light = (.48+.52*abs(ca))*(1-.40*f[1]/H)
            col = mix(self.pal[i & 3],self.silver,int(256*light*f[6]))
            wag = sin(f[4]) * .7
            if self.gfx:
                x,y = f[:2]
                line_set(buf,W,H,x-1.7*scale*ca,y-1.7*scale*sa,
                         x+2.3*scale*ca,y+2.3*scale*sa,col)
                _ambient_disc(buf,W,H,x+.3*scale*ca,y+.3*scale*sa,self.px(1),shade(col,212))
                for side in (-1,1):
                    wing = (wag+side*.72)*scale
                    _gfx_line_set(buf,W,H,x-1.3*scale*ca,y-1.3*scale*sa,
                                  x-2.9*scale*ca-wing*sa,y-2.9*scale*sa+wing*ca,shade(col,166))
                continue
            for (u, v, k) in ((2.2, 0, 256), (1.4, 0, 256), (0.6, 0, 240), (-0.2, 0.0, 220), (-1.0, 0.0, 200), (0.4, -0.7, 190), (0.4, 0.7, 190), (-0.4, -0.6, 170), (-0.4, 0.6, 170)):
                xx = int(f[0] + u * ca - v * sa)
                yy = int(f[1] + u * sa + v * ca)
                plot(buf, W, H, xx, yy, shade(col, k))
            tx, ty = f[0] - 1.8 * ca, f[1] - 1.8 * sa
            for s_ in (-1, 0, 1):
                xx = int(tx - 1.0 * ca - (wag + s_ * 0.8) * -sa)
                yy = int(ty - 1.0 * sa + (wag + s_ * 0.8) * ca)
                plot(buf, W, H, xx, yy, shade(col, 160))
        return buf


# ------------------------------------------------------------------ mystify
class Mystify(Scene):
    """Classic Mystify: bouncing polygons trailing rainbow echoes."""
    fps = 15
    mask = 0xF8F8F8
    gfx_pixels = 68000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.polys = []
        for p in range(2):
            vs = []
            for i in range(4):
                a = rng.uniform(0, TAU)
                s = rng.uniform(8,16) * min(1.2,H/(90*self.S))*self.S
                vs.append([rng.uniform(0, W - 1), rng.uniform(0, H - 1), cos(a) * s * 1.6, sin(a) * s])
            self.polys.append(vs)
        self.hist = [[] for _ in self.polys]
        self.pal = _ambient_palette(((0,0x366090),(.46,0x676998),(.78,0xA88173),(1,0xCB9E77)),64)
        self.bg = [rgb(2, 2, 8)] * (W * H)
        self.n = 19 if self.gfx else 14

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for pi, vs in enumerate(self.polys):
            for v in vs:
                v[0] += v[2] * dt
                v[1] += v[3] * dt
                if v[0] < 0:
                    v[0] = 0
                    v[2] = -v[2]
                elif v[0] > W - 1:
                    v[0] = W - 1
                    v[2] = -v[2]
                if v[1] < 0:
                    v[1] = 0
                    v[3] = -v[3]
                elif v[1] > H - 1:
                    v[1] = H - 1
                    v[3] = -v[3]
            h = self.hist[pi]
            h.append([(v[0], v[1]) for v in vs])
            if len(h) > self.n:
                h.pop(0)
            for k, poly in enumerate(h):
                lv = (k + 1) / len(h)
                color = self.pal[int(31.5+31.5*sin(t*.061+pi*2.4-lv*1.2))]
                c = shade(color,int(184*lv**2.15))
                m = len(poly)
                for a in range(m):
                    x0, y0 = poly[a]
                    x1, y1 = poly[(a + 1) % m]
                    line_set(buf, W, H, x0, y0, x1, y1, c)
        return buf


# -------------------------------------------------------------------- donut
class Donut(Scene):
    """A glazed ring tips gently above a soft studio-floor shadow."""
    fps = 14
    mask = 0xF8F8F8
    gfx_fps = 20
    gfx_pixels = 57500

    def setup(self):
        W, H = self.W, self.H
        self.bg = vgrad(W,H,((0,(10,7,21)),(.54,(26,14,34)),(.77,(40,26,44)),(1,(24,17,34))))
        for y in range(round(H*.63),round(H*.91)):
            for x in range(W):
                d = ((x-W*.53)/(min(W,H)*.36))**2+((y-H*.777)/(H*.059))**2
                if d<3.2:
                    i = y*W+x
                    self.bg[i] = shade(self.bg[i],int(256-136*exp(-1.4*d)))
        self.ramp = gradient([(0.0, (22, 8, 44)), (0.3, (150, 40, 120)), (0.62, (255, 120, 92)), (0.9, (255, 220, 190)), (1.0, (255, 250, 235))], 64)
        self.hw = W // 2
        self.hh = H // 2
        self.sc = min(self.hw * .42 / 3.4, self.hh * .45 / 3.0)
        n1 = int(min(208,max(100,self.hw * 2.9)))
        n2 = min(56,max(32,self.hh+4))
        if self.gfx:
            n1,n2 = 44,18
            self.faces = []
            for row in range(n1):
                for col in range(n2):
                    a,b = row*n2+col,((row+1)%n1)*n2+col
                    c,d = row*n2+(col+1)%n2,((row+1)%n1)*n2+(col+1)%n2
                    self.faces.extend(((a,b,c),(c,b,d)))
        self.pts = []
        for i in range(n1):
            th = i * TAU / n1
            ct, st = cos(th), sin(th)
            for j in range(n2):
                ph = j * TAU / n2
                cp, sp = cos(ph), sin(ph)
                self.pts.append(((2 + cp * 0.95) * ct, (2 + cp * 0.95) * st, sp * 0.95, cp * ct, cp * st, sp, 2*cp+.95))

    def frame(self, t, dt):
        W, H, hw, hh = self.W, self.H, self.hw, self.hh
        buf = self.bg[:]
        A = .49+.16*sin(t*.21)
        B = .33*sin(t*.147+.37)
        ca, sa = cos(A), sin(A)
        cb, sb = cos(B), sin(B)
        lx, ly, lz = -0.45, -0.6, -0.66
        ln = sqrt(lx * lx + ly * ly + lz * lz)
        lx /= ln
        ly /= ln
        lz /= ln
        hx, hy, hz = lx, ly, lz - 1
        hn = sqrt(hx * hx + hy * hy + hz * hz)
        hx /= hn
        hy /= hn
        hz /= hn
        cx, cy, sc = hw / 2.0, hh / 2.0, self.sc
        ramp = self.ramp
        if self.gfx:
            return self._mesh(buf,ca,sa,cb,sb,(lx,ly,lz),(hx,hy,hz))
        zb = [1e9] * (hw * hh)
        hit = {}
        for (x, y, z, nx, ny, nz, surface) in self.pts:
            # A cheap normal test rejects the hidden half before projection.
            nz1 = ny * sa + nz * ca
            nz2 = -nx * sb + nz1 * cb
            if surface+6*nz2 > .07:
                continue
            y1 = y * ca - z * sa
            z1 = y * sa + z * ca
            x2 = x * cb + z1 * sb
            z2 = -x * sb + z1 * cb
            zz = z2 + 6.0
            k = 5.0 / zz
            sx = int(cx + x2 * k * sc * 1.15)
            sy = int(cy + y1 * k * sc)
            if 0 <= sx < hw and 0 <= sy < hh:
                key = sy * hw + sx
                if zz < zb[key]:
                    ny1 = ny * ca - nz * sa
                    nx2 = nx * cb + nz1 * sb
                    zb[key] = zz
                    dif = nx2 * lx + ny1 * ly + nz2 * lz
                    spc = nx2 * hx + ny1 * hy + nz2 * hz
                    v = .16 + .64 * max(0.,dif) + max(0.,spc) ** 18 * .27
                    hit[key] = ramp[min(63, int(v * 63))]
        fill = {}
        for key, c in hit.items():
            if (key + 2) in hit and (key + 1) not in hit and key % hw < hw - 2:
                fill[key + 1] = mix(c,hit[key+2],128)
            if (key + 2 * hw) in hit and (key + hw) not in hit:
                fill[key + hw] = mix(c,hit[key+2*hw],128)
        hit.update(fill)
        # The first pass can restore the rim of a two-cell hole. Close its interior
        # only when the pixels above, below and to one side are already covered.
        for key,c in hit.items():
            gap = key+hw
            if (gap not in hit and gap+hw in hit and 0 < gap%hw < hw-1
                    and (gap-1 in hit or gap+1 in hit)):
                fill[gap] = mix(c,hit[gap+hw],128)
        hit.update(fill)
        # Suppress isolated undersampled flecks along a lit surface, leaving silhouettes alone.
        for key,c in hit.items():
            r = c>>16
            if r >= 170 or not 0 < key%hw < hw-1:
                continue
            for offset in (1,hw):
                low,high = hit.get(key-offset,0),hit.get(key+offset,0)
                if min(low>>16,high>>16)>r+44:
                    fill[key] = mix(low,high,128)
                    break
        hit.update(fill)
        for key, c in hit.items():
            y, x = divmod(key, hw)
            o = 2 * y * W + 2 * x
            buf[o] = buf[o + 1] = buf[o + W] = buf[o + W + 1] = c
        return buf

    def _mesh(self, buf, ca, sa, cb, sb, light, highlight):
        W,hw,hh,sc = self.W,self.hw,self.hh,self.sc
        lx,ly,lz = light
        hx,hy,hz = highlight
        points = []
        for x,y,z,nx,ny,nz,_ in self.pts:
            screen_y,rot_z = y*ca-z*sa,y*sa+z*ca
            inverse_z = 1/(6-x*sb+rot_z*cb)
            zoom = 5*sc*inverse_z
            normal_y,normal_z = ny*ca-nz*sa,ny*sa+nz*ca
            normal_x,normal_z = nx*cb+normal_z*sb,-nx*sb+normal_z*cb
            diffuse = max(0,normal_x*lx+normal_y*ly+normal_z*lz)
            specular = max(0,normal_x*hx+normal_y*hy+normal_z*hz)
            points.append((hw/2+(x*cb+rot_z*sb)*zoom*1.15,hh/2+screen_y*zoom,
                           inverse_z,63*(.16+.64*diffuse+.27*specular**18)))
        depth = [0.]*(hw*hh)
        surface = [-1]*(hw*hh)
        visible = []
        ramp = self.ramp
        for i,j,k in self.faces:
            ax,ay,az,al = points[i]
            bx,by,bz,bl = points[j]
            cx,cy,cz,cl = points[k]
            abx,aby,acx,acy = bx-ax,by-ay,cx-ax,cy-ay
            area = abx*acy-aby*acx
            if area >= -1e-8:
                continue
            left,right = max(0,math.ceil(min(ax,bx,cx))),min(hw-1,math.floor(max(ax,bx,cx)))
            top,bottom = max(0,math.ceil(min(ay,by,cy))),min(hh-1,math.floor(max(ay,by,cy)))
            if left>right or top>bottom:
                continue
            ur,vr = acy/area,-aby/area
            for y in range(top,bottom+1):
                u = (left-ax)*ur-(y-ay)*acx/area
                v = (left-ax)*vr+(y-ay)*abx/area
                for x in range(left,right+1):
                    if u >= -1e-7 and v >= -1e-7 and u+v <= 1.0000001:
                        key = y*hw+x
                        z = az+u*(bz-az)+v*(cz-az)
                        if z>depth[key]:
                            if surface[key] < 0:
                                visible.append(key)
                            depth[key] = z
                            surface[key] = ramp[min(63,int(al+u*(bl-al)+v*(cl-al)))]
                    u += ur
                    v += vr
        for key in visible:
            y,x = divmod(key,hw)
            i = 2*y*W+2*x
            color = surface[key]
            right = surface[key+1] if x+1<hw else color
            below = surface[key+hw] if y+1<hh else -1
            if right < 0:
                right = buf[i+1]
            if below < 0:
                below = buf[i+W]
            # Each component is halved before addition, matching mix(c1,c2,128).
            half = (color >> 1) & 0x7F7F7F
            east = half + ((right >> 1) & 0x7F7F7F)
            south = half + ((below >> 1) & 0x7F7F7F)
            buf[i],buf[i+1],buf[i+W] = color,east,south
            buf[i+W+1] = ((east >> 1) & 0x7F7F7F) + ((south >> 1) & 0x7F7F7F)
        return buf


# ------------------------------------------------------------------- sakura
class Sakura(Scene):
    """Cherry blossom branch with tumbling petals in a soft dusk sky."""
    fps = 16
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (70, 50, 110)), (0.45, (190, 120, 150)), (0.8, (250, 190, 175)), (1.0, (255, 220, 190))])
        sr = max(3, int(H * 0.09))
        sx, sy = int(W * 0.72), int(H * 0.62)
        for y in range(-sr * 3, sr * 3):
            for x in range(-sr * 3, sr * 3):
                d = hypot(x, y)
                if d < sr:
                    plot(bg, W, H, sx + x, sy + y, rgb(255, 240, 215))
                elif d < sr * 3:
                    plota(bg, W, H, sx + x, sy + y, shade(rgb(255, 170, 140), int(256 * 0.45 * (1 - (d - sr) / (2.0 * sr)) ** 2)))
        for _ in range(8):                                                # far haze hills
            pass
        ph = rng.uniform(0, 6)
        for x in range(W):
            ry = int(H * 0.88 - H * 0.04 * sin(x / W * 6 + ph) - H * 0.02 * sin(x / W * 17))
            bg[ry * W + x::W] = [rgb(150, 100, 130)] * (H - ry)
        # main branch from top-left
        self.blossoms = []
        branch = [(-2, H * 0.12)]
        x, y, ang = -2.0, H * 0.12, 0.25
        wdt = max(2.0, H * 0.035)
        segs = []

        def grow(x, y, ang, w, depth):
            ln = W * (0.07 if depth else 0.09)
            for _ in range(int(W * 0.5 / ln) + 1 if depth == 0 else 3):
                nx = x + cos(ang) * ln
                ny = y + sin(ang) * ln
                segs.append((x, y, nx, ny, w))
                x, y = nx, ny
                ang += rng.uniform(-0.28, 0.28)
                w *= 0.82
                if x > W * (0.55 if depth == 0 else 0.7) or w < 0.5:
                    break
                if depth < 2 and rng.random() < 0.55:
                    grow(x, y, ang + rng.choice((-1, 1)) * rng.uniform(0.5, 0.9), w * 0.7, depth + 1)
                if rng.random() < 0.6:
                    self.blossoms.append((x, y))
            self.blossoms.append((x, y))

        grow(x, y, ang, wdt, 0)
        bark = rgb(48, 26, 36)
        for (x0, y0, x1, y1, w) in segs:
            n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
            for i in range(n):
                f = i / n
                xx = x0 + (x1 - x0) * f
                yy = y0 + (y1 - y0) * f
                for k in range(int(w) + 1):
                    plot(bg, W, H, int(xx), int(yy) + k - int(w // 2), bark)
        cols = [rgb(255, 190, 215), rgb(255, 160, 195), rgb(255, 225, 235), rgb(240, 130, 175)]
        for (bx, by) in self.blossoms:
            for _ in range(7):
                dx = rng.gauss(0, 2.2)*self.S
                dy = rng.gauss(0, 1.8)*self.S
                c = rng.choice(cols)
                plot(bg, W, H, int(bx + dx), int(by + dy), c)
                plot(bg, W, H, int(bx + dx) + 1, int(by + dy), shade(c, 220))
            plot(bg, W, H, int(bx), int(by), rgb(255, 235, 150))
        self.bg = bg
        self.blossoms = [(bx, by) for (bx, by) in self.blossoms]
        n = max(30, min(120, int(self.logical_area // 90)))
        self.petals = []
        for i in range(n):
            self.petals.append(self._new(rng.uniform(0, W), rng.uniform(-H * 0.1, H), True))
        self.pc = [rgb(255, 196, 218), rgb(255, 170, 205), rgb(255, 222, 234), rgb(248, 150, 190)]

    def _new(self, x, y, anywhere=False):
        r = self.rng
        s = r.uniform(0.6, 1.5)
        return [x, y, r.uniform(0, 6.3), r.uniform(1.4, 3.2), s, r.uniform(0, 6.3), r.uniform(0, 3)]

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        wind = 7.0 + 4.0 * sin(t * 0.3) + 3 * sin(t * 0.91)
        for p in self.petals:
            p[2] += dt * p[3]
            p[5] += dt * (1.5 + p[4])
            p[0] += (wind * p[4] * 0.8 + 9.0 * sin(p[2] * 0.7)) * dt*self.S
            p[1] += (5.0 + 5.0 * p[4] + 2.5 * sin(p[2] * 1.3)) * dt*self.S
            if p[1] > H + 2 or p[0] > W + 3:
                if rng.random() < 0.6 and self.blossoms:
                    bx, by = rng.choice(self.blossoms)
                    p[0], p[1] = bx, by
                else:
                    p[0], p[1] = rng.uniform(-W * 0.2, W), -2
        pc = self.pc
        for i, p in enumerate(self.petals):
            x, y = int(p[0]), int(p[1])
            c = pc[i & 3]
            fl = cos(p[5])
            if self.gfx:
                _gfx_line_set(buf,W,H,x,y,x+self.S*fl,y+self.S*.62,c)
            elif abs(fl) > 0.55:
                plot(buf, W, H, x, y, c)
                plot(buf, W, H, x + 1, y, shade(c, 215))
                if p[4] > 1.0:
                    plot(buf, W, H, x, y + 1, shade(c, 190))
            else:
                plot(buf, W, H, x, y, shade(c, 235))
        return buf


# ------------------------------------------------------------------ skyline
class Skyline(Scene):
    """Night city: parallax towers, twinkling windows, blinking beacons, a moving train."""
    fps = 12
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (6, 6, 24)), (0.45, (28, 16, 60)), (0.75, (110, 40, 100)), (1.0, (240, 110, 110))])
        for _ in range(int(self.logical_area // 130)):
            plot(bg, W, H, rng.randrange(W), rng.randrange(int(H * 0.45)), shade(rgb(230, 230, 255), rng.randint(60, 200)))
        mr = max(2, int(H * 0.05))
        mx, my = int(W * 0.2), int(H * 0.16)
        for y in range(-mr, mr + 1):
            for x in range(-mr, mr + 1):
                if hypot(x, y) < mr:
                    plot(bg,W,H,mx+x,my+y,0xDAD6CC)
        moon_halo = make_sprite(0x5B5173,mr*4,3,2.8)
        stamp(bg,W,H,mx,my,moon_halo[1])
        windows = {}
        self.beacons = []
        specs = [(0.34, (30, 22, 58), (12, 3, 9), 0.5), (0.46, (18, 14, 40), (14, 4, 11), 0.8), (0.58, (8, 7, 20), (16, 5, 13), 1.0)]
        for (hf, col, bw, lit) in specs:
            x = -round(rng.randint(0,6)*self.S)
            while x < W:
                bw_ = self.px(rng.randint(bw[0] // 2 + 3, bw[0] + 5))
                bh = int(H * rng.uniform(hf * 0.5, hf * 1.15))
                top = H - bh
                left,right = max(0,x),min(W,x+bw_)
                for y in range(max(0,top),H):
                    fill_row(bg,W,y,left,right,rgb(*col))
                    for wx in range(left,right):
                        windows.pop((wx,y),None)
                self.beacons = [(bx,by,p) for bx,by,p in self.beacons
                                if not (left <= bx < right and by >= top)]
                if rng.random() < 0.4 and top > 3:
                    plot(bg, W, H, x + bw_ // 2, top - 1, rgb(*col))
                    plot(bg, W, H, x + bw_ // 2, top - 2, rgb(*col))
                    if hf > 0.4:
                        self.beacons.append((x + bw_ // 2, top - 3, rng.uniform(0, 6.3)))
                for wy in range(top+self.px(2),H-self.px(2),self.px(3)):
                    for wx in range(x+self.px(1),x+bw_-self.px(1),self.px(2)):
                        if rng.random() < 0.5 and 0 <= wx < W:
                            windows[wx,wy] = (wx,wy,rng.random()*TAU,rng.uniform(.025,.12),
                                              rng.choice((0xD5AB74,0xDEB581,0x93ADC7,0xCECAB7)),lit)
                x += bw_ + rng.randint(0, 2)
        for y in range(int(H * 0.93), H):
            fill_row(bg, W, y, 0, W, rgb(6, 5, 12))
        self.bg = bg
        self.train_y = int(H*.91)
        self.wins = [w for w in windows.values() if w[1]<self.train_y]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for (x, y, p, flick, c, lit) in self.wins:
            dim = _ambient_smooth((sin(t*flick+p)-.58)/.4)
            light = shade(c,int((100+135*lit)*(1-.79*dim)))
            fill_row(buf,W,y,x,min(W,x+self.px(1)),light)
        for (x, y, p) in self.beacons:
            if sin(t * 2.2 + p) > 0.6 and 0 <= y < H:
                plota(buf, W, H, x, y, rgb(255, 40, 40))
                plota(buf, W, H, x + 1, y, rgb(90, 10, 10))
                plota(buf, W, H, x - 1, y, rgb(90, 10, 10))
        ty = self.train_y
        pos = (t*14*self.S)%(W+40*self.S)-20*self.S
        for k in range(8):
            x0 = int(pos-k*5*self.S)
            for xx in range(x0,x0+self.px(4)):
                plot(buf, W, H, xx, ty, rgb(40, 40, 60))
                plot(buf, W, H, xx, ty + 1, rgb(255, 235, 170))
        return buf


# ------------------------------------------------------------------- matrix
class Matrix(Scene):
    """Digital rain with real glyphs, per-column speed and bright heads (text mode)."""
    fps = 20
    text = True
    GL = ('ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ'
          '0123456789:.=*+-<>|')

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        # fullwidth-free: half-width katakana is 1 cell in kitty/most fonts
        self.cols = []
        for x in range(W):
            self.cols.append([rng.uniform(-H, 0), rng.uniform(6, 20), rng.randint(8, max(9, H)), rng.random() < 0.15])
        self.glyph = [[self.GL[rng.randrange(len(self.GL))] for _ in range(H)] for _ in range(W)]
        self.ramp = gradient([(0.0, (0, 20, 6)), (0.25, (0, 90, 30)), (0.6, (10, 200, 70)), (1.0, (120, 255, 150))], 24)
        self.head = rgb(215, 255, 225)
        self.empty = [' '] * (W * H)
        self.zero = [0] * (W * H)

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        chars = self.empty[:]
        fgs = self.zero[:]
        ramp = self.ramp
        glyph = self.glyph
        GL = self.GL
        nl = len(GL)
        for x in range(W):
            c = self.cols[x]
            c[0] += c[1] * dt
            if c[0] - c[2] > H:
                c[0] = rng.uniform(-H * 0.6, 0)
                c[1] = rng.uniform(6, 20)
                c[2] = rng.randint(8, max(9, H))
                c[3] = rng.random() < 0.15
            head = int(c[0])
            tl = c[2]
            gx = glyph[x]
            if 0 <= head < H and rng.random() < 0.6:
                gx[head] = GL[rng.randrange(nl)]
            for k in range(int(tl)):
                y = head - k
                if 0 <= y < H:
                    i = y * W + x
                    chars[i] = gx[y]
                    if k == 0:
                        fgs[i] = self.head
                    else:
                        fgs[i] = ramp[int(23 * (1 - k / tl) ** 1.5)]
                    if k > 1 and rng.random() < 0.01:
                        gx[y] = GL[rng.randrange(nl)]
        return chars, fgs


# ---------------------------------------------------------------- tesseract
class Tesseract(Scene):
    """Rotating 4-D hypercube: glowing wireframe in perspective."""
    fps = 15
    mask = 0xF8F8F8

    def setup(self):
        W, H = self.W, self.H
        self.bg = vgrad(W, H, [(0.0, (3, 4, 14)), (1.0, (7, 6, 22))])
        self.v = [[(1 if (i >> k) & 1 else -1) for k in range(4)] for i in range(16)]
        self.e = [(i, i ^ (1 << k)) for i in range(16) for k in range(4) if i < i ^ (1 << k)]
        self.sc = min(W*.42,H*.49)
        self.pal = _ambient_palette(((0,0x596BA0),(.53,0x6BADB9),(1,0xE4B484)),64)
        self.nodesp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 1.8)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        a = [t*.14,t*.109,t*.172,t*.079,t*.133,t*.071]
        planes = ((0, 3), (1, 3), (2, 3), (0, 1), (0, 2), (1, 2))
        cs = [(cos(x), sin(x)) for x in a]
        P = []
        cx, cy = W / 2.0, H / 2.0
        for v in self.v:
            p = list(v)
            for (i, j), (c, s) in zip(planes, cs):
                u, w = p[i], p[j]
                p[i] = u * c - w * s
                p[j] = u * s + w * c
            k4 = 1.0 / (2.6 - p[3])
            x, y, z = p[0] * k4, p[1] * k4, p[2] * k4
            k3 = 1.0 / (3.0 - z * 0.9)
            P.append((cx + x * k3 * self.sc * 2.3, cy + y * k3 * self.sc * 2.3, z))
        pal = self.pal
        width = min(1.45, self.detail_scale) if self.detail_scale >= 1.45 else 1.
        for i,j in sorted(self.e,key=lambda edge:P[edge[0]][2]+P[edge[1]][2]):
            x0, y0, z0 = P[i]
            x1, y1, z1 = P[j]
            zz = (z0 + z1) * 0.5
            near = max(0.,min(1.,.48+zz*.49))
            c = shade(pal[int(near*63)],int(113+119*near))
            line_add(buf,W,H,x0+self.S,y0,x1+self.S,y1,shade(c,53))
            if self.gfx:
                _gfx_line_set(buf,W,H,x0,y0,x1,y1,c,width)
            else:
                line_set(buf,W,H,x0,y0,x1,y1,c)
        for (x, y, z) in P:
            stamp(buf, W, H, int(x), int(y), self.nodesp[min(7, max(2, int(4 + z * 3)))])
        return buf


# ---------------------------------------------------------------- lissajous
class Lissajous(Scene):
    """Phosphor-style Lissajous scope with a long glowing comet tail."""
    fps = 16
    mask = 0xF8F8F8

    def setup(self):
        W, H = self.W, self.H
        self.bg = vgrad(W, H, [(0.0, (2, 8, 6)), (1.0, (2, 8, 6))])
        for x in range(0, W, max(self.px(6), W // 14)):
            for y in range(H):
                self.bg[y * W + x] = rgb(5, 18, 12)
        for y in range(0, H, max(self.px(6), H // 8)):
            fill_row(self.bg, W, y, 0, W, rgb(5, 18, 12))
        self.pal = (0x72B7AA,0x789CC6,0xC6A778)
        self.sp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 1.6)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        cx, cy = W / 2.0, H / 2.0
        ax, ay = W * 0.45, H * 0.45
        stroke = _gfx_line_add if self.gfx else line_add
        for ci, (a, b, ph, sp) in enumerate(((3, 2, 0.0, 0.5), (5, 4, 1.1, 0.4), (7, 5, 2.0, 0.33))):
            A = .9*sin(t*.039+ci)
            B = .9*cos(t*.027+ci)
            n = 132
            px = py = None
            tail = 3.6
            for i in range(n):
                tt = t*sp*.74-(n-i)*tail/n*.48
                x = cx + ax * (0.75 - 0.2 * ci) * sin(a*tt + ph + A)
                y = cy + ay * (0.75 - 0.2 * ci) * sin(b*tt + B)
                if px is not None:
                    f = (i / n) ** 2.2
                    c = shade(self.pal[ci],int(164*f))
                    stroke(buf, W, H, px, py, x, y, c)
                px, py = x, y
            stamp(buf,W,H,int(px),int(py),self.sp[5])
        return buf


# ----------------------------------------------------------------- pendulum
class Pendulum(Scene):
    """Triple pendulum (real physics, RK4) painting a luminous trail."""
    fps = 16
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = [0x040615]*(W*H)
        self.state = [rng.uniform(1.8, 2.8), rng.uniform(1.8, 2.8), rng.uniform(1.8, 2.8), 0.0, 0.0, 0.0]
        self.trail = []
        self.pal = _ambient_palette(((0,0x263658),(.38,0x417C93),(.72,0xA886BD),(1,0xE1BB8A)),64)
        self.L = min(H * .144, W * .146)
        self.sp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 1.4)

    def _acc(self, s):
        # triple pendulum, equal masses/lengths; solve M a = f numerically (3x3)
        th = s[:3]
        w = s[3:]
        g = 9.8
        M = [[0.0] * 3 for _ in range(3)]
        f = [0.0] * 3
        for i in range(3):
            for j in range(3):
                M[i][j] = (3 - max(i, j)) * cos(th[i] - th[j])
            f[i] = -sum((3 - max(i, j)) * sin(th[i] - th[j]) * w[j] * w[j] for j in range(3)) - (3 - i) * g * sin(th[i])
        # gaussian elimination
        A = [M[i][:] + [f[i]] for i in range(3)]
        for c in range(3):
            p = max(range(c, 3), key=lambda r: abs(A[r][c]))
            A[c], A[p] = A[p], A[c]
            d = A[c][c] or 1e-9
            for r in range(c + 1, 3):
                k = A[r][c] / d
                for cc in range(c, 4):
                    A[r][cc] -= k * A[c][cc]
        a = [0.0] * 3
        for i in (2, 1, 0):
            a[i] = (A[i][3] - sum(A[i][j] * a[j] for j in range(i + 1, 3))) / (A[i][i] or 1e-9)
        return s[3:] + a

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        s = self.state
        n = 5
        h = min(dt, .08) / n * 1.10
        for _ in range(n):
            k1 = self._acc(s)
            k2 = self._acc([a + b * h / 2 for a, b in zip(s, k1)])
            k3 = self._acc([a + b * h / 2 for a, b in zip(s, k2)])
            k4 = self._acc([a + b * h for a, b in zip(s, k3)])
            s = [a + h / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(s, k1, k2, k3, k4)]
        for i in range(3):
            s[i] = (s[i] + PI) % TAU - PI if abs(s[i]) > 50 else s[i]
        if any(abs(x) > 60 or x != x for x in s[3:]):                  # numeric blow-up guard
            s = [self.rng.uniform(1.8, 2.8) for _ in range(3)] + [0.0, 0.0, 0.0]
            self.trail = []
        self.state = s
        ox, oy = W / 2.0, H * 0.50
        L = self.L
        x1, y1 = ox + L * sin(s[0]), oy + L * cos(s[0])
        x2, y2 = x1 + L * sin(s[1]), y1 + L * cos(s[1])
        x3, y3 = x2 + L * sin(s[2]), y2 + L * cos(s[2])
        self.trail.append((x3, y3))
        if len(self.trail) > (345 if self.gfx else 260):
            self.trail.pop(0)
        tr = self.trail
        m = len(tr)
        for i in range(1, m):
            f = (i / m) ** 1.7
            c = shade(self.pal[int(63*(.5+.5*sin(t*.05+i*.017)))], int(176 * f))
            line_add(buf, W, H, tr[i - 1][0], tr[i - 1][1], tr[i][0], tr[i][1], c)
        arm = 0x859BB6
        stroke = _gfx_line_set if self.gfx else line_set
        for (a, b, c_, d) in ((ox, oy, x1, y1), (x1, y1, x2, y2), (x2, y2, x3, y3)):
            stroke(buf, W, H, a, b, c_, d, arm)
        for (x, y) in ((ox, oy), (x1, y1), (x2, y2)):
            stamp(buf, W, H, int(x), int(y), self.sp[4])
        stamp(buf, W, H, int(x3), int(y3), self.sp[7])
        return buf


# ------------------------------------------------------------ constellation
class Constellation(Scene):
    """A slowly drifting star map with fading links and one roaming hub."""
    fps = 12
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W, H, [(0.0, (3, 4, 16)), (0.6, (10, 10, 36)), (1.0, (22, 12, 44))])
        for _ in range(int(self.logical_area // 90)):
            plot(self.bg, W, H, self.detail_coord(W), self.detail_coord(H,True), shade(rgb(130, 140, 190), rng.randint(40, 150)))
        n = max(32, min(77, int(self.logical_area // 160)))
        self.s = []
        for i in range(n):
            a = rng.uniform(0, TAU)
            sp = rng.uniform(.85, 3.5)*self.S
            self.s.append([rng.uniform(0, W), rng.uniform(0, H), cos(a) * sp, sin(a) * sp * 0.6, rng.uniform(0, 6.3), rng.random()])
        self.lk = max(9.*self.S,min(23.*self.S,H*.225))
        self.sp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 2.0)
        self.tints = [rgb(190, 215, 255), rgb(255, 240, 215), rgb(255, 200, 190)]
        self.hub_glow = make_sprite(0xBFD7FF, self.px(4), 8, 2.25)

    @staticmethod
    def _thin_link(buf,W,H,x0,y0,x1,y1,color):
        # Star centers are in bounds. Use the two minor-axis samples without a fringe.
        steep = abs(y1-y0)>abs(x1-x0)
        if steep:
            x0,y0,x1,y1 = y0,x0,y1,x1
        if x0>x1:
            x0,x1,y0,y1 = x1,x0,y1,y0
        span = x1-x0
        slope = (y1-y0)/span if span else 0.
        major,minor = (H,W) if steep else (W,H)
        step = 1 if steep else W
        rb,g = color&0xFF00FF,color&0x00FF00
        floor = math.floor
        for x in range(round(x0),min(major,round(x1)+1)):
            y = y0+(x-x0)*slope
            base = floor(y)
            alpha = int((y-base)*256)
            offset = x*W+base if steep else base*W+x
            if 0<=base<minor:
                weight = 256-alpha
                ink = (((rb*weight)>>8)&0xFF00FF)|(((g*weight)>>8)&0x00FF00)
                pixel = buf[offset]
                total = pixel+ink
                carry = (total^pixel^ink)&0x1010100
                buf[offset] = (total|(carry-(carry>>8)))&0xFFFFFF if carry else total
            if alpha and 0<=base+1<minor:
                ink = (((rb*alpha)>>8)&0xFF00FF)|(((g*alpha)>>8)&0x00FF00)
                pixel = buf[offset+step]
                total = pixel+ink
                carry = (total^pixel^ink)&0x1010100
                buf[offset+step] = (total|(carry-(carry>>8)))&0xFFFFFF if carry else total

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        S = self.s
        for p in S:
            p[0] = (p[0] + p[2] * dt) % W
            p[1] = (p[1] + p[3] * dt) % H
        cell = self.lk
        grid = {}
        for i, p in enumerate(S):
            grid.setdefault((int(p[0] / cell), int(p[1] / cell)), []).append(i)
        thr2 = cell * cell
        link = self._thin_link if self.gfx else line_add
        line_c = mix(0x7492CE,0x947DB3,int(128+110*sin(t*.021)))
        hub_budget = 0
        for (gx, gy), idxs in grid.items():
            for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 1)):
                other = grid.get((gx + dx, gy + dy))
                if not other:
                    continue
                for i in idxs:
                    pi = S[i]
                    for j in other:
                        if (dx or dy) or j > i:
                            pj = S[j]
                            ddx = pj[0] - pi[0]
                            ddy = pj[1] - pi[1]
                            d2 = ddx * ddx + ddy * ddy
                            if 1 < d2 < thr2:
                                if i == 0 or j == 0:
                                    hub_budget += 1
                                    continue
                                a = (1.0 - d2 / thr2) ** 1.3
                                ink = shade(line_c, int(122*a))
                                if ink:
                                    link(buf,W,H,pi[0],pi[1],pj[0],pj[1],ink)
        hx = W*(.50+.32*sin(t*.046))
        hy = H*(.50+.31*sin(t*.039+1.0))
        if hub_budget:
            candidates = []
            radius_sq = thr2*1.85
            for x,y,*_ in S[1:]:
                d2 = (x-hx)**2+(y-hy)**2
                if 1<d2<radius_sq:
                    candidates.append((d2,x,y))
            # Reuse only the link slots freed by the star the hub replaces.
            for d2,x,y in sorted(candidates)[:min(3,hub_budget)]:
                link(buf,W,H,hx,hy,x,y,shade(0x9BB4DD,int(122*(1-d2/radius_sq))))
        stamp(buf,W,H,round(hx),round(hy),self.hub_glow[5+round(1+sin(t*.56))])
        plota(buf,W,H,round(hx),round(hy),0xD1DEFB)
        for i, p in enumerate(S[1:], 1):
            tw = 0.55 + 0.45 * sin(t * (.58 + p[5] * .95) + p[4])
            lv = int(2 + 5 * tw * (0.5 + 0.5 * p[5]))
            xi, yi = int(p[0]), int(p[1])
            stamp(buf, W, H, xi, yi, self.sp[min(7, lv)])
            plota(buf, W, H, xi, yi, shade(self.tints[i % 3], int(256 * tw)))
        return buf


# -------------------------------------------------------------------- sonar
class Sonar(Scene):
    """Radar scope: phosphor sweep with afterglow, range rings and blips that echo."""
    fps = 15

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.cx, self.cy = W / 2.0, H / 2.0
        self.R = min(W * 0.5, H * 0.5) * 0.94
        rr = self.R
        bg = [rgb(1, 8, 5)] * (W * H)
        for y in range(H):
            for x in range(W):
                d = hypot(x - self.cx, (y - self.cy)) / rr
                if d < 1.0:
                    bg[y * W + x] = rgb(2, 16 - 6 * d, 9 - 3 * d)
        for k in range(1, 5):
            r = rr * k / 4
            for i in range(int(TAU * r * 1.3)):
                a = i / (r * 1.3)
                plot(bg, W, H, int(self.cx + r * cos(a)), int(self.cy + r * sin(a)), rgb(10, 70, 36) if k < 4 else rgb(20, 130, 64))
        for i in range(12):
            a = i * TAU / 12
            line_set(bg, W, H, self.cx, self.cy, self.cx + rr * cos(a), self.cy + rr * sin(a), rgb(7, 40, 22))
        self.bg = bg
        self.blips = []
        for i in range(14):
            a = rng.uniform(0, TAU)
            r = rng.uniform(0.15, 0.95) * rr
            self.blips.append([a, r, rng.uniform(-0.05, 0.05), rng.uniform(-0.08, 0.08)])
        self.sweepcols = [shade(rgb(80, 255, 140), int(256 * (1 - i / 64) ** 2.2)) for i in range(64)]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        cx, cy, R = self.cx, self.cy, self.R
        sw = (t * 1.3) % TAU
        for k in range(64):
            a = sw - k * 0.022
            line_add(buf, W, H, cx, cy, cx + R * cos(a), cy + R * sin(a) * 1.0, shade(self.sweepcols[k], 60 if k else 256))
        for b in self.blips:
            b[0] += b[2] * dt
            b[1] += b[3]*6*dt*self.S
            if b[1] > R * 0.97 or b[1] < R * 0.1:
                b[3] = -b[3]
            diff = (sw - b[0]) % TAU
            lv = max(0.0, 1.0 - diff / 4.4) ** 2.2
            if lv < 0.02:
                continue
            x, y = int(cx + b[1] * cos(b[0])), int(cy + b[1] * sin(b[0]))
            c = shade(rgb(120, 255, 170), int(256 * lv))
            plota(buf, W, H, x, y, c)
            plota(buf, W, H, x+self.px(1),y,c)
            plota(buf, W, H, x,y+self.px(1),shade(c,150))
            if lv > 0.7:
                ring = ((1-lv)*20+2)*self.S
                samples = self.px(14)
                for i in range(samples):
                    ang = i*TAU/samples
                    plota(buf, W, H, int(x + ring * cos(ang)), int(y + ring * sin(ang)), shade(c, 90))
        return buf


# ----------------------------------------------------------------- wormhole
class Wormhole(Scene):
    """Flight down a twisting, glowing tunnel with ring stripes and streaking stars."""
    fps = 11
    mask = 0xF0F0F0
    gfx_fps = 20
    gfx_pixels = 56000

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.cx, self.cy = W / 2.0, H / 2.0
        self.sh = H if self.gfx else (H+1)//2
        sh = self.sh
        cx, cy = W / 2.0, sh / 2.0
        hh = H * 0.5
        self.ang = []
        self.depth = []
        self.fog = []
        for y in range(sh):
            for x in range(W):
                dx = (x + 0.5 - cx) / hh
                dy = (y+.5-cy)*H/sh/hh if self.gfx else 2.0*(y+.5-cy)/hh
                r = hypot(dx, dy)
                depth = 2.2/(.28+r)
                self.depth.append(int(depth*.82*256))
                self.ang.append(math.floor((atan2(dy,dx)/TAU*4+depth*.075)*256))
                self.fog.append(min(15, int(15 * min(1.0, r * 1.7) ** 0.8)))
        hues = _ambient_palette(((0,0x08172A),(.36,0x25435A),(.68,0x438680),
                                 (.88,0xAC815D),(1,0xDAC09A)),64)
        self.tab = [[shade(h, 12 + 11*l) for h in hues] for l in range(16)]
        self.st = [[rng.uniform(0, TAU), rng.uniform(.05,1.0)]
                   for _ in range(max(18,min(61,int(self.logical_area//240))))]
        radius = min(W,H)*.102
        self.halo = []
        for y in range(max(0,int(self.cy-radius)),min(H,int(self.cy+radius)+1)):
            for x in range(max(0,int(self.cx-1.9*radius)),min(W,int(self.cx+1.9*radius)+1)):
                d = hypot((x-self.cx)/1.9,y-self.cy)/radius
                if d < 1:
                    self.halo.append((y*W+x,int(191*(1-d)**1.7)))

    def frame(self, t, dt):
        W, H, sh = self.W, self.H, self.sh
        tab = self.tab
        sp = int((t*.31+.52*sin(t*.042))*.82*256)
        tw = int(t*.029*256)
        out = []
        ext = out.extend
        ang, dep, fog = self.ang, self.depth, self.fog
        for y in range(sh):
            o = y * W
            row = []
            ap = row.append
            for a, d, f in zip(ang[o:o + W], dep[o:o + W], fog[o:o + W]):
                spiral = SIN256[(a+tw)&255]
                band = SIN256[(d+sp+spiral//5)&255]
                ap(tab[f][(band*(190+spiral//4))>>10])
            ext(row)
            if not self.gfx and 2*y+1<H:
                ext(row)
        cx, cy = self.cx, self.cy
        streak = _gfx_line_add if self.gfx else line_add
        for j,strength in self.halo:
            out[j] = mix(out[j],0xDCCB9E,strength)
        for s in self.st:
            s[1] += dt * (.052 + .36 * s[1])
            if s[1] > 1.4:
                s[1] = 0.08
                s[0] = self.rng.uniform(0, TAU)
            r1 = s[1]
            r0 = r1 * .94
            ca, sa = cos(s[0]), sin(s[0])
            streak(out, W, H, cx + ca * r0 * W * 0.5, cy + sa * r0 * H * 0.5,
                     cx + ca * r1 * W * 0.5, cy + sa * r1 * H * 0.5, shade(0xB4C3D8, int(min(158, 190 * r1))))
        return out


# --------------------------------------------------------------- fireworks
class Fireworks(Scene):
    """Rockets, spherical bursts, glitter and smoke-free sparkle over a reflective bay."""
    fps = 15
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (2, 2, 10)), (0.7, (8, 8, 28)), (1.0, (14, 12, 34))])
        for _ in range(int(self.logical_area // 200)):
            plot(bg, W, H, rng.randrange(W), rng.randrange(int(H * 0.6)), shade(rgb(200, 210, 255), rng.randint(40, 130)))
        self.hy = int(H * 0.82)
        for x in range(W):
            ry = int(self.hy - H * 0.04 * (0.5 + 0.5 * sin(x * 0.11 + 1)) * (1 if (x // 5) % 3 else 0.4) - 1)
            bg[ry * W + x::W] = [rgb(4, 4, 10)] * (H - ry)
        self.bg = bg
        self.rockets = []
        self.parts = []
        self.acc = 0.0
        self.next = 0.3
        self.pals = [((255, 90, 70), (255, 200, 90)), ((90, 170, 255), (200, 240, 255)), ((120, 255, 150), (240, 255, 190)),
                     ((255, 110, 220), (255, 200, 240)), ((255, 210, 80), (255, 250, 200)), ((180, 120, 255), (230, 200, 255))]

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        hy = self.hy
        self.acc += dt
        if self.acc >= self.next and len(self.rockets) < 3 and len(self.parts) < 900:
            self.acc = 0
            self.next = rng.uniform(1.25, 3.6)
            self.rockets.append([rng.uniform(W * .24, W * .76), float(hy), rng.uniform(-3,3)*self.S,
                                 -rng.uniform(H * 0.85, H * 1.15), rng.uniform(H * .27, H * .50), rng.randrange(6)])
        nr = []
        for r in self.rockets:
            r[0] += r[2] * dt
            r[1] += r[3] * dt
            r[3] += 0.0
            if r[1] <= r[4]:
                pal = self.pals[r[5]]
                big = rng.random() < 0.25
                n = int((150 if not big else 240) * min(1.3,W/(100*self.S)+.3))
                v = min(H*.36,W*.27)*rng.uniform(.82,1.10)*(1.17 if big else 1)
                ring = rng.random() < 0.3
                for i in range(n):
                    a = (i+rng.uniform(-.43,.43))*TAU/n if ring else rng.uniform(0,TAU)
                    if ring:
                        s = v*rng.uniform(.85,1.04)
                    else:
                        s = v * sqrt(rng.random()) * 1.0 + v * 0.15
                    col = pal[0] if i % 3 else pal[1]
                    self.parts.append([r[0], r[1], cos(a) * s * 1.7, sin(a) * s, rng.uniform(1.65, 2.8), 0.0, col, rng.random() < 0.18])
                continue
            nr.append(r)
            line_add(buf, W, H, r[0], r[1], r[0] - r[2] * 0.06, r[1]+3*self.S,rgb(255, 230, 180))
            plota(buf, W, H, int(r[0]), int(r[1]), rgb(255, 255, 255))
        self.rockets = nr
        keep = []
        grav = H * 0.35
        drag = 0.5 ** (dt * 2.0)
        for p in self.parts:
            p[5] += dt
            if p[5] >= p[4]:
                continue
            p[2] *= drag
            p[3] = p[3] * drag + grav * dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if p[1] >= hy:
                continue
            keep.append(p)
            f = 1.0 - p[5] / p[4]
            tw = .81+.19*sin(p[5]*5+p[4]*4) if p[7] else 1.
            rise = _ambient_smooth(p[5]/.20)
            c = shade(rgb(*p[6]), int(201 * f ** 1.03 * tw * rise))
            x, y = int(p[0]), int(p[1])
            plota(buf, W, H, x, y, c)
            plota(buf, W, H, int(p[0] - p[2] * dt * 1.8), int(p[1] - p[3] * dt * 1.8), shade(c, 110))
            if f>.45 and self.gfx:
                g = shade(c,65)
                for ox,oy in ((1,0),(-1,0),(0,1),(0,-1)):
                    plota(buf,W,H,x+ox,y+oy,g)
                    if self.S>1.6:
                        plota(buf,W,H,x+ox*2,y+oy*2,shade(g,74))
            elif f > .45:
                g = shade(c, 70)
                plota(buf, W, H, x + 1, y, g)
                plota(buf, W, H, x - 1, y, g)
                plota(buf, W, H, x, y + 1, g)
                plota(buf, W, H, x, y - 1, g)
            ry = 2 * hy - y                                      # water reflection
            if ry < H and f > 0.2:
                plota(buf, W, H, x, ry, shade(c, 60))
        self.parts = keep
        return buf


# -------------------------------------------------------------------- boids
class Boids(Scene):
    """Murmuration: a large flock with real separation / alignment / cohesion and swirl, over dusk sky."""
    fps = 15
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W, H, [(0.0, (30, 36, 90)), (0.5, (150, 90, 130)), (0.85, (250, 160, 110)), (1.0, (255, 200, 130))])
        n = max(40, min(110, int(self.logical_area//90)))
        self.b = []
        for i in range(n):
            a = rng.uniform(0, TAU)
            self.b.append([rng.uniform(W * 0.3, W * 0.7), rng.uniform(H * 0.3, H * 0.7), cos(a)*12*self.S,sin(a)*8*self.S])
        self.cell = max(7.*self.S,H*.14)
        self.edge = min(min(W,H)*.20, max(self.px(3), min(W,H)*.068))
        self.turn_x = max(self.edge*2, W*.20)
        self.turn_y = max(self.edge*2, H*.24)
        for x in range(W):
            u = x/W
            for base,amplitude,color in ((.83,.049,0x62475C),(.93,.038,0x372E48)):
                y = int(H*(base-amplitude*(sin(8*u+base)+.46*cos(20*u))))
                self.bg[y*W+x::W] = [color]*(H-y)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        B = self.b
        cell = self.cell
        grid = {}
        for i, b in enumerate(B):
            grid.setdefault((int(b[0] / cell), int(b[1] / cell)), []).append(i)
        gx = W*(.50+.25*sin(t*.094))
        gy = H*(.46+.15*sin(t*.139+1.0))
        edge, turn_x, turn_y = self.edge, self.turn_x, self.turn_y
        right, bottom = W-1-edge, H-1-edge
        c2 = cell * cell
        for i, b in enumerate(B):
            x, y, vx, vy = b
            cxg, cyg = int(x / cell), int(y / cell)
            sx = sy = ax = ay = cx_ = cy_ = 0.0
            n = 0
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    for j in grid.get((cxg + ox, cyg + oy), ()):
                        if j == i:
                            continue
                        o = B[j]
                        dx = o[0] - x
                        dy = o[1] - y
                        d2 = dx * dx + dy * dy
                        if d2 < c2:
                            n += 1
                            ax += o[2]
                            ay += o[3]
                            cx_ += o[0]
                            cy_ += o[1]
                            if d2 < c2 * 0.12 and d2 > 1e-3:
                                sx -= dx / d2
                                sy -= dy / d2
            fx = fy = 0.0
            if n:
                fx += (ax / n - vx) * 1.6 + (cx_ / n - x) * 0.25 + sx*28*self.S**2
                fy += (ay / n - vy) * 1.6 + (cy_ / n - y) * 0.25 + sy*28*self.S**2
            wall_x = max(0.,turn_x-x)-max(0.,x-W+turn_x)
            wall_y = max(0.,turn_y-y)-max(0.,y-H+turn_y)
            fx += (gx-x)*.12+3.2*wall_x
            fy += (gy-y)*.17+3.2*wall_y
            if wall_x*vx < 0:
                fx -= vx*min(2.4, 5.0*abs(wall_x)/turn_x)
            if wall_y*vy < 0:
                fy -= vy*min(2.4, 5.0*abs(wall_y)/turn_y)
            vx += fx * dt
            vy += fy * dt
            sp = sqrt(vx * vx + vy * vy) + 1e-6
            hi = min(16.*self.S,max(5.*self.S,min(W,H)*.27))
            lo = hi*.42
            if sp > hi:
                vx *= hi / sp
                vy *= hi / sp
            elif sp < lo:
                vx *= lo / sp
                vy *= lo / sp
            x,y = x+vx*dt,y+vy*dt
            if x < edge or x > right:
                x, vx = max(edge, min(right, x)), -.48*vx
            if y < edge or y > bottom:
                y, vy = max(edge, min(bottom, y)), -.48*vy
            b[0], b[1], b[2], b[3] = x, y, vx, vy
        col = rgb(12, 10, 24)
        for b in B:
            x, y = int(b[0]), int(b[1])
            sp = sqrt(b[2] * b[2] + b[3] * b[3]) + 1e-6
            ux, uy = b[2] / sp, b[3] / sp
            plot(buf, W, H, x, y, col)
            plot(buf, W, H, int(b[0] - ux*1.2*self.S), int(b[1] - uy*1.2*self.S), col)
            wing = sin(t*5.2+(x*.23+y*.3)/self.S)*1.35*self.S
            if self.gfx:
                _gfx_line_set(buf,W,H,x-uy*wing,y+ux*wing,x+uy*wing,y-ux*wing,col)
            plot(buf, W, H, int(b[0] - uy * wing), int(b[1] + ux * wing), col)
            plot(buf, W, H, int(b[0] + uy * wing), int(b[1] - ux * wing), col)
        return buf


# --------------------------------------------------------------------- fire
class Fire(Scene):
    """Classic fire effect, softly blurred, with rising embers and a warm glow."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 56000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.left, self.top = round(W*.15), round(H*.12)
        self.width = W - 2*self.left
        self.height = round(H*.89) - self.top
        self.fw = (self.width + 1) // 2
        self.fh = (self.height + 1) // 2 + self.px(6)
        self.pal = _ambient_palette(((0,0x080611),(.17,0x281323),(.39,0x803223),
                                     (.64,0xCA612D),(.84,0xECA04E),(1,0xF4D28E)))
        self.fuel = []
        for x in range(self.fw):
            u = x/max(1,self.fw-1)
            taper = _ambient_smooth(min(u,1-u)/.19)
            hearth = (.54+.46*sin(PI*u)**.8)*taper
            self.fuel.append((u, rng.uniform(-.05,.05), hearth))
        self.f = [0] * (self.fw * self.fh)
        self.embers = []
        self.setup_hearth()

    def setup_hearth(self):
        W, H = self.W, self.H
        left, top, width, height = self.left, self.top, self.width, self.height
        spring = max(1, round(height*.30))
        floor = top+height
        stone_w, stone_h = self.px(15), self.px(6)
        mortar = max(2, self.px(1))
        self.opening = []
        self.bg = [0]*(W*H)
        for y in range(H):
            row = y-top
            inset = 0
            if 0 <= row < spring:
                arc = (spring-row)/(spring+.6)
                inset = min(width//2-1, round(width*.36*(1-sqrt(1-arc*arc))))
            tile_row = y//stone_h
            for x in range(W):
                tx = x+(tile_row % 2)*stone_w//2
                tile = tx//stone_w
                light = exp(-((x/W-.50)/.39)**2-((y/H-.83)/.50)**2)
                distance = min(abs(x-left-inset), abs(x-left-width+inset+1))
                trim = 0 <= row < height and distance < self.px(2)
                seam = not trim and (tx % stone_w < mortar or y % stone_h < mortar)
                gx, gy = x//self.px(2), y//self.px(2)
                grit = ((gx*83 ^ gy*131 ^ gx*gy*7) % 6)-3
                tone = (tile*13 ^ tile_row*19) % 9 if not seam else -6
                if floor <= y < floor+self.px(2):
                    tone -= 5
                core = rgb(10+tone+grit, 10+tone*.7+grit, 14+tone*.55+grit)
                spill = shade(0x733514, int(light*(115 if trim else 54 if seam else 87)))
                self.bg[y*W+x] = addp(core, spill)
            if 0 <= row < height:
                self.opening.append((inset, width-inset))

        # Charred logs cross just above the hearth, with a thin ember-lit upper lip.
        self.logs = []
        for x0, y0, x1, y1, thickness in ((.17,.94,.70,.85,.047), (.34,.86,.85,.97,.057)):
            a, b = x0*width, y0*height
            dx, dy = x1*width-a, y1*height-b
            length = dx*dx+dy*dy
            radius = max(1.1, height*thickness)
            for row in range(max(0, int(min(b,b+dy)-radius)), min(height, round(max(b,b+dy)+radius+1))):
                for col in range(max(0,int(a-radius)), min(width,round(a+dx+radius+1))):
                    u = max(0.,min(1.,((col-a)*dx+(row-b)*dy)/length))
                    off = row-b-u*dy
                    distance = hypot(col-a-u*dx,off)
                    grain = ((row*19 ^ col*31) % 7)
                    if distance <= radius*(.85+grain*.035):
                        color = 0x130B10
                        if off < -radius*.36:
                            color = shade(0x85371F, 97+grain*17)
                        elif grain < 2:
                            color = 0x241119
                        self.logs.append(((top+row)*W+left+col, color))

    def frame(self, t, dt):
        W, H, fw, fh, rng = self.W, self.H, self.fw, self.fh, self.rng
        f = self.f
        rnd = rng.random
        base = (fh - 1) * fw
        flick = .92+.075*sin(t*1.8)*sin(t*.62)
        dcy = 2.4 * 255 / fh
        for x,(u,variation,hearth) in enumerate(self.fuel):
            tongues = .82+.12*sin(u*20+t*1.37)+.05*sin(u*46-t*2.05)
            f[base+x] = clamp8(255*flick*hearth*(tongues+variation+.09*rnd()))
        for y in range(fh - 2, -1, -1):
            r = y * fw
            b = r + fw
            b2 = b + fw if y < fh - 2 else b
            new = []
            for x in range(fw):
                xl = x - 1 if x else 0
                xr = x + 1 if x < fw - 1 else x
                s = (f[b + xl] + 2 * f[b + x] + f[b + xr] + f[b2 + x]) * 0.2
                s -= (.20+.62*rnd()) * dcy
                new.append(255 if s > 255 else int(s) if s > 0 else 0)
            f[r:r + fw] = new
        width, height = self.width, self.height
        visible_rows = (height + 1) // 2
        idx = f[(fh-visible_rows)*fw:]
        flames = up2(idx, fw, visible_rows, width, height, self.pal)
        out = self.bg[:]
        for row, (a, b) in enumerate(self.opening):
            dst = (self.top+row)*W+self.left
            src = row*width
            out[dst+a:dst+b] = flames[src+a:src+b]
        # embers
        if rnd() < (1-.57**(dt*type(self).fps) if self.gfx else .43) and len(self.embers) < 30:
            self.embers.append([self.left+rng.uniform(width*.10,width*.90), self.top+height-2*self.S, rng.uniform(-5,5)*self.S, -rng.uniform(8,22)*self.S, rng.uniform(1.5, 3.5), 0.0])
        keep = []
        for e in self.embers:
            e[5] += dt
            if e[5] > e[4]:
                continue
            e[0] += (e[2] + 6*self.S*sin(e[5]*5+e[0]/self.S)) * dt
            e[1] += e[3] * dt
            keep.append(e)
            lv = 1 - e[5] / e[4]
            x, y = int(e[0])-self.left, int(e[1])-self.top
            if 0 <= y < height:
                a, b = self.opening[y]
                if a <= x < b:
                    plota(out, W, H, x+self.left, y+self.top, shade(0xFFBE3C, int(256 * lv)))
        self.embers = keep
        for i, color in self.logs:
            out[i] = color
        return out


# ---- shared helpers for scenes 27-46 ----
def _ambient_scale(W, H, pixel_scale=1.0):
    return min(W / 118, H / 98, 1.4 * pixel_scale)


def _ambient_palette(stops, count=256):
    return gradient([(p, (c >> 16, c >> 8 & 255, c & 255)) for p, c in stops], count)


def _ambient_disc(buf, W, H, x, y, radius, color):
    x, y = round(x), round(y)
    rr = radius * radius
    for dy in range(max(-radius, -y), min(radius + 1, H - y)):
        dx = int(sqrt(rr - dy * dy))
        fill_row(buf, W, y + dy, max(0, x - dx), min(W, x + dx + 1), color)


def _ambient_stars(buf, W, H, rng, count, ceiling):
    for _ in range(count):
        c = shade(rng.choice((0x9CB9FF, 0xFFD9AA, 0xCCD6EE)), rng.randrange(22, 114))
        buf[rng.randrange(ceiling) * W + rng.randrange(W)] = c


def _ambient_grid(W, H, step):
    return (W + step - 1) // step, (H + step - 1) // step


def _ambient_expand(field, W, H, sw, step, pal):
    """Expand a regularly sampled field using nearest-neighbour cells."""
    if step == 2:
        out = []
        for i in range(0, len(field), sw):
            colors = list(map(pal.__getitem__, field[i:i + sw]))
            row = [0] * (2 * sw)
            row[::2] = row[1::2] = colors
            row = row[:W]
            out.extend(row)
            out.extend(row)
        return out[:W * H]
    out = []
    for i in range(0, len(field), sw):
        row = [c for k in field[i:i + sw] for c in (pal[k],) * step][:W]
        out.extend(row * step)
    return out[:W * H]


@lru_cache(maxsize=3)
def _field_blends(step):
    """Weights for integer palette indices between adjacent field samples."""
    return tuple(tuple(bytes((a*(step-phase)+b*phase)//step for b in range(256))
                       for a in range(256))
                 for phase in range(1,step))


class _FieldGrid:
    """Keep smooth field work bounded and interpolate before drawing details."""

    def __init__(self, width, height, limit):
        self.W, self.H = width, height
        self.step = max(2, round(sqrt(width*height/limit)))
        self.sw, self.sh = _ambient_grid(width, height, self.step)
        self.blends = _field_blends(self.step) if self.step > 2 else ()

    def expand(self, indices, palette):
        if self.step == 2:
            return up2(indices, self.sw, self.sh, self.W, self.H, palette)

        sw, step = self.sw, self.step
        rows = [indices[i:i+sw] for i in range(0, len(indices), sw)]
        rows.append(rows[-1])
        output = []
        for y in range(self.H):
            iy, phase = divmod(y, step)
            samples = rows[iy]
            if phase:
                blend = self.blends[phase-1]
                samples = [blend[a][b] for a,b in zip(samples,rows[iy+1])]
            right = samples[1:]+samples[-1:]
            row = [0]*(sw*step)
            row[::step] = map(palette.__getitem__, samples)
            for phase, blend in enumerate(self.blends, 1):
                row[phase::step] = [palette[blend[a][b]] for a,b in zip(samples,right)]
            output.extend(row[:self.W])
        return output


def _ambient_smooth(v):
    v = max(0., min(1., v))
    return v * v * (3 - 2 * v)


class Koi(Scene):
    """Patterned koi wind through caustic light and flowering lily pads."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 52000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.scale = max(.26, _ambient_scale(W, H, self.S))
        self.grid = _FieldGrid(W,H,10_000) if self.gfx else None
        self.sw,self.sh = ((self.grid.sw,self.grid.sh) if self.grid
                           else _ambient_grid(W,H,2))
        self.water = _ambient_palette(((0, 0x06222B), (.56, 0x0B3B44), (.83, 0x145059), (1, 0x297270)))
        self.vignette = [[max(0., 139 - 140 * ((x / self.sw - .5)**2 + (y / self.sh - .48)**2))
                          for x in range(self.sw)] for y in range(self.sh)]
        colors = (0xFF6A1A, 0xF4EFE6, 0xFFB000, 0x242732, 0xF4EFE6, 0xDC4B2C, 0xE8AD50)
        self.fish = [(i * TAU / 7 + rng.uniform(-.14, .14), rng.uniform(.17, .29),
                      rng.uniform(.22, .39), self.scale * rng.uniform(.77, 1.13), c)
                     for i, c in enumerate(colors[:max(5, min(7, int(self.logical_area // 2000) + 1))])]
        self.pads = [(int(W * x), int(H * y), max(1, round(self.scale * r)), a, i % 3 != 1)
                     for i, (x, y, r, a) in enumerate(((.13,.21,7,1),(.21,.14,4,3),(.87,.26,7,4),
                                                       (.91,.34,4,2),(.12,.75,7,5),(.20,.80,5,1),
                                                       (.77,.86,6,3),(.86,.89,4,4)))]
        self.petals = [(rng.random()*W, rng.random()*H, rng.random()*TAU) for _ in range(12)]

    def _head(self, t, phase, fx, fy):
        W, H = self.W, self.H
        ax, ay = t * fx + phase, t * fy + phase * 1.38
        x = W * (.5 + .30 * cos(ax) + .055 * sin(2 * ay))
        y = H * (.5 + .29 * sin(ay) + .047 * cos(2 * ax))
        vx = W * (-.30 * fx * sin(ax) + .11 * fy * cos(2 * ay))
        vy = H * (.29 * fy * cos(ay) - .094 * fx * sin(2 * ax))
        angle = atan2(vy, vx)
        return x, y, cos(angle), sin(angle), hypot(vx,vy)

    def frame(self, t, dt):
        W, H = self.W, self.H
        # Rows share two axes of the caustic net; only the oblique leg varies per cell.
        p = t * .35
        field_scale = self.S * 2 / self.grid.step if self.grid else self.S
        ax = [sin(x*.42/field_scale+p) for x in range(self.sw)]
        bx = [sin(x*.26/field_scale-p*.84) for x in range(self.sw)]
        f = []
        for y, base in enumerate(self.vignette):
            a, b = sin(y*.53/field_scale-p*.75), y*.37/field_scale+p*.61
            f.extend(int(v + 91 * (1 - abs((u + a) * w * sin(x*.22/field_scale+b)) / 2)**7)
                     for x, (u, w, v) in enumerate(zip(ax, bx, base)))
        buf = self.grid.expand(f, self.water) if self.grid else up2(f, self.sw, self.sh, W, H, self.water)
        for i, (phase, fx, fy, s, c) in enumerate(self.fish):
            x, y, ux, uy, speed = self._head(t, phase, fx, fy)
            points = [(x,y,max(1,round(2.5*s)))]
            along = t
            px,py = x,y
            for k, width in enumerate((3.2, 3.9, 4.1, 3.8, 3.4, 2.9, 2.4, 1.8, 1.3, 1, .7),1):
                along -= min(.42,1.55*s/max(.2,speed))
                hx,hy,tx,ty,speed = self._head(along, phase, fx, fy)
                dx,dy = hx-px,hy-py
                length = hypot(dx,dy)
                if length < .12:
                    dx,dy,length = -tx,-ty,1.
                px,py = px+dx*1.55*s/length,py+dy*1.55*s/length
                sway = s*(k/11)**1.55*4.3*sin(t*5.8-k*.53+phase)
                points.append((px-sway*ty,py+sway*tx,max(1,round(width*s))))
            for px, py, r in points:
                ix, iy = round(px), round(py)
                if 0 <= ix < W and 0 <= iy < H:
                    _ambient_disc(buf, W, H, px+2*s, py+3*s, r, shade(buf[iy*W+ix], 148))
            for sign in (-1, 1):
                px, py, _ = points[3]
                fxp, fyp = px - ux*4*s - sign*uy*5.4*s, py - uy*4*s + sign*ux*5.4*s
                line_set(buf, W, H, px, py, fxp, fyp, shade(c, 172))
                line_set(buf, W, H, px-ux*s, py-uy*s, fxp, fyp, shade(c, 118))
            px, py, _ = points[-1]
            wx, wy, _ = points[-3]
            a = atan2(py-wy, px-wx)
            for k in range(-3, 4):
                wing = a + k*.22
                line_set(buf, W, H, px, py, px+cos(wing)*5.5*s, py+sin(wing)*5.5*s,
                         shade(c, 152 + (3-abs(k))*21))
            for k in range(11, -1, -1):
                px, py, r = points[k]
                pigment = c
                if i in (1, 4) and k in (1, 2, 5, 6, 9):
                    pigment = 0xDC511B if k != 6 else 0x33303A
                if i == 3 and 3 <= k <= 5:
                    pigment = 0xD8CFC0
                _ambient_disc(buf, W, H, px, py, r, shade(pigment, 147))
                _ambient_disc(buf, W, H, px - uy*.45*s, py - .55*s, max(0, r-1), pigment)
            for sign in (-1, 1):
                plot(buf, W, H, round(x - sign*uy*1.5*s), round(y + sign*ux*1.5*s), 0x1C1720)
        age = t % 8.3
        if age < 2.5:
            phase, fx, fy, _, _ = self.fish[int(t / 8.3) % len(self.fish)]
            x, y, _, _, _ = self._head(t-age, phase, fx, fy)
            r = self.scale * (2 + 10*age)
            c = shade(0x2A6B70, int(192 * sin(PI * age / 2.5)))
            samples = self.px(56)
            for k in range(samples):
                a = k*TAU/samples
                plota(buf, W, H, round(x+cos(a)*r), round(y+sin(a)*r), c)
        for x, y, r, a, flower in self.pads:
            _ambient_disc(buf, W, H, x+1, y+1, r, 0x0B2825)
            _ambient_disc(buf, W, H, x, y, r, 0x37624D)
            _ambient_disc(buf, W, H, x, y-1, max(0, r-1), 0x447958)
            for q in (-.22, 0, .22):
                line_set(buf, W, H, x, y, x+cos(a+q)*r, y+sin(a+q)*r, 0x0E3A40)
            if flower:
                for k in range(7):
                    p = k*TAU/7 + a
                    _ambient_disc(buf, W, H, x+cos(p)*r*.38, y+sin(p)*r*.38, r//3,
                                  0xFF9EC4 if k % 2 else 0xC9689F)
                plot(buf, W, H, x, y, 0xFFD49B)
        for x, y, p in self.petals:
            plot(buf, W, H, int((x + t*.7*self.S) % W), int((y + 2*self.S*sin(t*.31 + p)) % H), 0xC17A96)
        return buf


class Bokeh(Scene):
    """City lights drift across three depths while the lens slowly refocuses."""
    fps = 14
    mask = 0xF8F8F8
    gfx_pixels = 63000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W, H, ((0,(7,9,15)), (.60,(12,15,22)), (1,(12,11,16))))
        for y in range(H):
            vertical = (2*y/max(1,H-1)-1)**2
            for x in range(W):
                horizontal = (2*x/max(1,W-1)-1)**2
                i = y*W+x
                self.bg[i] = shade(self.bg[i], 256-int(47*(horizontal+vertical)))
        self.colors = (0xFFA53D, 0xFFC779, 0xEF3830, 0x43C9B2, 0xE7F1F9)
        s = _ambient_scale(W, H, self.S)
        self.radii = [max(2,round(s*r)) for r in (4,7,11)]
        self.sprites = {}
        largest = max(self.radii)
        self.sprite_radii = sorted(set(self.radii+[1]+[max(1,round(largest*j/7)) for j in range(1,8)]))
        if not self.gfx:
            self.sprite_radii = list(range(1,largest+1))
        for color in self.colors:
            for r in self.sprite_radii:
                shape = []
                for y in range(-r, r+1):
                    for x in range(-r, r+1):
                        d = hypot(x, y)/(r+.2)
                        if d < 1.03:
                            edge = _ambient_smooth((1.03-d)/.24)
                            v = (.36+.34*(1-d*d))*edge
                            shape.append((x, y, v if r > 1 else 1-d*.62))
                self.sprites[color, r] = [[(x,y,pixel) for x,y,v in shape
                                           if (pixel := shade(color, int(v*level*32)))]
                                          for level in range(1,9)]
        self.lights = []
        for layer in range(3):
            n = max(5, min((24, 19, 12)[layer], int(self.logical_area//(465+layer*205))))
            for _ in range(n):
                color = rng.choices(self.colors, (33,23,15,14,15))[0]
                self.lights.append((layer, rng.uniform(-.08*W,1.08*W), rng.uniform(-.08*H,1.08*H),
                                    rng.uniform(-2,2)*self.S, rng.uniform(-1,1)*self.S, rng.random()*TAU, color))

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        focus = min(1., _ambient_smooth((t%25-17)/2.5), _ambient_smooth((25-t%25)/2.5))
        for layer,x,y,vx,vy,p,color in self.lights:
            r = max(1,round(self.radii[layer]*(1-.94*focus)))
            if self.gfx:
                r = min(self.sprite_radii,key=lambda radius:abs(radius-r))
            u = .5+.5*sin(t*.38+p)
            lv = min(7, int(1+layer+u*3+focus*2))
            margin = self.radii[layer]
            x = int((x+t*vx*(layer+1)*.58+3*self.S*cos(t*.35+p)+margin)%(W+2*margin)-margin)
            y = int((y+t*vy*(layer+1)*.42+2*self.S*sin(t*.42+p)+margin)%(H+2*margin)-margin)
            stamp(buf,W,H,x,y,self.sprites[color,r][lv])
        return buf


class _ReflectionColors(dict):
    """Per-level lookup for repeated colors in a lantern reflection."""

    def __init__(self, colors, level):
        super().__init__((color, shade(color, level)) for color in colors)
        self.level = level
        self.limit = len(self) + 640

    def __missing__(self, color):
        dimmed = shade(color, self.level)
        if len(self) < self.limit:
            self[color] = dimmed
        return dimmed


class Lanterns(Scene):
    """Warm sky lanterns ascend over a dark lake that mirrors their glow."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 64000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.shore = int(H*.66)
        self.bg = vgrad(W,H,((0,(4,6,26)),(.43,(26,16,64)),(.66,(64,32,74)),(1,(6,10,26))))
        if self.gfx_reference:
            rw,rh = self.gfx_reference
            stars = [0]*(rw*rh)
            _ambient_stars(stars,rw,rh,rng,max(18,int(self.logical_area//170)),max(1,int(rh*.55)))
            for i,c in enumerate(stars):
                if c:
                    y,x = divmod(i,rw)
                    plota(self.bg,W,H,x*W//rw,y*H//rh,c)
        else:
            _ambient_stars(self.bg,W,H,rng,max(18,int(self.logical_area//170)),max(1,int(H*.55)))
        for x in range(W):
            for depth,c in enumerate((0x251A38,0x130F28,0x090D20)):
                y = int(self.shore-H*(.047-depth*.012)
                        -H*(.038-depth*.009)*(sin(x/W*10+depth*2)+.45*sin(x/W*24+depth)))
                y = max(0,min(self.shore,y))
                self.bg[y*W+x:self.shore*W+x:W] = [c]*(self.shore-y)
        s = max(.25, _ambient_scale(W,H,self.S))
        self.lanterns = [(rng.uniform(.05,.95)*W, rng.uniform(3,9)*s,
                          rng.randrange(3), rng.random()*TAU, rng.random()*(self.shore+12*self.S))
                         for _ in range(max(24,min(54,int(self.logical_area//335))))]
        self.reflection = None
        if self.gfx:
            colors = set(self.bg)
            self.reflection = [_ReflectionColors(colors, level) for level in range(84,115)]
        self.forms = []
        for depth in range(3):
            r = max(1,round(s*(2+depth)))
            h = max(2,round(s*(5+depth*2)))
            halo = make_sprite(0x9C4328, max(2,r*3), 6, 2.1)
            rows = [max(0,round(r*(.69+.30*sin(PI*(j+.5)/h)) - j/h*.65)) for j in range(h)]
            fills = [(shade(0xEF7D39,lv),shade(0xFFF2B0,lv),shade(0xFFAB4E,lv))
                     for lv in (85,115,146,175,210,244)]
            self.forms.append((h,rows,halo,fills))

    def frame(self,t,dt):
        W,H,L = self.W,self.H,self.shore
        buf = self.bg[:]
        for x,speed,depth,p,start in self.lanterns:
            h,rows,halo,fills = self.forms[depth]
            y = int(L-(t*speed+start)%(L+12*self.S))
            xi = int(x+self.S*((2+depth)*sin(t*.56+p)+1.5*sin(t*.19+p)))
            fade = min(1, max(0,(y+h)/max(1,H*.12)), max(0,(L-y)/(5*self.S)))
            if fade <= 0:
                continue
            lv = min(5,int((3.6+depth*.85+.46*sin(t*2.2+p))*fade))
            stamp(buf,W,H,xi,y,halo[lv])
            edge,core,base = fills[lv]
            for j,half in enumerate(rows):
                yy = y+j-h//2
                if 0 <= yy < L:
                    fill_row(buf,W,yy,max(0,xi-half),min(W,xi+half+1),edge if j < h-1 else base)
                    if j and half:
                        plot(buf,W,H,xi,yy,core)
            if depth and lv >= 3:
                plota(buf,W,H,xi+int(3*sin(t+p)),y+h//2+int((t*3+p)%6),0x663719)
        # Each lake row samples the composite sky so moving lanterns and hills reflect together.
        for y in range(L,H):
            sy = max(0,L-1-int((y-L)*1.22))
            shift = round(self.S*(2.1*sin(y*.64/self.S-t*1.15)+1.5*sin(y*.23/self.S+t*.71)))
            row = buf[sy*W:(sy+1)*W]
            row = row[shift:]+row[:shift]
            level = 99 + int(15*sin(y*.74/self.S+t*.64))
            if self.reflection:
                reflection = list(map(self.reflection[level-84].__getitem__, row))
            else:
                reflection = [shade(c,level) for c in row]
            buf[y*W:(y+1)*W] = reflection
        return buf


class Nebula(Scene):
    """Warped clouds and diffraction stars drift through a stellar nursery."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 57000
    gfx_fps = 20

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.grid = _FieldGrid(W,H,13_000) if self.gfx else None
        self.sw,self.sh = ((self.grid.sw,self.grid.sh) if self.grid
                           else _ambient_grid(W,H,2))
        self.pal = _ambient_palette(((0,0x030311),(.28,0x100A2F),(.46,0x211748),
                                    (.60,0x126E70),(.70,0x337E89),(.80,0x8F2683),
                                    (.92,0xE94C85),(1,0xFFC971)))
        self.field = []
        for y in range(self.sh):
            v = y/self.sh-.5
            for x in range(self.sw):
                u = x/self.sw-.5
                a = u*12.8+v*6.6 + 1.42*sin(v*10-u*4)
                b = v*14.4-u*7.9 + 1.90*cos(u*10+v*5)
                self.field.append((a,b,a*2.1+b*.43,max(0,1-1.25*u*u-2.18*v*v)))
        self.stars = [(self.detail_coord(W),self.detail_coord(H, True),rng.random()*TAU,
                       rng.choice((0xFFDAAA,0x9DBEFF,0xCCD9FF)),rng.randrange(38,160))
                      for _ in range(max(38,min(245,int(self.logical_area//53))))]
        self.glow = make_sprite(0xEA5685,max(3,round(12*_ambient_scale(W,H,self.S))),8,2.2)

    def frame(self,t,dt):
        W,H = self.W,self.H
        p = t*.055
        idx = [int(max(0,min(255, 39 + g*(74+58*sin(a+p+.64*sin(b-p*.67))
                                          +37*cos(b+p*.53)+31*sin(c-p*.79)))))
               for a,b,c,g in self.field]
        buf = self.grid.expand(idx, self.pal) if self.grid else up2(idx,self.sw,self.sh,W,H,self.pal)
        drift = int(t*.125*self.S)%W
        rim = min(105, round(100*max(0., self.detail_scale-1.)))
        for i,(x,y,a,c,v) in enumerate(self.stars):
            xi = (x+drift)%W
            lv = int(v*(.75+.24*sin(t*.92+a)))
            light = shade(c,lv)
            plota(buf,W,H,xi,y,light)
            if rim:
                _gfx_point_rim(buf,W,H,xi,y,shade(light,rim))
            if i%19 == 0:
                for d in (-2,-1,1,2):
                    glint = shade(c,lv//(2+abs(d)))
                    plota(buf,W,H,xi+round(d*self.S),y,glint)
                    plota(buf,W,H,xi,y+round(d*self.S),glint)
        for x,y,a in ((.40,.39,0),(.68,.59,2.7),(.52,.67,1.4)):
            xi,yi = int(W*x+W*.024*sin(p+a)),int(H*y+H*.022*cos(p+a))
            stamp(buf,W,H,xi,yi,self.glow[4+int(2+1.9*sin(p*4+a))])
            plota(buf,W,H,xi,yi,0xF2AE89)
        return buf


class Prism(Scene):
    """A rotating glass prism bends a white beam into a soft spectrum."""
    fps = 14
    mask = 0xF8F8F8
    gfx_pixels = 64000

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [0x060712]*(W*H)
        self.grains = [(rng.random(),rng.uniform(-2,2)*self.S,rng.random()*TAU) for _ in range(21)]
        self.spectrum = [(c,shade(c,106),shade(c,46),shade(c,20))
                         for c in (0xFF2A2A,0xFF8A1F,0xFFE11F,0x3BFF5A,0x1FD5FF,0x3A52FF,0xA83BFF)]
        self.glint = make_sprite(0xACC9E1,max(2,round(min(W,H)*.074)),8,2)

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        s = min(W,H)
        cx,cy = W*.47,H*.49
        spin = .435*sin(t*.31)
        corners = [(cx+s*.24*cos(a+spin),cy+s*.24*sin(a+spin))
                   for a in (-PI/2,PI/6,5*PI/6)]
        beam = cy+s*.025*sin(t*.48+.7)
        edges = list(zip(corners,corners[1:]+corners[:1]))
        entry = min(ax+(bx-ax)*(beam-ay)/(by-ay)
                    for ((ax,ay),(bx,by)) in edges if min(ay,by) <= beam < max(ay,by))
        (ax,ay),(bx,by) = corners[:2]
        out_y = beam+s*(.047+.06*sin(spin))
        out_x = ax+(bx-ax)*(out_y-ay)/(by-ay)
        # Fill the triangle and shade the glass toward its upper facet.
        for y in range(max(0,math.ceil(min(p[1] for p in corners))),
                       min(H,math.ceil(max(p[1] for p in corners)))):
            hits = [a+(c-a)*(y-b)/(d-b) for (a,b),(c,d) in edges if min(b,d) <= y < max(b,d)]
            if len(hits) == 2:
                fill_row(buf,W,y,max(0,math.ceil(min(hits))),min(W,math.ceil(max(hits))),
                         mix(0x173043,0x0B1022,int(256*(y-min(p[1] for p in corners))/(s*.48))))
        for j,colors in enumerate(self.spectrum):
            pulse = int(171+28*sin(t*.61+j*.13))
            colors = tuple(shade(c,pulse) for c in colors)
            for x in range(max(0,math.ceil(out_x)),W):
                d = x-out_x
                center = int(out_y+d*(.20+spin*.53+(j-3)*.087))
                width = self.px(1)+int(d*.029)
                for k in range(-width-2,width+3):
                    band = max(0,abs(k)-width+1)
                    plota(buf,W,H,x,center+k,colors[min(3,band)])
        stroke = _gfx_line_set if self.gfx else line_add
        for (x0,y0),(x1,y1) in edges:
            line_add(buf,W,H,x0,y0+1,x1,y1+1,0x1C3D52)
            stroke(buf,W,H,x0,y0,x1,y1,0x4F8398)
        for k,c in ((-2,0x0B1020),(-1,0x2D3B4C),(1,0x293242),(2,0x0B1020),(0,0xB5BDC6)):
            line_add(buf,W,H,0,beam+k*self.S,entry,beam+k*self.S,c)
        stroke(buf,W,H,entry,beam,out_x,out_y,0x667585)
        line_add(buf,W,H,entry,beam-1,out_x,out_y-1,0x25394A)
        stamp(buf,W,H,round(entry),round(beam),self.glint[6])
        line_add(buf,W,H,entry,beam-s*.055,entry,beam+s*.055,0x344B61)
        for i,(x,y,p) in enumerate(self.grains):
            plot(buf,W,H,int(((x+t*.06)%1)*entry),round(beam+y),
                 shade(0xE8EDFF,int(139+95*sin(t*.76+p))))
        return buf


class Flyover(Scene):
    """A banked golden-hour flight over interpolated volcanic ridges."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 55000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W,H = self.W,self.H
        self.bg = vgrad(W,H,((0,(27,42,90)),(.21,(83,72,117)),(.42,(216,122,105)),
                             (.57,(255,155,112)),(1,(233,160,124))))
        r = max(2,round(min(W,H)*.048))
        x,y = round(W*.74),round(H*.30)
        stamp(self.bg,W,H,x,y,make_sprite(0xBB752B,r*5,3,2.2)[-1])
        stamp(self.bg,W,H,x,y,make_sprite(0xFFE0A0,r*2,1,2.)[0])
        _ambient_disc(self.bg,W,H,x,y,r,0xFFE1A2)
        axis = [i*TAU/256 for i in range(256)]
        self.height = [22+13*sin(2*x+y)+9*cos(3*y-x)
                       +11*abs(sin(4*x-3*y))**1.7+3*sin(13*x+8*y)+2*cos(21*y-11*x)
                       for y in axis for x in axis]
        earth = _ambient_palette(((0,0x122520),(.33,0x315344),(.52,0x557055),
                                   (.66,0x6D5C56),(.80,0xC09272),(.88,0xD9BAAA),(1,0xFFF0DB)),64)
        self.terrain = []
        for y in range(256):
            for x in range(256):
                i = y*256+x
                a = self.height[i]
                dx = self.height[y*256+((x+1)&255)]-self.height[y*256+((x-1)&255)]
                dy = self.height[((y+1)&255)*256+x]-self.height[((y-1)&255)*256+x]
                ink = shade(earth[max(0,min(63,round(a)))],int(205-11*dx+8*dy))
                self.terrain.append(ink)
        self.layers = []
        z = 2.6
        while z < 194:
            distance_fog = 1-exp(-z/116)
            glare = .20*exp(-z/15)
            self.layers.append((z,H*.83/z,int(248*(distance_fog+glare))))
            z += .37+z*.16 if z<17 else .72+z*.20

    def _height(self,x,y):
        ix,iy = math.floor(x),math.floor(y)
        u,v = x-ix,y-iy
        ht = self.height
        a,b = (iy&255)*256,((iy+1)&255)*256
        c,d = ix&255,(ix+1)&255
        h0,h1 = ht[a+c],ht[b+c]
        return h0+(ht[a+d]-h0)*u+(h1-h0)*v+((ht[b+d]-h1)-(ht[a+d]-h0))*u*v

    @staticmethod
    def _terrain_ink(terrain, ix, iy, u, v, fog):
        row,next_row = (iy&255)*256,((iy+1)&255)*256
        left,right = ix&255,(ix+1)&255
        horizontal = int(256*u)
        a = mix(terrain[row+left],terrain[row+right],horizontal)
        b = mix(terrain[next_row+left],terrain[next_row+right],horizontal)
        return mix(mix(a,b,int(256*v)),0xE9A07C,fog)

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        cx,cy = 120+44*sin(t*.085),t*12
        a = .48*cos(t*.085)
        fx,fy = sin(a),cos(a)
        altitude = 21+.74*self._height(cx,cy)+.26*self._height(cx+fx*16,cy+fy*16)+1.15*sin(t*.62)
        shear = .057*sin(t*.085)
        horizon = H*.43-W*.5*shear
        top = [H]*W
        ht,terrain = self.height,self.terrain
        floor,ceil = math.floor,math.ceil
        stride = 3 if W*H<=75_000 else 4
        fractions = [i/stride for i in range(stride)]
        weights = [round(256*f) for f in fractions]
        for z,zoom,fade in self.layers:
            x0,y0 = cx+z*(fx-fy*.67),cy+z*(fy+fx*.67)
            dx,dy = z*fy*1.34/W,-z*fx*1.34/W
            last_y = horizon+(altitude-self._height(x0,y0))*zoom
            previous = (floor(x0),floor(y0),x0%1,y0%1)
            for start in range(0,W,stride):
                end = start+stride
                x,y = x0+end*dx,y0+end*dy
                ix,iy = floor(x),floor(y)
                u,v = x-ix,y-iy
                left,right = ix&255,(ix+1)&255
                row,next_row = (iy&255)*256,((iy+1)&255)*256
                a,b = ht[row+left],ht[next_row+left]
                terrain_y = a+(ht[row+right]-a)*u
                terrain_y += (b+(ht[next_row+right]-b)*u-terrain_y)*v
                next_y = horizon+end*shear+(altitude-terrain_y)*zoom
                delta = next_y-last_y
                start_color = end_color = None
                for offset in range(min(stride,W-start)):
                    x = start+offset
                    edge = last_y+delta*fractions[offset]
                    top_y = max(0,ceil(edge))
                    old_top = top[x]
                    if top_y >= old_top:
                        continue
                    if start_color is None:
                        start_color = self._terrain_ink(terrain,*previous,fade)
                        end_color = self._terrain_ink(terrain,ix,iy,u,v,fade)
                    ink = mix(start_color,end_color,weights[offset]) if offset else start_color
                    buf[top_y*W+x:old_top*W+x:W] = [ink]*(old_top-top_y)
                    if top_y and top_y-edge>.04:
                        i = (top_y-1)*W+x
                        buf[i] = mix(buf[i],ink,int(256*(top_y-edge)))
                    top[x] = top_y
                last_y = next_y
                previous = ix,iy,u,v
        return buf


class Attractor(Scene):
    """Three luminous trajectories reveal four strange attractors in perspective."""
    fps = 13
    mask = 0xF0F0F0

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [shade(0x10132D, int(28+53*max(0,1-3*((x/W-.5)**2+(y/H-.5)**2))))
                   for y in range(H) for x in range(W)]
        _ambient_stars(self.bg,W,H,rng,max(16,int(self.logical_area//280)),H)
        self.ramps = [_ambient_palette(((0,0x030617),(.37,a),(.79,b),(1,0xFFF1E7)),64)
                      for a,b in ((0x243C9F,0x55E6FF),(0x8B2F80,0xFFB358),(0x155C59,0x81FFCD))]
        self.head_glow = make_sprite(0xA788C2,max(2,self.px(2)),1,2.)[0]
        self.length = 1280
        stride = 7 if self.gfx else 9
        tail = 360
        self.ages = (*range(self.length-1,tail,-stride),
                     *range(tail,-1,-(3 if self.gfx else 4)))
        self.trail_colors = []
        for ramp in self.ramps:
            colors = []
            for age in self.ages:
                p = 1-age/self.length
                colors.append(shade(ramp[int(63*p)],int(23+118*p*p)))
            self.trail_colors.append(colors)
        self.mode = None
        self.bundle = None
        self.advance_remainder = 0.
        self.steps = (.008,.018,.073,.015)
        self.normalize = ((0,0,24,.080),(0,0,.75,.84),(0,0,0,.46),(0,0,0,.19))
        self.seeds = ((1.,1.,18.),(.18,.19,.09),(.13,1.,-.31),(-4.,-.8,2.))

    @staticmethod
    def _flow(mode,x,y,z):
        if mode == 0:
            return 10*(y-x),x*(28-z)-y,x*y-(8/3)*z
        if mode == 1:
            return (z-.7)*x-3.5*y,3.5*x+(z-.7)*y,.6+.95*z-z*z*z/3-(x*x+y*y)*(1+.25*z)+.1*z*x*x*x
        if mode == 2:
            return sin(y)-.208186*x,sin(z)-.208186*y,sin(x)-.208186*z
        return -1.89*x-4*y-4*z-y*y,-1.89*y-4*z-4*x-z*z,-1.89*z-4*x-4*y-x*x

    def _advance(self, mode, bundle, steps):
        h = self.steps[mode]
        for trail in bundle:
            points,head = trail
            x,y,z = points[head]
            for _ in range(steps):
                dx,dy,dz = self._flow(mode,x,y,z)
                dx,dy,dz = self._flow(mode,x+.5*h*dx,y+.5*h*dy,z+.5*h*dz)
                x,y,z = x+h*dx,y+h*dy,z+h*dz
                head = (head+1)%len(points)
                points[head] = (x,y,z)
            trail[1] = head

    def _bundle(self,mode):
        x,y,z = self.seeds[mode]
        bundle = []
        for i in range(3):
            trail = [[(x+i*.0017,y-i*.001,z)]*self.length,0]
            self._advance(mode,[trail],self.length+340+i*146)
            bundle.append(trail)
        return bundle

    @staticmethod
    def _trail_segment(buf,width,x0,y0,x1,y1,color):
        # Projection already fits the complete polyline inside the framebuffer.
        dx,dy = abs(x1-x0),-abs(y1-y0)
        step_x = 1 if x1>x0 else -1
        step_y = width if y1>y0 else -width
        offset = y0*width+x0
        error = dx+dy
        for _ in range(max(dx,-dy)):
            previous = buf[offset]
            total = previous+color
            overflow = (total^previous^color)&0x1010100
            if overflow:
                total = (total|(overflow-(overflow>>8)))&0xFFFFFF
            buf[offset] = total
            e2 = error+error
            if e2>=dy:
                error += dy
                offset += step_x
            if e2<=dx:
                error += dx
                offset += step_y

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        section = t/70
        cycle = int(section)
        mode = cycle%4
        if self.mode != cycle:
            self.mode = cycle
            self.bundle = self._bundle(mode)
        phase = section%1
        fade = _ambient_smooth(min(phase,1-phase)/.033) if cycle or phase>.5 else 1.
        a = (t*.093)%TAU
        ca,sa = cos(a),sin(a)
        pitch = .29+.17*sin(t*.071)
        cp,sp = cos(pitch),sin(pitch)
        zoom = min(W,H)*(1.07+.11*sin(t*.027))
        steps = 4
        if self.gfx:
            self.advance_remainder += dt*type(self).fps*4
            steps = int(self.advance_remainder)
            self.advance_remainder -= steps
        length = self.length
        self._advance(mode,self.bundle,steps)
        ox,oy,oz,s = self.normalize[mode]
        projected = []
        extent = 1.
        for points,head in self.bundle:
            trace = []
            for age in self.ages:
                x,y,z = points[(head-age)%length]
                x,y,z = (x-ox)*s,(y-oy)*s,(z-oz)*s
                u,w = x*ca-z*sa,x*sa+z*ca
                v = y*cp-w*sp
                z = 4.1+y*sp+w*cp
                k = zoom/max(.65,z)
                px,py = u*k,v*k
                extent = max(extent,abs(px)/(W*.43),abs(py)/(H*.42))
                trace.append((px,py))
            projected.append(trace)
        fit = 1/extent
        fade_level = int(256*fade)
        for trace,colors in zip(projected,self.trail_colors):
            old_x = old_y = None
            for (x,y),age,color in zip(trace,self.ages,colors):
                px,py = W*.5+x*fit,H*.5-y*fit
                ix,iy = round(px),round(py)
                if fade_level<256:
                    color = shade(color,fade_level)
                if old_x is not None and color:
                    if self.gfx and age<102:
                        _gfx_line_add(buf,W,H,prev_x,prev_y,px,py,color)
                    elif ix!=old_x or iy!=old_y:
                        self._trail_segment(buf,W,old_x,old_y,ix,iy,color)
                old_x,old_y = ix,iy
                prev_x,prev_y = px,py
            if old_x is not None and fade:
                x,y = old_x,old_y
                stamp(buf,W,H,x,y,self.head_glow)
                plota(buf,W,H,x,y,shade(0xFFF0C3,int(239*fade)))
        return buf


class Jellyfish(Scene):
    """Pulsing translucent bells tow bioluminescent tentacles through falling marine snow."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 64000
    gfx_fps = 20

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = vgrad(W,H,((0,(3,20,39)),(.5,(4,15,33)),(1,(0,4,13))))
        self.snow = [(self.detail_coord(W),self.detail_coord(H,True),rng.uniform(.5,2.8),rng.random()*TAU)
                     for _ in range(max(24,min(180,int(self.logical_area//95))))]
        self.jellies = []
        colors = (0x738DEE,0x5BCAF3,0xA98BFF,0xFF6BD6,0x8FF7FF,0xED9BD7,0x8FF7FF)
        for i,c in enumerate(colors[:max(5,min(7,int(self.logical_area//4800)+4))]):
            phase = rng.random()*TAU
            size = max(2,min(16*self.S,min(W,H)*(.058+i*.014)))
            x = W*(.10+(.79*i/6))
            y = H*(.22 + (.23 if i%2 else 0)+.13*sin(phase))
            chains = []
            for j in range(6):
                anchor = (j-2.5)/3.0
                nodes = [[x+size*anchor,y+k*size*.28,x+size*anchor,y+k*size*.28] for k in range(12)]
                chains.append((anchor,nodes))
            bell = []
            inner_color = mix(c, 0xECF7FF, 96)
            for width in range(1,round(size)+2):
                height = max(2,round(width*.65))
                shape = []
                for yy in range(-height,self.px(2)):
                    for xx in range(-width,width+1):
                        q = xx*xx/(width+.5)**2 + yy*yy/(height+.5)**2
                        if q <= 1:
                            edge = q>.71 or yy==self.px(2)-1
                            rib = yy < 0 and (xx % max(2,width//3) == 0)
                            level = (95 if edge else 29)+(55 if rib else 0)+int(34*(1-q))
                            color = shade(c,level)
                            if self.gfx and yy < 0:
                                core = ((xx/(width+.5))**2
                                        + ((yy+height*.37)/(height+.5))**2)
                                glow = int(121*max(0., 1.-2.35*core)*(1-q))
                                color = addp(color, shade(inner_color, glow))
                            shape.append((xx,yy,color))
                bell.append(shape)
            self.jellies.append([x,y,size,phase,c,chains,bell,0.,None,None])

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        rays = ((.12,.21),(.39,.16),(.71,.12),(.91,-.2))
        filament = min(1.55, self.detail_scale) if self.detail_scale >= 1.24 else 1.
        for j,(x,v) in enumerate(rays):
            bend = .026*sin(t*.17+j)
            for k in range(-2,3):
                line_add(buf,W,H,W*x+k*self.S,0,W*(x+v+bend)+k*2*self.S,H*.62,0x010306)
        for x,y,v,p in self.snow:
            plota(buf,W,H,int((x+2*self.S*sin(t*.27+p))%W),int((y+t*v*self.S)%H),
                  shade(0x6E96AB,int(26+23*v+12*sin(t*.65+p))))
        for i,jelly in enumerate(self.jellies):
            ox,oy,size,phase,c,chains,bell,drift,previous,last_x = jelly
            p = (t+phase)%2.9
            contract = _ambient_smooth(p/.35)*(1-_ambient_smooth((p-.35)/1.9))
            if previous is not None and p < previous:
                drift -= size*.70
            jelly[7] = drift*exp(-dt*2.0)
            jelly[8] = p
            x = ox+min(W*.075,size*1.35)*sin(t*.29+phase)
            y = oy+H*.13*sin(t*.21+phase)+size*.38*cos(t*.36+phase)+drift
            if size > min(W,H)*.112:
                y += H*.17*sin(t*.092+phase*.44)
            if i >= 5:
                # The outer lane is wide enough for the complete bell and chains to leave view.
                x = (x + t*W*.013 + 2.5*size)%(W+5*size) - 2.5*size
                if last_x is None or abs(x-last_x)>W*.55:
                    for anchor,nodes in chains:
                        for k,node in enumerate(nodes):
                            nx,ny = x+anchor*size,y+k*size*.31
                            node[:] = [nx,ny,nx,ny]
            jelly[9] = x
            r = max(1,round(size*(1-.29*contract)))
            gap = max(.7,size*.38)
            for j,(anchor,nodes) in enumerate(chains):
                nodes[0][:] = [x+anchor*r,y+self.S,x+anchor*r,y+self.S]
                force = .13*self.S*sin(t*1.85+phase+j*.72)
                for node in nodes[1:]:
                    nx,ny,px,py = node
                    node[:] = [nx+(nx-px)*.81+force,ny+(ny-py)*.81+.20*self.S,nx,ny]
                for _ in range(2):
                    for k in range(1,len(nodes)):
                        nx,ny,px,py = nodes[k]
                        dx,dy = nx-nodes[k-1][0],max(gap*.26,ny-nodes[k-1][1])
                        pull = gap/max(.05,hypot(dx,dy))
                        nodes[k][0] = nodes[k-1][0]+dx*pull
                        nodes[k][1] = nodes[k-1][1]+dy*pull
                for k in range(1,len(nodes)):
                    a,b = nodes[k-1],nodes[k]
                    cc = shade(c,max(15,(121 if j in (2,3) else 94)-8*k))
                    line_add(buf,W,H,a[0],a[1],b[0],b[1],cc)
                    if self.gfx:
                        offset = self.S*.52
                        _gfx_line_add(buf,W,H,a[0]+offset,a[1],b[0]+offset,b[1],shade(cc,108),filament)
                    elif j in (2,3) and k < 6:
                        line_add(buf,W,H,a[0]+self.S,a[1],b[0]+self.S,b[1],shade(cc,115))
                a = nodes[int((t*2.4+j+phase)%len(nodes))]
                plota(buf,W,H,round(a[0]),round(a[1]),shade(c,116))
            stamp(buf,W,H,round(x),round(y),bell[r-1])
            plota(buf,W,H,round(x),round(y-1),shade(0xFFB86B,int(52+86*contract)))
        return buf


class Dunes(Scene):
    """Five drifting desert dunes glow under a low moon and streaming sand."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 68000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = vgrad(W,H,((0,(13,27,74)),(.33,(65,52,111)),(.49,(138,79,160)),
                             (.57,(242,160,123)),(1,(99,53,87))))
        _ambient_stars(self.bg,W,H,rng,max(14,int(self.logical_area//241)),max(1,int(H*.40)))
        r = max(1,round(min(W,H)*.053))
        x,y = round(W*.68),round(H*.33)
        stamp(self.bg,W,H,x,y,make_sprite(0x9D6549,r*6,4,2.1)[-1])
        _ambient_disc(self.bg,W,H,x,y,r,0xFFE9B0)
        self.layers = []
        for i,(front,back,crest) in enumerate(((0x62405F,0x875876,0xA983A1),(0x583455,0xA66B73,0xC58689),
                                                (0x49273C,0xBD795B,0xD49269),(0x33213A,0x895044,0xBC7260),
                                                (0x201628,0x532E39,0x966052))):
            self.layers.append((front,back,crest,rng.random()*TAU))
        self.grains = [(rng.randrange(5),rng.random(),rng.uniform(3,13),rng.random()*TAU)
                       for _ in range(max(28,min(136,int(self.logical_area//105))))]

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        for y in range(int(H*.49),int(H*.58)):
            row = buf[y*W:(y+1)*W]
            shift = round(1.2*self.S*sin(y*1.43/self.S+t*.96))
            if shift:
                row = row[shift:]+row[:shift]
            tint = shade(0x302333,int(23*(1+sin(t*.85+y*1.2/self.S))))
            buf[y*W:(y+1)*W] = [addp(c,tint) for c in row]
        crests = []
        for i,(shadow,light,edge,p) in enumerate(self.layers):
            positions = []
            for x in range(W):
                a = (x+t*.15*self.S*(i+1))/W*(7.9+i*1.1)+p
                b = sin(a)+.44*sin(2*a+.78)+.23*sin(3*a-1)+.18*cos(a*.54-i)
                y = max(0,min(H-1,int(H*(.545+i*.084)-H*(.045+i*.005)*b)))
                positions.append(y)
                slope = cos(a)+.88*cos(2*a+.78)+.69*cos(3*a-1)
                cover = (.5+.5*sin(a+.20))**1.2
                face = mix(shadow,light,int(183*cover+32*max(0,cos(slope))))
                buf[y*W+x::W] = [face]*(H-y)
                buf[y*W+x] = shade(edge,int(130+85*cover))
                if y+1 < H:
                    buf[(y+1)*W+x] = mix(edge,face,149)
            crests.append(positions)
        for i,x,v,p in self.grains:
            xi = int((x*W+t*v*self.S)%W)
            fade = sin(t*.88+p)
            y = crests[i][xi]-int(1+(1+fade)*max(1,H*.026))
            if any(y >= crests[k][xi] for k in range(i+1,len(crests))):
                continue
            plota(buf,W,H,xi,y,shade(0xF8B07A,int(27+29*max(0,fade))))
            if fade > .3:
                plota(buf,W,H,xi-1,y,0x21141C)
        age = (t+10)%153
        if 13 < age < 41:
            for j in range(5):
                x = int(W*(1.12-(age-13)/24))+j*max(4,W//26)
                if 0 <= x < W:
                    y = crests[2][x]
                    if y < crests[3][x] and y < crests[4][x]:
                        for dx,dy in ((0,-2),(1,-2),(2,-3),(0,-1),(2,-1),(1,-3)):
                            plot(buf,W,H,x+round(dx*self.S),y+round(dy*self.S),0x262035)
        return buf


class Orrery(Scene):
    """Brass zodiac ticks frame an antique orrery with seven illuminated worlds."""
    fps = 13

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [shade(0x101B35,int(30+54*max(0,1-2*((x/W-.5)**2+(y/H-.5)**2))))
                   for y in range(H) for x in range(W)]
        _ambient_stars(self.bg,W,H,rng,max(17,int(self.logical_area//180)),H)
        self.scale = min(W,H)
        self.radius = self.scale*.45
        tick_gap = 2*max(1.,self.detail_scale)
        width = max(1., min(1.65, self.detail_scale))
        for k in range(120):
            a = k*TAU/120
            length = (.107 if k%10==0 else .043 if k%5==0 else .017)
            x,y = W/2+self.radius*cos(a),H/2+self.radius*.82*sin(a)
            x1 = W/2+self.radius*(1-length)*cos(a)
            y1 = H/2+self.radius*(1-length)*.82*sin(a)
            color = shade(0xB08D57,180 if k%10==0 else 86)
            if self.gfx:
                _gfx_line_set(self.bg,W,H,x,y,x1,y1,color,width)
            else:
                line_set(self.bg,W,H,x,y,x1,y1,color)
            if k%2:
                plot(self.bg,W,H,round(W/2+(self.radius+tick_gap)*cos(a)),
                     round(H/2+(self.radius+tick_gap)*.82*sin(a)),0x55402B)
        self.sun = make_sprite(0xFF8727,max(3,round(self.scale*.174)),8,2.25)
        self.orbits = [(r,e,w,rng.random()*TAU,rng.random()*TAU,c,k)
                       for r,e,w,c,k in ((.16,.10,1.02,0xB6A898,.58),(.26,.12,.67,0xF3CA83,.92),
                                         (.37,.14,.46,0x59A8CE,.91),(.48,.16,.33,0xD7754A,.70),
                                         (.65,.11,.205,0xE0AB78,1.44),(.79,.13,.155,0xD2AF81,1.15),
                                         (.91,.08,.105,0x83C7D7,.92))]
        self.asteroids = [(rng.uniform(.53,.59),rng.random()*TAU,rng.uniform(.24,.30),
                           rng.randrange(37,131)) for _ in range(max(32,min(120,int(self.logical_area//84))))]

    def frame(self,t,dt):
        W,H = self.W,self.H
        cx,cy = W*.5,H*.5
        buf = self.bg[:]
        a = t*TAU/240
        ca,sa = cos(a),sin(a)
        radius = self.radius
        bodies = []
        sunr = max(1,round(self.scale*.054))
        stamp(buf,W,H,round(cx),round(cy),self.sun[5+int(1.9+1.08*sin(t*2.5))//2])
        for i,(r,e,w,start,tilt,c,size) in enumerate(self.orbits):
            u,v = cos(tilt),sin(tilt)
            def project(q):
                x = radius*r*(cos(q)-e)
                y = radius*r*sin(q)*sqrt(1-e*e)
                X,Y = x*(u*ca-v*sa)-y*(v*ca+u*sa), x*(v*ca+u*sa)+y*(u*ca-v*sa)
                depth = Y*.57
                factor = 1+depth/(3*radius)
                return cx+X*factor,cy+Y*.82*factor,depth
            count = 24+i*10
            for k in range(count):
                x,y,z = project(k*TAU/count)
                plota(buf,W,H,round(x),round(y),0x362B20 if z>0 else 0x211C19)
            phase = t*w+start
            phase += e*sin(phase)
            x,y,z = project(phase)
            for k in range(1,15):
                X,Y,_ = project(phase-k*.068)
                plota(buf,W,H,round(X),round(Y),shade(c,(15-k)*7))
            rbody = max(1,round(size*self.scale*.029*(1+z/(3*radius))))
            bodies.append((z,i,x,y,rbody,c))
            for m in range(1 if i==2 else 2 if i==4 else 0):
                q = t*(1.7-m*.47)+m*2.3+i
                distance = rbody+(2.1+m*2)*self.S
                bodies.append((z+distance*sin(q)*.7,-2,x+distance*cos(q),
                               y+distance*sin(q)*.65,0,0xAFA7A1))
        for r,p,v,l in self.asteroids:
            q = p+t*v+a
            x,y = radius*r*cos(q),radius*r*sin(q)
            z = y*.57
            fac = 1+z/(3*radius)
            plota(buf,W,H,round(cx+x*fac),round(cy+y*fac*.82),shade(0xBC926A,l))
        bodies.append((0,-1,cx,cy,sunr,0xFFBD55))
        for z,i,x,y,r,c in sorted(bodies):
            if i == -2:
                plot(buf,W,H,round(x),round(y),c)
                continue
            if i == 5:
                for k in range(self.px(25),self.px(48)):
                    q = k*TAU/self.px(48)
                    self._ring(buf,x,y,r,q)
            _ambient_disc(buf,W,H,x,y,r,shade(c,142))
            if i == -1:
                _ambient_disc(buf,W,H,x-.4,y-.45,max(1,r-1),0xFFBA56)
                _ambient_disc(buf,W,H,x-1,y-1,max(0,r-2),0xFFF2A8)
            else:
                direction = atan2(cy-y,cx-x)
                _ambient_disc(buf,W,H,x+cos(direction)*.65,y+sin(direction)*.65,max(0,r-1),c)
                if i == 2:
                    plot(buf,W,H,round(x+.5*sin(t)),round(y-.6),0x72B07A)
                if i == 4:
                    line_set(buf,W,H,x-r*.7,y,x+r*.6,y-.2,0x906D58)
            if i == 5:
                for k in range(self.px(25)):
                    self._ring(buf,x,y,r,k*TAU/self.px(48))
        return buf

    def _ring(self,buf,x,y,r,a):
        u,v = (r+3.6*self.S)*cos(a),(r*.51+self.S)*sin(a)
        X,Y = round(x+.90*u+.43*v),round(y-.43*u+.90*v)
        plot(buf,self.W,self.H,X,Y,0xA38362 if sin(a)>0 else 0x664D3E)


class Thunder(Scene):
    """Slate clouds roll over an ink-dark shore with distant lightning."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 68000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.grid = _FieldGrid(W,H,11_000) if self.gfx else None
        self.sw,self.sh = ((self.grid.sw,self.grid.sh) if self.grid
                           else _ambient_grid(W,H,2))
        self.idx = []
        self.tick = 0
        self.cloud = [(x/self.sw*16+y/self.sh*3, y/self.sh*26-x/self.sw*6,
                       x/self.sw*32+y/self.sh*13,exp(-((y/self.sh-.35)*2.12)**2))
                      for y in range(self.sh) for x in range(self.sw)]
        self.sky = _ambient_palette(((0,0x080B17),(.25,0x0B0F1C),(.63,0x222A42),(.83,0x3E4D6C),(1,0x7A8EA7)))
        self.sheet = _ambient_palette(((0,0x090B18),(.25,0x131329),(.63,0x373050),(.83,0x655578),(1,0x9886B9)))
        self.pals = [[mix(a,b,lv*29) for a,b in zip(self.sky,self.sheet)] for lv in range(9)]
        self.land = [int(H*(.776+.021*sin(7*x/W)+.009*cos(19*x/W))) for x in range(W)]
        self.events = [0.]
        for _ in range(37):
            self.events.append(self.events[-1]+rng.uniform(2.1,6.9))
        self.bolts = []
        self.event = None
        self.bloom = make_sprite(0x415C9C,max(3,round(H*.20)),7,1.65)

    def _split(self,rng,a,b,rough,depth):
        if not depth:
            return [a]
        x = (a[0]+b[0])*.5+rng.uniform(-rough,rough)
        y = (a[1]+b[1])*.5+rng.uniform(-rough*.23,rough*.23)
        c = x,y
        return self._split(rng,a,c,rough*.55,depth-1)+self._split(rng,c,b,rough*.55,depth-1)

    def _bolt(self):
        W,H = self.W,self.H
        x = W*(.20+.60*self.rng.random())
        a,b = (x,H*.14),(x+self.rng.uniform(-.22,.22)*W,H*.75)
        main = self._split(self.rng,a,b,H*.15,5)+[b]
        lines = [main]
        for k in (5,11,17,23):
            a = main[k]
            b = (a[0]+self.rng.choice((-1,1))*W*self.rng.uniform(.10,.22),
                 a[1]+self.rng.uniform(.12,.22)*H)
            lines.append(self._split(self.rng,a,b,H*.068,3)+[b])
        self.bolts = lines

    def frame(self,t,dt):
        W,H = self.W,self.H
        if self.tick%2 == 0 or not self.idx:
            p = t*.32
            self.idx = [int(20+v*(100+40*sin(a-p+.75*sin(b-p*.69))
                                   +28*cos(b-p*.74)+22*sin(c+p*.61)))
                        for a,b,c,v in self.cloud]
        self.tick ^= 1
        span = self.events[-1]
        phase = (t+2.0)%span
        k = next((i for i in range(len(self.events)-2,-1,-1) if self.events[i] <= phase),0)
        age = phase-self.events[k]
        event = int((t+2)/span)*(len(self.events)-1)+k
        sheet = event%3==2
        flash = (0.42 if sheet else .86)*_ambient_smooth(age/.092)*exp(-max(0.,age-.15)*6.8)
        peak = min(8,round(flash*10))
        pal = self.pals[peak] if sheet else self.sky
        idx = self.idx
        if peak:
            offset = (4 if sheet else 8)*peak
            idx = [min(255,z+offset) for z in idx]
        buf = self.grid.expand(idx, pal) if self.grid else up2(idx,self.sw,self.sh,W,H,pal)
        if not sheet and age < .71:
            if event != self.event:
                self._bolt()
                self.event = event
            pulse = .21*exp(-((age-.60)/.048)**2)
            power = max(6,round(233*max(flash,pulse)))
            x,y = self.bolts[0][8]
            if peak:
                stamp(buf,W,H,round(x),round(y),self.bloom[peak-1 if peak<8 else 6])
            leader = _ambient_smooth(age/.10)
            for j,branch in enumerate(self.bolts):
                color = shade(0xCFE3FF,power if j == 0 else power//2)
                glow = shade(0x708BC3,power//3)
                end = max(2,round(len(branch)*leader))
                for (x0,y0),(x1,y1) in zip(branch[:end-1],branch[1:end]):
                    if peak:
                        line_add(buf,W,H,x0+self.S,y0,x1+self.S,y1,glow)
                        if j == 0:
                            line_add(buf,W,H,x0-2*self.S,y0,x1-2*self.S,y1,shade(glow,105))
                    if self.gfx:
                        _gfx_line_set(buf,W,H,x0,y0,x1,y1,addp(0x202938,color))
                    else:
                        line_add(buf,W,H,x0,y0,x1,y1,color)
        rim = mix(0x131927,0x4A5673,int(190*flash))
        for x,y in enumerate(self.land):
            buf[y*W+x::W] = [0x070C17]*(H-y)
            buf[y*W+x] = rim
        x = int(W*.19)
        y = self.land[x]
        h = max(3,H*.17)
        ink = mix(0x070913,0x2D3148,int(180*flash))
        line_set(buf,W,H,x,y,x+.08*h,y-h,ink)
        for s in (-1,1):
            line_set(buf,W,H,x,y-h*.35,x+s*h*.36,y-h*.70,ink)
            line_set(buf,W,H,x+s*h*.26,y-h*.62,x+s*h*.28,y-h*.9,ink)
            line_set(buf,W,H,x+.02*h,y-h*.69,x+s*h*.20,y-h*.96,ink)
        x = int(W*.83)
        y = self.land[x]
        height = H*.14
        line_set(buf,W,H,x,y,x,y-height,ink)
        for n in range(3):
            a = t*.53+n*TAU/3
            line_set(buf,W,H,x,y-height,x+cos(a)*height*.52,y-height+sin(a)*height*.52,ink)
        return buf


class Kaleido(Scene):
    """Mirrored neon petals dissolve between six, eight and twelve wedges."""
    fps = 12
    mask = 0xF8F8F8

    def setup(self):
        W,H = self.W,self.H
        self.bg = [shade(0x1A0F39,int(44+151*exp(-6*((x/W-.5)**2+(y/H-.5)**2))))
                   for y in range(H) for x in range(W)]
        self.pal = cospal(128,(.55,.49,.56),(.37,.42,.35),(1,1,1),(.08,.35,.71))
        self.symmetry = (6,8,12)
        self.rotations = [[(cos(k*TAU/n),sin(k*TAU/n)) for k in range(n)] for n in self.symmetry]

    def frame(self,t,dt):
        W,H = self.W,self.H
        cx,cy,radius = W*.5,H*.5,min(W,H)*.475
        buf = self.bg[:]
        q = (t/45)%3
        phase = int(q)
        blend = _ambient_smooth((q%1-.87)/.13)
        layers = [(phase,1-blend)]
        if blend:
            layers.append(((phase+1)%3,blend))
        stroke = _gfx_line_add if self.gfx else line_add
        for mode,amount in layers:
            n = self.symmetry[mode]
            wedge = PI/n
            rings = []
            for j in range(3):
                pts = []
                for k in range(13):
                    p = k/12
                    a = wedge*(.04+.90*p)
                    r = radius*(.17+.245*j+.18*sin(p*PI)*(1+.28*sin(t*.61+j))
                                +.045*cos(t*.81+j+p*TAU))
                    pts.append((r*cos(a),r*sin(a)))
                rings.append(pts)
            for ca,sa in self.rotations[mode]:
                for sign in (-1,1):
                    for j,pts in enumerate(rings):
                        col = self.pal[(int(t*5)+33*j+mode*7)%128]
                        ink = shade(col,int(amount*(144-15*j)))
                        glow = shade(col,int(amount*44))
                        old = None
                        for k,(x,y) in enumerate(pts):
                            y *= sign
                            X,Y = cx+x*ca-y*sa,cy+x*sa+y*ca
                            if old is not None:
                                stroke(buf,W,H,*old,X,Y,ink)
                            old = X,Y
                            if k%3 == 1:
                                x0,y0 = round(X),round(Y)
                                plota(buf,W,H,x0,y0,ink)
                                for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                                    plota(buf,W,H,x0+round(dx*self.S),y0+round(dy*self.S),glow)
                        a = wedge*(.43+.36*sin(t*.76+j))
                        r = radius*(.28+.25*j+.07*sin(t*.36+j*1.8))
                        u,v = r*cos(a),sign*r*sin(a)
                        x,y = round(cx+u*ca-v*sa),round(cy+u*sa+v*ca)
                        plota(buf,W,H,x,y,shade(0xFFF0BF,int(amount*159)))
        return buf


class Fractal(Scene):
    """Smooth escape-time vistas paint in and slowly cycle through luminous palettes."""
    fps = 8
    mask = 0xF8F8F8
    gfx_pixels = 68500
    gfx_fps = 20

    def setup(self):
        W,H = self.W,self.H
        max_width,max_height = (280,225) if self.gfx else (140,100)
        self.step = max(1,math.ceil(W/max_width),math.ceil(H/max_height))
        self.sw,self.sh = _ambient_grid(W,H,self.step)
        self.views = ((-.743643887,.1318259042,.0095),(.005,0.,2.48),(-1.756,-.032,.078))
        hues = (((0,0x080B1E),(.22,0x173878),(.43,0x24A2AB),(.61,0xF6C377),(.81,0x953F7D),(1,0x080B1E)),
                ((0,0x130820),(.22,0x5D287A),(.43,0xB6599C),(.62,0xF7AC8C),(.80,0x453B99),(1,0x130820)),
                ((0,0x071218),(.22,0x275275),(.42,0x559877),(.64,0xD4AE5F),(.81,0x70485A),(1,0x071218)))
        self.palettes = []
        for hue in hues:
            pal = _ambient_palette(hue,128)
            self.palettes.append([pal[k:]+pal[:k]+[0x03040B] for k in range(128)])
        self.mode = None
        self.indices = [128]*(self.sw*self.sh)
        self.previews = []
        sample = 4
        for mode in range(len(self.views)):
            coarse = [[self._sample(mode,min(self.sw-1,x+sample//2),
                                          min(self.sh-1,y+sample//2))[0]
                       for x in range(0,self.sw,sample)] for y in range(0,self.sh,sample)]
            self.previews.append([coarse[y//sample][x//sample]
                                  for y in range(self.sh) for x in range(self.sw)])

    def _sample(self, mode, col, row):
        cx,cy,span = self.views[mode]
        step = span/self.sh
        a,b = cx+(col-self.sw*.5)*step,cy+(row-self.sh*.5)*step
        if mode == 1:
            x,y,a,b = a,b,-.8,.156
        else:
            x=y=0.
        n = 0
        xx,yy = x*x,y*y
        while n < 160 and xx+yy < 64:
            cross = x*y
            y = 2*(abs(cross) if mode == 2 else cross)+b
            x = xx-yy+a
            xx,yy = x*x,y*y
            n += 1
        if n == 160:
            return 128,n
        smooth = n+1-math.log2(math.log(sqrt(xx+yy)))
        return int(smooth*6.5)&127,n

    def _paint(self,mode):
        # Cap work on dense regions while filling in the coarse preview.
        budget = 9200
        for i in range(self.cursor,len(self.indices)):
            value,cost = self._sample(mode,i%self.sw,i//self.sw)
            self.indices[i] = value
            budget -= cost+4
            if budget <= 0:
                self.cursor = i+1
                return
        self.cursor = len(self.indices)

    def frame(self,t,dt):
        W,H = self.W,self.H
        cycle = int(t/207)
        local = t%207
        mode = cycle%len(self.views)
        if cycle != self.mode:
            self.mode = cycle
            self.cursor = 0
            self.indices[:] = self.previews[mode]
        if self.cursor < len(self.indices):
            self._paint(mode)
        pal = self.palettes[mode][int(t*2.4)%128]
        fade = min(_ambient_smooth(local/.8),_ambient_smooth((207-local)/5))
        if fade < 1:
            pal = [shade(c,int(fade*256)) for c in pal]
        if self.step == 1:
            return list(map(pal.__getitem__,self.indices))
        return _ambient_expand(self.indices,W,H,self.sw,self.step,pal)


class Cyclic(Scene):
    """A cyclic cellular automaton grows rotating colonies of colored wavefronts."""
    fps = 12
    mask = 0xF0F0F0
    gfx_fps = 12

    def setup(self):
        W,H = self.W,self.H
        self.step = self.px(2 if self.logical_area <= 16000 else 3)
        self.sw,self.sh = _ambient_grid(W,H,self.step)
        self.grid_x = self.grid_y = None
        if self.gfx_reference:
            rw,rh = self.gfx_reference
            nominal = 2 if self.logical_area <= 16000 else 3
            step = max(1, round(nominal*self.S/self.detail_scale))
            self.sw,self.sh = _ambient_grid(rw,rh,step)
            self.grid_x = itemgetter(*(x*self.sw//W for x in range(W)))
            self.grid_y = [y*self.sh//H for y in range(H)]
        self.ramps = {}
        for k in range(12,15):
            pal = _ambient_palette(((0,0x1C173D),(.19,0x334D79),(.40,0x27847E),(.59,0x86934F),
                                    (.74,0xCB9454),(.88,0xA65870),(1,0x593366)),k)
            self.ramps[k] = [[shade(c,32+i*28) for c in pal] for i in range(9)]
        self.epoch = None
        self.next_seed = None
        self.noise = None
        self._seed(0)

    def _seed(self,t):
        rng = self.rng
        self.states = rng.randrange(12,15)
        self.successor = list(range(1,self.states))+[0]
        sw,sh,K = self.sw,self.sh,self.states
        centers = [(sw*rng.uniform(a-.035,a+.035),sh*rng.uniform(b-.07,b+.07),rng.choice((-1,1)),rng.randrange(K))
                   for a,b in ((.16,.28),(.43,.68),(.70,.26),(.88,.72))]
        self.cells = []
        self.cores = []
        self.tick = 0
        radius = max(2.2,min(4.3,min(sw,sh)*.083))
        for y in range(sh):
            for x in range(sw):
                px,py,hand,phase = min(centers,key=lambda c:(x-c[0])**2+(y-c[1])**2)
                dx,dy = x-px,y-py
                distance = hypot(dx,dy)
                wave = math.floor(-.43*distance+hand*K/TAU*atan2(dy,dx)+phase)
                if distance < radius:
                    self.cores.append((y*sw+x,wave%K))
                if rng.random()<.045:
                    wave = rng.randrange(K)
                self.cells.append(wave%K)
        self.noise = int(t/8)

    def frame(self,t,dt):
        W,H,sw,sh = self.W,self.H,self.sw,self.sh
        if self.epoch is None:
            self.epoch = t-4
            self.next_seed = t+116
        if self.next_seed <= t:
            self._seed(t)
            self.epoch = t
            self.next_seed = t+120
        interval = int(t/8)
        field = self.cells
        if interval != self.noise:
            self.noise = interval
            cx,cy = self.rng.randrange(sw),self.rng.randrange(sh)
            r = max(1,min(3,sw//17))
            for y in range(-r,r+1):
                for x in range(-r,r+1):
                    if x*x+y*y <= r*r:
                        field[((cy+y)%sh)*sw+(cx+x)%sw] = self.rng.randrange(self.states)
        rows = [field[i:i+sw] for i in range(0,len(field),sw)]
        left = [row[-1:]+row[:-1] for row in rows]
        right = [row[1:]+row[:1] for row in rows]
        out = []
        get = self.successor.__getitem__
        for y,row in enumerate(rows):
            a,b = y-1,(y+1)%sh
            neigh = zip(row,map(get,row),left[a],rows[a],right[a],left[y],right[y],left[b],rows[b],right[b])
            out.extend(n if ((n==a)+(n==b)+(n==c)+(n==d)+(n==e)+(n==f)+(n==g)+(n==h))>=2 else s
                       for s,n,a,b,c,d,e,f,g,h in neigh)
        if self.tick%48 == 0 and t-self.epoch > 20:
            activity = sum(a!=b for a,b in zip(out,field))
            if activity < max(2,len(field)//160):
                self.next_seed = min(self.next_seed,t+1.5)
        # Small rotating nucleation cores keep wavefronts circulating between reseeds.
        phase = self.tick//3
        for i,state in self.cores:
            out[i] = (state+phase)%self.states
        self.tick += 1
        self.cells = out
        fade = min(_ambient_smooth((t-self.epoch)/1.5),_ambient_smooth((self.next_seed-t)/1.5))
        palette = self.ramps[self.states][round(fade*8)]
        if self.grid_x:
            rows = [self.grid_x(list(map(palette.__getitem__, out[i:i+sw])))
                    for i in range(0,len(out),sw)]
            expanded = []
            for y in self.grid_y:
                expanded.extend(rows[y])
            return expanded
        return _ambient_expand(out,W,H,sw,self.step,palette)


class StainedGlass(Scene):
    """Sunlight crosses jewel-toned panes set into a pointed cathedral window."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 68500

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        cx = (W-1)*.5
        half = min(W*.39,H*.43)
        spring = H*.39
        height = H*.325
        bottom = H*.91
        colors = (0xB3123A,0x1B3FA8,0x0F8A4F,0xE6A21A,0x6A2BB0,0x0F8F9F,0xD6457A)
        nx,ny = 8,9
        seeds = [[(i+.5+rng.uniform(-.31,.31),j+.5+rng.uniform(-.31,.31),
                   rng.choice(colors),rng.random()*TAU) for i in range(nx)] for j in range(ny)]
        self.seeds = []
        for row in seeds:
            for a,b,c,p in row:
                c = mix(c,0xFFF0C0,18)
                self.seeds.append(((a/nx-.5)*2,b/ny,p,
                                   [shade(c,int(30+j*9.6)) for j in range(26)]))
        plate = [0]*(W*H)
        ids = [-1]*(W*H)
        columns = []
        if self.gfx:
            for x in range(W):
                u = abs(x-cx)/half
                arch = spring-height*sqrt(max(0,1-((u+.56)/1.56)**2))/.932
                fx = (x-cx+half)/(2*half)*nx
                # Jitter is bounded to .31 around each cell center. A seed two
                # cells away cannot beat the seed in the current cell.
                ix = int(fx)
                candidates = [tuple(((fx-row[i][0])**2,row[i][1],j*nx+i)
                                    for i in range(max(0,ix-1),min(nx,ix+2)))
                              for j,row in enumerate(seeds)]
                columns.append(((1-u)*half,arch,fx,candidates))
        for y in range(H):
            for x in range(W):
                if columns:
                    wall,arch,fx,candidates = columns[x]
                    d = min(wall,y-arch,bottom-y)
                else:
                    u = abs(x-cx)/half
                    arch = spring-height*sqrt(max(0,1-((u+.56)/1.56)**2))/.932
                    d = min((1-u)*half,y-arch,bottom-y)
                k = y*W+x
                grain = rng.randrange(8)
                if d < 1:
                    stone = 0x14121A if (y//max(3,H//11))%2 else 0x17141D
                    if -.065*H < d < 1:
                        stone = 0x43364B if d > -.026*H else 0x262231
                    elif x in (0,W-1) or y%max(4,H//11)==0:
                        stone = 0x0F0D16
                    plate[k] = addp(stone,shade(0x181218,grain*5))
                    continue
                fx = (x-cx+half)/(2*half)*nx
                fy = (y-(spring-height))/(bottom-(spring-height))*ny
                best,jid = 10.,0
                if columns and 0 <= fx < nx and 0 <= fy < ny:
                    for j in range(max(0,int(fy)-1),min(ny,int(fy)+2)):
                        for dx2,b,index in candidates[j]:
                            score = dx2+(fy-b)**2
                            if score < best:
                                best,jid = score,index
                else:
                    for j in range(max(0,int(fy)-2),min(ny,int(fy)+3)):
                        for i in range(max(0,int(fx)-2),min(nx,int(fx)+3)):
                            a,b,_,_ = seeds[j][i]
                            score = (fx-a)**2+(fy-b)**2
                            if score < best:
                                best,jid = score,j*nx+i
                ids[k] = jid
        self.bg = plate
        self.glass = []
        lead_width = self.px(1)
        for i,j in enumerate(ids):
            if j < 0:
                continue
            y,x = divmod(i,W)
            # Mullion, rose medallion and a highlighted leading edge share the lead treatment.
            ring = hypot((x-cx),(y-H*.31)*1.06)
            rose = abs(ring-H*.095)<.74*self.S or abs(ring-H*.047)<.51*self.S
            lead = abs(x-cx)<max(.6,H*.010) or rose
            if not lead and (j != ids[i-lead_width] or j != ids[i-lead_width*W]):
                plate[i] = 0x0A0A10
            elif lead:
                plate[i] = 0x17131E if x<cx else 0x0A0A10
            else:
                raw = int(1.3*sin((x*1.52+y*.32)/self.S)+1.1*cos((y*1.82-x*.21)/self.S))+rng.randrange(-1,2)
                etch = -2 if j != ids[i+1] or j != ids[i+W] else 0
                self.glass.append((i,j,max(-3,min(3,raw-etch))))

    def frame(self,t,dt):
        a = t*TAU/60
        dx,dy = cos(a*.27+.68),sin(a*.27+.68)
        ray = 1.09*sin(a*.5+.44)
        cols = []
        for x,y,p,ramp in self.seeds:
            v = x*dx+(y-.51)*1.32*dy-ray
            light = exp(-(v/.39)**2)
            lv = int(6+14*light+1.8*sin(t*.71+p))
            cols.append(ramp[lv-3:lv+4])
        buf = self.bg[:]
        for i,j,texture in self.glass:
            buf[i] = cols[j][texture+3]
        return buf


class Circuit(Scene):
    """Data pulses thread quiet PCB traces and trigger activity at chip pins."""
    fps = 15
    mask = 0xF8F8F8

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        board = [0x050B15]*(W*H)
        for y in range(self.px(2),H,self.px(4)):
            for x in range(self.px(2),W,self.px(4)):
                board[y*W+x] = 0x0B1624
        for _ in range(int(self.logical_area//100)):
            board[rng.randrange(W*H)] = 0x101C2B
        hw,hh = max(2,min(self.px(12),W//11)),max(2,min(self.px(8),H//10))
        centers = [(round(W*a),round(H*b)) for a,b in ((.27,.26),(.72,.26),(.27,.69),(.72,.69))]
        blocked = set()
        self.chips = []
        for x,y in centers:
            left,right,top,bottom = x-hw,x+hw,y-hh,y+hh
            edge = []
            for yy in range(top,bottom+1):
                for xx in range(left,right+1):
                    i = yy*W+xx
                    blocked.add(i)
                    board[i] = 0x0C1424
                    if xx in (left,right) or yy in (top,bottom):
                        edge.append(i)
                        board[i] = 0x263B55
            _ambient_disc(board,W,H,left+self.px(2),top+self.px(2),self.px(1),0x445266)
            for k in range(-hw+1,hw,self.px(2)):
                plot(board,W,H,x+k,top-1,0x454655)
                plot(board,W,H,x+k,bottom+1,0x454655)
            for k in range(-hh+1,hh,self.px(2)):
                plot(board,W,H,left-1,y+k,0x454655)
                plot(board,W,H,right+1,y+k,0x454655)
            self.chips.append((edge,[]))
        self.routes = []
        self.heads = []
        self.flashes = [0.]*len(centers)
        self.bg = board
        occupied = set(blocked)

        def add_route(points,a,b):
            pixels = []
            for (x,y),(X,Y) in zip(points,points[1:]):
                span = max(abs(X-x),abs(Y-y))
                for k in range(span):
                    xx,yy = round(x+(X-x)*k/span),round(y+(Y-y)*k/span)
                    if not (0 <= xx < W and 0 <= yy < H):
                        return False
                    pixels.append(yy*W+xx)
            x,y = points[-1]
            if not (0 <= x < W and 0 <= y < H):
                return False
            pixels.append(y*W+x)
            if len(pixels) < 4 or any(i in occupied for i in pixels):
                return False
            occupied.update(pixels)
            k = len(self.routes)
            c = rng.choices((0x7DFCFF,0xFF4FD8,0xFFD04A),(8,2,2))[0]
            ramp = [shade(c,int(218*exp(-d/(4.6*self.S)))) for d in range(self.px(14))]
            self.routes.append((pixels,a,b,ramp))
            for chip in (a,b):
                if chip >= 0:
                    self.chips[chip][1].append(k)
            for i in pixels:
                board[i] = 0x0E3B4A
            for i in (pixels[0],pixels[-1]):
                board[i] = 0x407177
            return True

        pins_y = range(-min(self.px(5),hh-1),min(self.px(6),hh),self.px(2))
        pins_x = range(-min(self.px(7),hw-1),min(self.px(8),hw),self.px(2))
        for a,b in ((0,1),(2,3)):
            x,y = centers[a]
            X,Y = centers[b]
            for k in pins_y:
                sign = 1 if k >= 0 else -1
                bend = min(abs(k)//2+1,max(1,(X-x-2*hw)//5))
                x0,x1 = x+hw+1,X-hw-1
                if x1-x0 >= 2*bend+1:
                    add_route(((x0,y+k),(x0+bend,y+k+sign*bend),
                               (x1-bend,Y+k+sign*bend),(x1,Y+k)),a,b)
        for a,b in ((0,2),(1,3)):
            x,y = centers[a]
            X,Y = centers[b]
            for k in pins_x:
                sign = 1 if k>=0 else -1
                bend = min(abs(k)//2+1,max(1,(Y-y-2*hh)//5))
                y0,y1 = y+hh+1,Y-hh-1
                if y1-y0 >= 2*bend+1:
                    add_route(((x+k,y0),(x+k+sign*bend,y0+bend),
                               (X+k+sign*bend,y1-bend),(X+k,y1)),a,b)
        outward = []
        for i,(x,y) in enumerate(centers):
            nx = -1 if i%2==0 else 1
            ny = -1 if i<2 else 1
            outward.extend((i,x+nx*(hw+1),y+k,0 if nx>0 else 4) for k in pins_y)
            outward.extend((i,x+k,y+ny*(hh+1),2 if ny>0 else 6) for k in pins_x)
        rng.shuffle(outward)
        compass = ((1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1))
        target = min(55,max(26,int(self.logical_area//230)))
        for chip,x,y,d in outward:
            if len(self.routes) >= target:
                break
            for _ in range(5):
                points = [(x,y)]
                X,Y = x,y
                direction = d
                for k in range(rng.randint(2,7)):
                    dx,dy = compass[direction]
                    X,Y = X+dx*self.px(3),Y+dy*self.px(3)
                    if not (1 <= X < W-1 and 1 <= Y < H-1):
                        break
                    points.append((X,Y))
                    if rng.random() < .28:
                        direction = (direction+rng.choice((-2,-1,1,2)))%8
                if len(points)>1 and add_route(points,chip,-1):
                    break
        self.scan = sorted((i%W+i//W,i) for pixels,_,_,_ in self.routes for i in pixels)
        self.next_pulse = None
        for k,route in enumerate(self.routes):
            if k%3==0:
                self.heads.append([k,rng.uniform(0,len(route[0])-1),rng.uniform(22,54)*self.S])

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        rng = self.rng
        if self.routes and (self.next_pulse is None or t>=self.next_pulse):
            k = rng.randrange(len(self.routes))
            self.heads.append([k,0.,rng.uniform(21,57)*self.S])
            self.next_pulse = t+rng.uniform(.08,.27)
        age = (t+9)%40
        if age < 2.5:
            x = (W+H+22)*age/2.5-10
            for diag,i in self.scan:
                if abs(diag-x)<9:
                    buf[i] = addp(buf[i],shade(0x185268,int(91*(1-abs(diag-x)/9))))
        heads = []
        arrivals = []
        for k,s,v in self.heads:
            pixels,a,b,ramp = self.routes[k]
            s += dt*v
            j = int(s)
            if s < 0 or j>=len(pixels):
                chip = b if v > 0 else a
                if chip >= 0:
                    arrivals.append((k,chip))
                continue
            heads.append([k,s,v])
            direction = 1 if v > 0 else -1
            tail = j+1 if v > 0 else len(pixels)-j
            for d,c in enumerate(ramp[:tail]):
                i = pixels[j-d*direction]
                buf[i] = addp(buf[i],c)
        for k,b in arrivals:
            self.flashes[b] = 1.
            choices = self.chips[b][1]
            if len(choices)>1 and len(heads)<76 and rng.random()<.62:
                q = rng.choice(choices)
                if q != k:
                    pixels,a,_b,_ = self.routes[q]
                    direction = 1 if a==b else -1
                    heads.append([q,0. if direction>0 else len(pixels)-1.,direction*rng.uniform(20,55)*self.S])
        self.heads = heads
        for j,lv in enumerate(self.flashes):
            if lv > .015:
                self.flashes[j] = lv*exp(-dt*4)
                c = shade(0x4CB8C8,int(lv*170))
                for i in self.chips[j][0]:
                    buf[i] = addp(buf[i],c)
        return buf


class Silk(Scene):
    """Long-lived strands of champagne, rose and teal flow into cool luminous silk."""
    fps = 9
    mask = 0xF8F8F8
    gfx_pixels = 65000
    gfx_fps = 22

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.ramps = []
        dark = 0x0A0710
        for colors in ((0xC88A3C,0xDB4E81,0x299E93),(0x7367D7,0x3979D9,0x94BCD1)):
            bank = []
            for ink in colors:
                pal = _ambient_palette(((0,dark),(.18,mix(dark,ink,46)),(.68,ink),
                                        (.85,mix(ink,0xFFE7CC,81)),(1,0xFFEAD9)),16)
                bank.extend(pal[k//4] for k in range(64))
            self.ramps.append(bank+[dark]*64)
        self.decays = bytes((i&192)|max(0,(i&63)-3) for i in range(256))
        self.state = bytearray(W*H)
        self.tick = 0
        n = max(100,min(760,int(self.logical_area//15)))
        if self.gfx:
            n = min(1150,int(n*sqrt(self.S)))
        self.particles = [self._new(rng.uniform(0,7)) for _ in range(n)]
        self.speed = 25*max(.4,_ambient_scale(W,H,self.S))

    def _new(self,age):
        rng = self.rng
        x,y = rng.random(),rng.random()
        ink = (min(2,int(x*3)) if rng.random()<.8 else rng.randrange(3))*64
        return [x*self.W,y*self.H,age,ink,rng.uniform(.78,1.22)]

    def frame(self,t,dt):
        W,H = self.W,self.H
        cadence = 5 if self.gfx else 2
        if self.tick == 0:
            self.state = self.state.translate(self.decays)
        self.tick = (self.tick+1)%cadence
        buf = self.state
        a,b,c = (t*.11)%TAU,(-t*.07)%TAU,(t*.05)%TAU
        step = self.speed*dt
        scale = self.S
        head, tail = (16,9) if self.gfx else (23,14)
        for j,pt in enumerate(self.particles):
            x,y,age,ink,speed = pt
            theta = 2.3*sin(.035*x/scale+a)+2.1*sin(.05*y/scale+b)+.86*sin(.02*(x+y)/scale+c)
            nx,ny = x+step*speed*cos(theta),y+step*speed*sin(theta)
            if age <= 0 or not (0 <= nx < W and 0 <= ny < H):
                self.particles[j] = self._new(self.rng.uniform(3,8))
                continue
            pt[0],pt[1],pt[2] = nx,ny,age-dt
            i = int(ny)*W+int(nx)
            level = buf[i]&63
            buf[i] = ink|min(63,level+head)
            mid = int((y+ny)*.5)*W+int((x+nx)*.5)
            if mid!=i:
                buf[mid] = ink|min(63,(buf[mid]&63)+tail)
        shift = (t/90)%2
        src,dst = self.ramps[int(shift)],self.ramps[1-int(shift)]
        blend = _ambient_smooth((shift%1-.86)/.14)
        pal = src if blend == 0 else [mix(x,y,int(256*blend)) for x,y in zip(src,dst)]
        return list(map(pal.__getitem__,buf))


class Filings(Scene):
    """Iron filings follow an evolving magnetic field and its close-orbiting dipole."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 62500

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [shade(0x242738,rng.randrange(41,80)) for _ in range(W*H)]
        self.spacing = max(3,math.ceil(sqrt(W*H/800)),round(5*_ambient_scale(W,H,self.S)))
        gap = self.spacing
        self.lattice = [(x+(gap//2 if j%2 else 0),y)
                        for j,y in enumerate(range(1,H,gap)) for x in range(1,W-gap//2,gap)]
        self.angles = [0.]*len(self.lattice)
        self.ready = False
        self.pal = _ambient_palette(((0,0x202B46),(.34,0x506785),(.72,0x9FB4D6),(1,0xE0F6F5)),64)
        self.halos = [make_sprite(c,max(3,round(min(W,H)*.12)),6,2.1) for c in (0xFF8A3D,0x3D8BFF)]

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        angle = t*.24
        age = (t%60)
        close = _ambient_smooth((age-43)/4)*(1-_ambient_smooth((age-55)/5))
        poles = []
        for j in range(4):
            x = W*(.5+( .23 if j<2 else .33)*cos(t*(.13+.018*j)+j*1.87))
            y = H*(.5+(.23 if j<2 else .33)*sin(t*(.15+.021*j)+j*1.79))
            if j<2:
                a = angle+j*PI
                x = x*(1-close)+(W*.50+min(W,H)*.115*cos(a))*close
                y = y*(1-close)+(H*.48+min(W,H)*.115*sin(a))*close
            poles.append((x,y,1 if j%2==0 else -1))
        inertia = min(1,8*dt) if self.ready else 1
        self.ready = True
        length = self.spacing*.39
        normal = min(W,H)**2
        eps = (min(W,H)*.048)**2
        stroke = _gfx_line_set if self.gfx else line_set
        for i,(x,y) in enumerate(self.lattice):
            u=v=0.
            for px,py,q in poles:
                dx,dy = x-px,y-py
                d = dx*dx+dy*dy+eps
                force = q/(d*sqrt(d))
                u += dx*force
                v += dy*force
            aim = atan2(v,u)
            old = self.angles[i]
            # Filings have no arrowhead, so the shortest rotation is periodic over pi.
            a = old+((aim-old+PI/2)%PI-PI/2)*inertia
            self.angles[i] = a%PI
            power = min(1,math.log1p(normal*hypot(u,v)*.32)/4.1)
            r = length*(.47+.58*power)
            dx,dy = r*cos(a),r*sin(a)
            stroke(buf,W,H,x-dx,y-dy,x+dx,y+dy,self.pal[int(63*power)])
        for j,(x,y,q) in enumerate(poles):
            xi,yi = round(x),round(y)
            stamp(buf,W,H,xi,yi,self.halos[j%2][3])
            plota(buf,W,H,xi,yi,0xFFA36A if q>0 else 0x7EB7FF)
        return buf


class StarTrails(Scene):
    """A turning sky builds long exposures over pine silhouettes until dawn."""
    fps = 12
    mask = 0xF8F8F8
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.cx,self.cy = W*.31,H*.29
        self.night = _ambient_palette(((0,0x070C22),(.49,0x101738),(1,0x29334F)),H)
        self.dawn = _ambient_palette(((0,0x163557),(.40,0x276779),(.70,0x887987),(1,0xF9A57E)),H)
        self.bg = [c for c in self.night for _ in range(W)]
        self.ridge = [int(H*(.794+.049*sin(x/W*8)+.027*cos(16*x/W)+.032*sin(x/W*23))) for x in range(W)]
        for x in range(W):
            h = max(2,round(H*rng.uniform(.021,.088)))
            if x%self.px(2)==0 and rng.random()<.70:
                y = self.ridge[x]+1
                for dx in range(-h//3,h//3+1):
                    X = x+dx
                    if 0 <= X < W:
                        self.ridge[X] = min(self.ridge[X],y-h+abs(dx)*3)
        for x,y in enumerate(self.ridge):
            self.bg[y*W+x::W] = [0x05070D]*(H-y)
        x = int(W*.80)
        y = min(H-3,max(self.ridge[max(0,x-2):x+4])+1)
        line_set(self.bg,W,H,x-2,y+1,x,y-1,0x10111A)
        line_set(self.bg,W,H,x,y-1,x+3,y+1,0x10111A)
        plot(self.bg,W,H,x,y+1,0xD29657)
        self.cabin = (x,y+1)
        self.sky = [(x,y) for y in range(H) for x in range(W) if y<self.ridge[x]]
        self.stars = []
        for i in range(max(105,min(775 if self.gfx else 670,int(self.logical_area//17*sqrt(self.S))))):
            x = rng.uniform(-.32,1.25)*W-self.cx
            y = rng.uniform(-.59,1.09)*H-self.cy
            color = rng.choice((0xFFD9B0,0xB8D0FF,0xB8D0FF,0xEED2BB,0xD49987))
            bright = rng.randrange(22,130) if i%8 else rng.randrange(132,218)
            self.stars.append((x,y,shade(color,bright),i%19==0))
        self.dust = [(rng.uniform(-.64,.95)*W,rng.gauss(0,.068)*H, rng.randrange(20,78))
                     for _ in range(max(70,min(440,int(self.logical_area//25))))]
        self.pole = make_sprite(0xB8D0FF,max(2,round(H*.043)),6,2.2)[-1]
        self.cycle = None
        self.last = []
        self.canvas = self.bg[:]
        self.exposure = [0]*(W*H)
        self.meteors = [12.7]
        for _ in range(13):
            self.meteors.append(self.meteors[-1]+rng.uniform(15,39))

    def _record(self,x,y,c):
        if 0 <= x < self.W and 0 <= y < self.ridge[x]:
            i = y*self.W+x
            old = self.exposure[i]
            if old < c:
                self.exposure[i] = c
                self.canvas[i] = addp(self.bg[i],c)

    def frame(self,t,dt):
        W,H = self.W,self.H
        local,cycle = t%360,int(t/360)
        if cycle != self.cycle:
            self.cycle = cycle
            self.last = []
            self.canvas[:] = self.bg
            self.exposure[:] = [0]*(W*H)
        phase = local*TAU/300
        ca,sa = cos(phase),sin(phase)
        cx,cy = self.cx,self.cy
        if local<244:
            last = self.last
            now = []
            for j,(x,y,c,bright) in enumerate(self.stars):
                X,Y = round(cx+x*ca-y*sa),round(cy+x*sa+y*ca)
                now.append((X,Y))
                if last and (X,Y)==last[j]:
                    continue
                self._record(X,Y,c)
                if bright:
                    self._record(X+self.px(1),Y,shade(c,53))
                if last:
                    a,b = last[j]
                    d = max(abs(a-X),abs(b-Y))
                    if 1 < d <= 4:
                        for k in range(1,d):
                            self._record(round(a+(X-a)*k/d),round(b+(Y-b)*k/d),c)
            self.last = now
        day = _ambient_smooth((local-244)/41)*(1-_ambient_smooth((local-308)/32))
        if local >= 244:
            buf = self.bg[:]
            trails = int(256*(1-_ambient_smooth((local-244)/42)))
            rows = [mix(n,d,int(256*day)) for n,d in zip(self.night,self.dawn)]
            # Skip the foreground so both the tree line and cabin stay sharp through dawn.
            for x,y in self.sky:
                i = y*W+x
                c = self.exposure[i]
                buf[i] = addp(rows[y],shade(c,trails)) if c and trails else rows[y]
        else:
            buf = self.canvas[:]
        if day<.9 and local<306:
            a = phase+.60
            ca,sa = cos(a),sin(a)
            for x,y,l in self.dust:
                X,Y = round(cx+x*ca-y*sa),round(cy+x*sa+y*ca)
                if 0 <= X < W and 0 <= Y < self.ridge[X]:
                    plota(buf,W,H,X,Y,shade(0x4F6186,int(l*(1-day))))
            stamp(buf,W,H,round(cx),round(cy),self.pole)
            meteor = next((i for i,v in enumerate(self.meteors) if 0<=local-v<.95),None)
            if meteor is not None:
                a = local-self.meteors[meteor]
                x,y = W*(.78-.51*a),H*(.11+.31*a+(meteor%4)*.058)
                for k in range(9):
                    X,Y = round(x+k*1.12*self.S),round(y-k*.51*self.S)
                    if 0 <= X < W and 0 <= Y < self.ridge[X]:
                        plota(buf,W,H,X,Y,shade(0xD7FFDD,(9-k)*25))
            satellite = (local+15)%121
            if satellite<32:
                x = int(W*satellite/32)
                y = int(H*(.38+.19*satellite/32))
                if y<self.ridge[x]:
                    plota(buf,W,H,x,y,0x82988F)
        return buf


class Lighthouse(Scene):
    """A quiet headland, watched by a single slow amber beacon."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.horizon = horizon = round(.62*H)
        self.tower_x = x = round(.72*(W-1))
        foot = min(H-1, horizon+max(1,round(.025*H)))
        height = max(2, int(.14*H)) if self.gfx else min(16,foot+1)
        self.tower_height = height
        self.lens_y = top = foot-height+1
        half = max(1, round(.18*height))
        self.bg = vgrad(W,H,((0,(5,8,15)),(.62,(13,26,43)),(.63,(11,23,38)),
                             (1,(5,11,21))))
        self.fog = []
        self.fog_at = [0.]*H
        mist = 0x2A3F55
        for y in range(max(0, top-round(.12*H)), horizon):
            # Two partially separated height profiles scroll at different rates.
            upper = .28*exp(-((y/H-.502)/.051)**2)
            lower = .58*exp(-((y/H-.602)/.027)**2)
            if upper+lower < .012:
                continue
            harmonic = .52+.25*sin(y/H*39)
            shape = [.60+.22*sin(2*TAU*i/W+harmonic)+.12*cos(3*TAU*i/W-9*y/H)
                     for i in range(W)]
            profile = upper+lower
            self.fog_at[y] = profile
            base = self.bg[y*W]
            rows = []
            palette = [mix(base,mist,n) for n in range(115)]
            for level in range(5):
                row = [palette[min(114,round(152*profile*v*(.53+.155*level)))]
                       for v in shape]
                rows.append(row+row)
            self.fog.append((y, .011*W if upper>lower else -.021*W, rows))
        self.headland = []
        for offset in range(-3*half,4*half+1):
            px = x+offset
            if 0<=px<W:
                land_y = foot+round(abs(offset)*.40+sin(offset*.39)*height*.065)
                for y in range(max(horizon,land_y),min(H,land_y+max(2,round(H*.022)))):
                    self.headland.append((y*W+px,0x080E18))
        self.tower = []
        self.glass = []
        for y in range(top,foot+1):
            k = y-top
            if k==0:
                width,ink = max(1,half-1),0x192330
            elif k<=max(1,round(.17*height)):
                width,ink = max(1,half-1),0x758089
            elif k==max(2,round(.18*height)+1):
                width,ink = half+max(1,round(height*.05)),0x151E2B
            else:
                width,ink = max(1,round(half*(.49+.55*k/height))),0x4B5864
            for px in range(max(0,x-width),min(W,x+width+1)):
                color = ink if px<=x else shade(ink,173)
                self.tower.append((y*W+px,color))
            if 0<k<=max(1,round(.17*height)):
                self.glass.append(y*W+x)
        self.lens_y = top+max(1,round(.1*height))
        self.glow = make_sprite(0xFFD08A,max(2,round(.03*H)),5,2.45)
        self.moon = make_sprite(0x657683,max(2,round(.032*H)),5,2.1)
        radius = max(2,round(.016*H))
        self.moon_rim = [(dx,dy) for dy in range(-radius,radius+1)
                         for dx in range(-radius,radius+1)
                         if hypot(dx,dy)<=radius and hypot(dx+radius*.62,dy-radius*.14)>radius*.93]
        self.waves = [(rng.random(), rng.uniform(.01,.95), rng.random()*TAU,
                       rng.uniform(.018,.088)) for _ in range(49)]
        self.beam_colors = [shade(0xFFD08A,l) for l in range(85)]

    def _beam(self, buf, t, density):
        W, H = self.W, self.H
        a = TAU*t/40+.69
        reach = max(2.,W*.62*abs(cos(a)))
        direction = 1 if cos(a)>0 else -1
        x0, y0 = self.tower_x,self.lens_y
        end = min(int(reach),W-1-x0 if direction>0 else x0)
        bend = .12*H*sin(a+.38)/reach
        spread = .081
        start_width = max(1.,.009*H)
        for y, _, _ in self.fog:
            rise = y-y0
            lo,hi = 1.,float(end)
            # Intersect this scanline with the wedge's two angular boundaries.
            for delta, slope in ((rise-start_width,bend+spread),
                                 (-rise-start_width,spread-bend)):
                if slope>0:
                    lo = max(lo,delta/slope)
                elif slope<0:
                    hi = min(hi,delta/slope)
                elif delta>0:
                    hi = 0.
            if hi<lo:
                continue
            strength = min(84.,203*self.fog_at[y]*density)
            base = y*W+x0
            for distance in range(math.ceil(lo),int(hi)+1):
                aperture = start_width+spread*distance
                edge = 1-abs(rise-bend*distance)/aperture
                along = distance/reach
                falloff = (1-along)*(1+.48*along)
                level = int(strength*min(1.,max(0.,edge*2.3))*falloff)
                if level:
                    i = base+direction*distance
                    buf[i] = addp(buf[i],self.beam_colors[level])
        return x0+direction*reach, abs(cos(a))*(.35+.65*max(0.,sin(a+.38)))

    def frame(self,t,dt):
        W,H = self.W,self.H
        horizon = self.horizon
        buf = self.bg[:]
        density = .59+.30*sin(t*TAU/187-.75)+.09*sin(t*TAU/79)
        level = max(0,min(4,round(4*density)))
        for y,speed,rows in self.fog:
            offset = int(t*speed)%W
            buf[y*W:(y+1)*W] = rows[level][offset:offset+W]
        moon = _ambient_smooth((t-420)/104)
        if moon:
            mx,my = round(W*.31),round(H*.23)
            stamp(buf,W,H,mx,my,self.moon[min(4,int(moon*5))])
            ink = shade(0x95A6BB,int(64*moon))
            for dx,dy in self.moon_rim:
                plota(buf,W,H,mx+dx,my+dy,ink)
        tip, light = self._beam(buf,t,density)
        for u,depth,phase,span in self.waves:
            x = round(W*((u+t*.009*(.25+depth))%1))
            y = min(H-1,horizon+round((H-1-horizon)*depth))
            w = max(2,round(W*span*(.31+.78*depth)))
            ripple = .54+.43*sin(t*(.61+.53*depth)+phase)
            sweep = max(0.,1-abs(x-(self.tower_x*.34+tip*.66))/(W*.21))
            gain = 64*light*sweep*(1-depth)**2
            color = shade(0x4C6578,int((36+36*depth)*ripple))
            if gain>2:
                color = addp(color,shade(0xBA9A6B,int(gain*ripple)))
            left,right = max(0,x-w//2),min(W,x+w//2+1)
            if left<right:
                i = y*W+left
                buf[i:i+right-left] = map(addp,buf[i:i+right-left],[color]*(right-left))
        for i,c in self.headland:
            buf[i] = c
        for i,c in self.tower:
            buf[i] = c
        pulse = .82+.15*sin(t*TAU/40+.3)
        stamp(buf,W,H,self.tower_x,self.lens_y,self.glow[min(4,round(4*pulse))])
        for i in self.glass:
            buf[i] = shade(0xFFD08A,int(235*pulse))
        crossing = (t-320)/84
        if 0<crossing<1:
            x = round(W*(.085+.53*crossing))
            y = min(H-1,horizon+max(1,round(H*.035)))
            visibility = _ambient_smooth(crossing/.13)*_ambient_smooth((1-crossing)/.13)
            size = max(2,round(W*.005))
            fill_row(buf,W,y,x,min(W,x+size),shade(0xFFD08A,int(174*visibility)))
        return buf


class Streetlamp(Scene):
    """An old amber streetlamp over fog and rain-dark cobblestones."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.x = lx = round(.35*(W-1))
        self.y = ly = round(.276*H)
        self.floor = floor = round(.73*H)
        self.bg = []
        self.fog = []
        r = max(2,round(H*.115))
        self.glow = make_sprite(0xFFC66E,r,8,2.5)
        self.remote = make_sprite(0xCEAE81,max(2,round(H*.037)),6,2.3)
        cx = lx+H*.018
        for y in range(H):
            v = y/H
            street = max(0.,(y-floor)/max(1,H-floor))
            street_fade = _ambient_smooth(street/.19)
            stones_w = max(3.,W*(.025+.048*street))
            p = 13*math.log1p(4.0*street)
            row = math.floor(p)
            gap_y = p-row
            for x in range(W):
                wx = (x-lx)/H
                fog = exp(-((wx+.05)/.43)**2-((v-.51)/.39)**2)
                c = mix(0x070C15,0x1C2430,int(177*fog))
                light = exp(-((x-cx)/(H*.382))**2-((v-.792)/.158)**2)
                if y>=floor:
                    s = x/stones_w+(.46 if row%2 else 0.)
                    col = math.floor(s)
                    seam = min(s-col,(col+1)-s)<.057 or gap_y<.095
                    tile = ((row*61 ^ col*43) % 15)-7
                    surface = 0x16191F if seam else 0x23272C
                    c = mix(c,surface,int((108+tile*5)*street_fade))
                    glitter = ((x*73^y*137)%113)<11 and .09<gap_y<.31
                    warm = int(light*(99+tile*5+(28 if glitter else 0))*(.27+.73*street_fade))
                    c = addp(c,shade(0x926334,warm))
                    if glitter:
                        c = addp(c,shade(0xF8B966,int(light*39)))
                else:
                    haze = exp(-(wx/.218)**2-((v-.355)/.253)**2)
                    c = addp(c,shade(0xB4773A,int(haze*62)))
                self.bg.append(c)
        pole = lx-max(2,round(H*.033))
        dark, trim = 0x0B1019,0x514331
        end = min(H-1,floor+round(H*.096))
        width = max(1,round(H*.006))
        for y in range(ly+round(H*.052),end+1):
            flare = width+int(width*2*_ambient_smooth((y-end+H*.085)/(H*.085)))
            fill_row(self.bg,W,y,max(0,pole-flare),min(W,pole+flare+1),dark)
            plot(self.bg,W,H,pole+min(1,flare),y,trim)
        line_set(self.bg,W,H,pole,ly+H*.081,pole+H*.018,ly+H*.018,dark)
        line_set(self.bg,W,H,pole+H*.015,ly+H*.022,lx,ly+H*.017,trim)
        self.lantern = []
        height = max(4,round(H*.075))
        r = max(2,round(H*.038))
        for row in range(height):
            y = ly-height//2+row
            q = row/max(1,height-1)
            roof = q < .24
            half = max(1,round(r*(.46+1.9*q if roof else 1.03-.43*q)))
            for dx in range(-half,half+1):
                x = lx+dx
                if 0<=x<W and 0<=y<H:
                    frame = roof or row==height-1 or abs(dx)==half
                    c = (0x6D563B if roof and dx<1 else 0x3A3027) if frame else 0
                    self.lantern.append((y*W+x,c))
        for y in range(round(H*.39),floor):
            # Bounded fog ribbons stay mostly left of the dark side of the street.
            factor = exp(-((y/H-.56)/.11)**2)*(.6+.4*sin(y/H*25)**2)
            if factor>.09:
                self.fog.append((y,factor))
        self.moths = [(rng.uniform(.045,.138),rng.uniform(.025,.095),rng.uniform(.85,1.65),
                       rng.random()*TAU,rng.random()*TAU) for _ in range(11)]

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        density = .55+.40*sin(t*TAU/156-.45)
        for y,factor in self.fog:
            n = int(58*factor*density*(.72+.28*sin(t*.10+y/H*37)))
            center = W*(.24+.10*sin(t*.024+y/H*8))
            span = min(W*.45,H*(.26+factor*.13))
            for side in range(-3,4):
                left = max(0,round(center+span*(side-.5)*.24))
                right = min(W,round(center+span*(side+.5)*.24))
                if n and left<right:
                    ink = shade(0x1C2430,int(n*(1-(side/3.65)**2)**2))
                    i = y*W+left
                    buf[i:i+right-left] = map(addp,buf[i:i+right-left],[ink]*(right-left))
        reveal = _ambient_smooth((.43-density)/.36)
        if reveal:
            x,y = round(W*.637),round(H*.553)
            stamp(buf,W,H,x,y,self.remote[min(5,int(6*reveal))])
            line_set(buf,W,H,x,y,x,y+max(2,round(H*.074)),shade(0x3B3D42,int(106*reveal)))
            fill_row(buf,W,y,x,min(W,x+max(2,round(H*.011))),shade(0xEAB590,int(145*reveal)))
        age = t%76.8
        flicker = (.15*sin(48*age)**2*exp(-5*age)) if t>=76.8 and age<1.1 else 0.
        stamp(buf,W,H,self.x,self.y,self.glow[min(7,int(7.9*(1-flicker)))])
        core = shade(0xFFC66E,int(256*(1-flicker)))
        for i,color in self.lantern:
            buf[i] = color or core
        for r,s,speed,p,q in self.moths:
            a = t*speed+p
            x = self.x+H*(r*cos(a)+.020*sin(t*2.71+q))
            y = self.y+H*(s*sin(a+.61)+.016*cos(t*2.3+q))
            wing = max(1.,H*.006)*sin(t*28+q)
            moth = shade(0xC5AE89,int(143+70*sin(a)**2))
            ix,iy = round(x),round(y)
            plota(buf,W,H,ix,iy,moth)
            plot(buf,W,H,round(x-wing),iy+1,shade(moth,162))
            sx = round(self.x+(x-self.x)*1.9)
            sy = round(H*.813+(y-self.y)*.34)
            if 0<=sy<H and 0<=sx<W:
                for px in range(sx,min(W,sx+max(2,round(H*.01)))):
                    i = sy*W+px
                    buf[i] = shade(buf[i],194)
        return buf


class Mistwood(Scene):
    """A green dawn woodland with drifting shafts and an occasional deer."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.ground = round(H*.79)
        base = []
        for y in range(H):
            v = y/H
            meadow = _ambient_smooth((v-.65)/.35)
            for x in range(W):
                u = x/W
                haze = exp(-((u-.57)/.45)**2-((v-.48)/.39)**2)
                c = mix(0x6F8F7A,0xD5E0D8,int(56+191*haze))
                grass = .67+.23*sin(9*u+19*v)+.10*sin(23*u-13*v)
                soil = mix(0x334D3B,0x778556,int(256*grass))
                base.append(mix(c,soil,int(meadow*222)))
        for layer,(count,ground,ink,thickness) in enumerate(
                ((38,.72,0x7C9C89,.0038),(24,.80,0x537360,.007),
                 (12,.89,0x364F3F,.012),(5,.98,0x1E2B27,.020))):
            plane = base if layer<3 else [-1]*(W*H)
            for i in range(count):
                u = (i+rng.uniform(.13,.85))/count
                if layer>=2:
                    # Leave a clearing through the middle even at narrow viewport sizes.
                    u = .64+.40*u if i>=count//2 else .68*u
                x = u*W
                foot = min(H-1,round(H*(ground+rng.uniform(-.031,.041))))
                length = H*rng.uniform(.39+.12*layer,.71+.11*layer)
                width = max(1,round(H*thickness*rng.uniform(.63,1.25)))
                lean = rng.uniform(-.095,.095)*H
                tint = mix(ink,0x9BB091,rng.randrange(0,40 if layer<2 else 21))
                self._tree(plane,x,foot,length,width,lean,tint,layer)
        # Low ferns soften the bottom of the close silhouette.
        for _ in range(40):
            x = rng.uniform(0,W)
            if abs(x/W-.55)<.16:
                continue
            y = rng.uniform(.935,1.01)*H
            r = H*rng.uniform(.014,.043)
            c = rng.choice((0x213A2C,0x2C4432,0x35513A))
            for i in range(5):
                dx = (i-2)*r*.68
                ex,ey = x+dx,y-r*(1.2-.21*abs(i-2))
                line_set(plane,W,H,x,y,ex,ey,c)
                self._oval(plane,ex,ey,max(1,round(r*.18)),max(1,round(r*.25)),c)
        self.near = self._spans(plane,W,H)
        self.backgrounds = []
        colors = set(base)
        for level in range(13):
            temperature = level/12
            tones = {}
            for c in colors:
                # Warm the lit mist much more than the shaded trunks.
                n = (c>>8)&255
                target = addp(c,rgb(42,23,0))
                tones[c] = mix(c,target,int(227*temperature*n/255))
            self.backgrounds.append([tones[c] for c in base])
        self.motes = [(rng.random(),rng.random(),rng.uniform(.20,.68),rng.random()*TAU)
                      for _ in range(24)]
        self.shafts = []
        for origin, width, power in ((.33,.049,54),(.56,.044,67),(.80,.032,48)):
            profile = []
            for y in range(round(H*.10),round(H*.87)):
                v = y/H
                radius = max(1,round(W*width*(.36+.79*v)))
                along = _ambient_smooth((v-.08)/.19)*_ambient_smooth((.89-v)/.27)
                weights = bytes(round(255*along*(1-(x/radius)**2)**2)
                                for x in range(-radius,radius+1))
                profile.append((y,radius,weights))
            self.shafts.append((origin,width,power,profile))

    def _spans(self,plane,width,height):
        spans=[]
        for y in range(height):
            row=y*width
            start=None
            for x in range(width):
                if plane[row+x]>=0:
                    if start is None:
                        start=x
                elif start is not None:
                    spans.append((row+start,plane[row+start:row+x]))
                    start=None
            if start is not None:
                spans.append((row+start,plane[row+start:row+width]))
        return spans

    def _tree(self,buf,x,foot,height,width,lean,color,layer):
        W,H = self.W,self.H
        top = foot-height
        for y in range(max(0,round(top)),foot+1):
            p = (foot-y)/height
            cx = round(x+lean*p*p)
            half = max(0,round(width*(1-.82*p)))
            fill_row(buf,W,y,max(0,cx-half),min(W,cx+half+1),color)
            if layer>=2 and half>=2:
                plot(buf,W,H,cx-half+1,y,mix(color,0x7B8760,34))
        for i in range(4):
            p = .44+i*.137
            sy = foot-height*p
            if sy<0:
                continue
            sx = x+lean*p*p
            sign = -1 if i%2 else 1
            length = height*(.11+.031*i)
            ex = sx+sign*length
            ey = sy-length*(.72+.16*i)
            line_set(buf,W,H,sx,sy,ex,ey,color)
            if layer>=2:
                line_set(buf,W,H,sx,sy-1,ex,ey-1,color)
            line_set(buf,W,H,(sx+ex)*.5,(sy+ey)*.5,ex-sign*length*.11,ey-length*.39,color)
            for j in range(3):
                fx = sx+sign*length*(.86+.19*j)
                fy = ey+length*(.11-.21*j)
                rx=max(1,round(length*(.31+.04*j)))
                ry=max(1,round(length*.18))
                self._oval(buf,fx,fy,rx,ry,color)

    def _oval(self,buf,x,y,rx,ry,c):
        W,H = self.W,self.H
        cx,cy = round(x),round(y)
        for dy in range(max(-ry,-cy),min(ry,H-1-cy)+1):
            half = round(rx*sqrt(max(0.,1-(dy/ry)**2)))
            fill_row(buf,W,cy+dy,max(0,cx-half),min(W,cx+half+1),c)

    def _shaft(self,buf,origin,angle,power,profile):
        W = self.W
        palette = [shade(0xFFE2A0,round(power*x/255)) for x in range(256)]
        get = palette.__getitem__
        for y,radius,weights in profile:
            left = round(origin+angle*y)-radius
            x0,x1 = max(0,left),min(W,left+len(weights))
            if x0<x1:
                row = y*W
                buf[row+x0:row+x1] = map(addp,buf[row+x0:row+x1],
                                         map(get,weights[x0-left:x1-left]))

    def _deer(self,buf,t):
        W,H = self.W,self.H
        crossing = (t-68)%187
        if crossing>=15:
            return
        x = W*(-.07+1.14*crossing/15)
        y = self.ground+H*(.044+.012*sin(crossing*.3))
        size = max(2.1,H*.021)
        c = 0x25352A
        self._oval(buf,x,y-size*1.72,max(2,round(size*1.22)),max(1,round(size*.50)),c)
        self._oval(buf,x+size*.73,y-size*2.26,max(1,round(size*.38)),max(1,round(size*.69)),c)
        self._oval(buf,x+size*1.21,y-size*2.95,max(1,round(size*.47)),max(1,round(size*.28)),c)
        line_set(buf,W,H,x+size*.97,y-size*3.08,x+size*.64,y-size*3.63,c)
        line_set(buf,W,H,x+size*1.13,y-size*3.16,x+size*1.15,y-size*3.74,c)
        line_set(buf,W,H,x+size*1.14,y-size*3.54,x+size*1.48,y-size*3.83,c)
        for i,offset in enumerate((-.71,-.39,.49,.73)):
            stride = .67*sin(crossing*8+i*2.4)
            a,b = x+size*offset,y-size*1.57
            knee,foot = a+size*stride*.46,a+size*stride
            lift = max(0.,size*.31*cos(crossing*8+i*2.4))
            for dx in (0,max(1,round(size*.18))):
                line_set(buf,W,H,a+dx,b,knee+dx,y-size*.69,c)
                line_set(buf,W,H,knee+dx,y-size*.69,foot+dx,y-lift,c)

    def frame(self,t,dt):
        W,H = self.W,self.H
        warmth = _ambient_smooth(t/600)
        buf = self.backgrounds[round(warmth*12)][:]
        beams = []
        for i,(origin,width,power,profile) in enumerate(self.shafts):
            x = W*(origin+.043*sin(t*.029+i*1.86))
            spread = W*width
            angle = -.38+.076*sin(t*.032+i*1.3)
            power *= (.71+.46*warmth)*(.85+.15*sin(t*.073+i))
            beams.append((x,angle,spread))
            self._shaft(buf,x,angle,power,profile)
        for x,y,speed,phase in self.motes:
            j = min(H-1,round(H*(.21+.62*((y-t*speed*.008)%1))))
            i = round(W*((x+t*.0032+.011*sin(t*.27+phase))%1))
            light = max((max(0.,1-abs(i-origin-angle*j)/span)
                         for origin,angle,span in beams),default=0.)
            if light:
                plota(buf,W,H,i,j,shade(0xFFE2A0,int(123*light)))
        self._deer(buf,t)
        for start,colors in self.near:
            buf[start:start+len(colors)] = colors
        return buf


class Metropolis(Scene):
    """Amber streets and a river seen from above as late-night traffic fades."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    @staticmethod
    def _river(v):
        return .56+.22*(v-.5)+.127*sin(v*TAU+.49)

    @classmethod
    def _land(cls,u,v):
        river = abs(u-cls._river(v))<.058+.016*sin(v*9+.5)**2
        park = ((u-.22)/.12)**2+((v-.68)/.156)**2<1
        return not (river or park)

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.pad_x,self.pad_y = round(W*.041)+2,round(H*.043)+2
        self.map_w,self.map_h = MW,MH = W+2*self.pad_x,H+2*self.pad_y
        board = []
        for y in range(MH):
            v = (y-self.pad_y)/H
            for x in range(MW):
                u = (x-self.pad_x)/W
                if self._land(u,v):
                    bx = int((u+.08*sin(v*7))*66)
                    by = int((v+.06*sin(u*7))*57)
                    hash_ = (bx*71 ^ by*119 ^ bx*by*13)%23
                    brightness = 81+hash_*4
                    light = 22*exp(-((u-.48)/.32)**2-((v-.48)/.44)**2)
                    c = shade(0x392A24,int(brightness+light))
                    if hash_%7==0 and (x*11 ^ y*7)%37<3:
                        c = addp(c,0x271D16)
                elif abs(u-self._river(v))<.074:
                    glint = int(7*exp(-((u-self._river(v)-.022)/.013)**2))
                    c = addp(0x070F1A,rgb(glint//2,glint,glint))
                else:
                    c = shade(0x17241F,106+(x*23 ^ y*31)%31)
                board.append(c)
        self.cars = []
        for vertical in (False,True):
            for i in range(1,15 if vertical else 13):
                p = i/(15 if vertical else 13)+rng.uniform(-.017,.017)
                arterial = i%4==0
                ink = 0xAF804D if arterial else 0x5E4933 if i%2 else 0x7B5D39
                width = max(2,round(H*.006)) if arterial else 1
                road=[]
                for j in range(65):
                    v = j/64
                    block = min(2,int(p*3))
                    curve = p+.032*sin(v*5+block*.82)+.008*cos(v*12+i*.29)
                    if vertical:
                        u,y = curve+.10*(v-.5),v
                    else:
                        u,y = v,curve+.11*(v-.5)+.026*sin(v*7.5)
                    if self._land(u,y):
                        road.append(self._point(u,y))
                    elif len(road)>1:
                        self._road(board,road,ink,width,2 if arterial else 1)
                        road=[]
                    else:
                        road=[]
                if len(road)>1:
                    self._road(board,road,ink,width,2 if arterial else 1)
        for y in (.31,.741):
            pts=[self._point(.26+.59*i/27,y+.026*sin(i/27*TAU+i*.008))
                 for i in range(28)]
            self._road(board,pts,0xB17A44,max(1,round(H*.005)),2)
        highway=[]
        for i in range(53):
            t=i/52
            u = .105+.75*t+.127*sin((t-.08)*TAU)
            v = .023+.934*t
            highway.append(self._point(u,v))
        self._road(board,highway,0x563821,max(3,round(H*.02)),0)
        self._road(board,highway,0xDB9A57,max(2,round(H*.009)),10)
        self.roadmap=board
        self.clouds = ((.30,.24,.22),(.66,.52,.26),(.43,.79,.36))

    def _point(self,x,y):
        return self.pad_x+x*self.W,self.pad_y+y*self.H

    def _road(self,buf,points,ink,width,cars):
        MW,MH = self.map_w,self.map_h
        stroke = _gfx_line_set if self.gfx else line_set
        for x in range(-(width//2),width-width//2):
            for (ax,ay),(bx,by) in zip(points,points[1:]):
                stroke(buf,MW,MH,ax+x,ay,bx+x,by,ink)
        if not cars:
            return
        # Equal-distance waypoints keep traffic moving at a steady speed on curves.
        distance=0.
        spacing=max(1.5,self.H*.011)
        track=[points[0]]
        for (ax,ay),(bx,by) in zip(points,points[1:]):
            d=hypot(bx-ax,by-ay)
            while d and distance+spacing<=d:
                distance += spacing
                u=distance/d
                track.append((ax+(bx-ax)*u,ay+(by-ay)*u))
            distance-=d
        if len(track)<5:
            return
        rng=self.rng
        for i in range(cars):
            direction=1 if rng.random()>.46 else -1
            self.cars.append((track,rng.random(),direction*rng.uniform(.047,.082),
                              rng.random(),0xFFE8C9 if direction>0 else 0xDB4F42))

    def frame(self,t,dt):
        W,H,MW = self.W,self.H,self.map_w
        dx = self.pad_x+round(W*.028*sin(t*.008))
        dy = self.pad_y+round(H*.028*sin(t*.006+.9))
        buf=[]
        for y in range(dy,dy+H):
            start=y*MW+dx
            buf.extend(self.roadmap[start:start+W])
        activity = 1-.70*_ambient_smooth(t/600)
        for track,start,speed,threshold,color in self.cars:
            fade = _ambient_smooth((activity-threshold+.11)/.15)
            if not fade:
                continue
            p = ((start+t*speed)%1)*(len(track)-1)
            k = min(int(p),len(track)-2)
            u = p-k
            a,b = track[k],track[k+1]
            x = round(a[0]+(b[0]-a[0])*u)-dx
            y = round(a[1]+(b[1]-a[1])*u)-dy
            plota(buf,W,H,x,y,shade(color,int(189*fade)))
            plota(buf,W,H,x+1,y,shade(color,int(52*fade)))
        for j,(u,v,width) in enumerate(self.clouds):
            x = W*(u+.24*sin(t*.007+j*2))
            cy = H*(v+.063*sin(t*.012+j))
            span = W*width
            high = H*(.064+.013*j)
            for y in range(max(0,round(cy-high)),min(H,round(cy+high))):
                d = (y-cy)/high
                n = 46*max(0.,1-d*d)**2
                center = x+.37*(y-cy)+W*.032*sin(y/H*21+t*.018+j)
                for band in range(-4,5):
                    ink = shade(0x454959,int(n*(1-(band/4.75)**2)**2))
                    left = max(0,round(center+span*(band-.5)/4.5))
                    right = min(W,round(center+span*(band+.5)/4.5))
                    if ink and left<right:
                        i = y*W+left
                        buf[i:i+right-left] = map(addp,buf[i:i+right-left],[ink]*(right-left))
        return buf

class Sandcastle(Scene):
    """One afternoon on a beach, drawn from individually growing sand forms."""

    gfx_fps = 22
    mask = 0xF8FCF8
    STAGES = (('arrival', 0, 40), ('foundation', 40, 80),
              ('towers', 120, 120), ('details', 240, 90),
              ('moat', 330, 60), ('tide', 390, 120),
              ('epilogue', 510, 30))

    @staticmethod
    def ease(x):
        x = max(0., min(1., x))
        return x*x*(3-2*x)

    @staticmethod
    def growth(t, start, duration):
        return Sandcastle.ease((t-start)/duration)

    def setup(self):
        self.episode = Episode(self.rng, self.STAGES)
        self.number = -1
        self._new_episode(0)

    def _new_episode(self, number):
        self.number = number
        r = self.episode.rng(number)
        self.layout = r.randrange(3)
        self.tower_count = 3 + r.randrange(3)
        self.failed_tower = r.randrange(self.tower_count)
        self.outcome = r.randrange(1, 4)
        forced = os.environ.get('FUN_OUTCOME')
        if forced in ('1', '2', '3'):
            self.outcome = int(forced)
        self.hat = r.choice((0xDC9476, 0x78A7A0, 0xE2C280, 0xA58AB0))
        self.suit = r.choice((0xD97566, 0x527B9B, 0x8C9364, 0xB66E87))
        self.bucket = r.choice((0xDC805B, 0x5C9EA2, 0xD2B45F))
        self.offset = r.uniform(-.025, .025)
        self.shells = [(r.uniform(.39,.71),r.uniform(.76,.88),r.choice((0xF7E6CD,0xCB9D8A,0xEDE1BB))) for _ in range(11)]
        self.specks = [(r.randrange(self.W),r.randrange(int(self.H*.58),self.H),r.randrange(-16,17)) for _ in range(min(1800,self.W*self.H//85))]
        self.tower_x = [(-.105 + i*.065) for i in range(self.tower_count)]
        if self.layout == 1:
            self.tower_x = [-.10,-.045,.045,.105][:self.tower_count] + ([.15] if self.tower_count == 5 else [])
        elif self.layout == 2:
            self.tower_x = [-.13,-.065,0,.065,.13][:self.tower_count]
        self.child_poses = self._make_child_poses()

    def _rect(self, b, x0, y0, x1, y1, c):
        W,H = self.W,self.H
        x0=max(0,int(x0)); x1=min(W,int(x1)); y0=max(0,int(y0)); y1=min(H,int(y1))
        if x1>x0:
            row=[c]*(x1-x0)
            for y in range(y0,y1): b[y*W+x0:y*W+x1]=row

    def _oval(self,b,cx,cy,rx,ry,c):
        W,H=self.W,self.H
        if rx<=0 or ry<=0:return
        for y in range(max(0,int(cy-ry)),min(H,int(cy+ry)+1)):
            q=1-((y-cy)/ry)**2
            if q>0:
                reach=rx*sqrt(q)
                self._rect(b,cx-reach,y,cx+reach+1,y+1,c)

    def _line(self,b,x0,y0,x1,y1,c,thick=1):
        for d in range(max(1,int(thick))):
            line_set(b,self.W,self.H,x0,y0+d,x1,y1+d,c)

    def _background(self,t):
        W,H=self.W,self.H
        dusk=self.ease((t-300)/220)
        sky_top=mix(0xBFE0EE,0xE7A0A0,int(dusk*210))
        sky_bottom=mix(0xE5EDF0,0xFFD79A,int(dusk*235))
        horizon=int(H*.395)
        sandline=int(H*.585)
        b=[0]*(W*H)
        for y in range(H):
            if y<horizon:
                c=mix(sky_top,sky_bottom,int(y/max(1,horizon)*255))
            elif y<sandline:
                d=(y-horizon)/max(1,sandline-horizon)
                c=mix(0x70B4B4,0x2E8C93,int(d*215))
                c=mix(c,0xE9C8A2,int(dusk*45))
            else:
                d=(y-sandline)/max(1,H-sandline)
                c=mix(0xE8D2A6,0xD2B581,int(d*90))
            b[y*W:(y+1)*W]=[c]*W
        # A shallow beach slope and bounded grain sit beneath all moving forms.
        for x,y,v in self.specks:
            if y >= sandline+H*.018*sin(x/W*7):
                i=y*W+x; b[i]=mix(b[i],0x897959,32+max(0,v))
        sun_x=int(W*(.81-.22*t/540)); sun_y=int(H*(.13+.20*t/540))
        self._oval(b,sun_x,sun_y,max(2,W*.021),max(2,H*.027),mix(0xFFF7D2,0xFCD084,int(dusk*170)))
        # Layered distant surf has independent slow phases, not a repeated story.
        for k in range(4):
            yy=H*(.43+k*.038)
            for x in range(0,W,max(1,W//150)):
                dx=x/W
                wave=H*.004*sin(dx*16+k*2+t*(.085+.009*k))
                self._line(b,x,yy+wave,x+max(1,W//150),yy+wave,0xB4D5D1)
        return b

    def _sand_and_water(self,b,t):
        W,H=self.W,self.H
        # The wet boundary advances continuously, then a single broad surge arrives.
        advance=self.ease((t-390)/120)
        surge=self.ease((t-482)/17)*(1-self.ease((t-505)/8))
        boundary=H*(.673+.060*advance+.053*surge)
        coast=int(H*.585)
        low=max(coast,int(boundary-H*.010))
        high=min(H,int(boundary+H*.010))
        # Fill whole rows first; only the narrow scalloped edge needs per-column work.
        for y in range(coast,low):
            depth=(y-coast)/max(1,boundary-coast)
            c=mix(0x6FAEB0,0x90B5A4,int(depth*160))
            b[y*W:(y+1)*W]=[c]*W
        for y in range(high,min(H,high+int(H*.049))):
            d=(y-high)/max(1,H*.049)
            c=mix(0xB79A6A,0xD4BA8C,int(d*190))
            b[y*W:(y+1)*W]=[c]*W
        for x in range(W):
            edge=boundary+H*.006*sin(x/W*14+t*.17)+H*.003*sin(x/W*33-t*.13)
            top=max(0,min(H,int(edge)))
            for y in range(low,top):
                b[y*W+x]=mix(0x81B4B0,0xA7B6A0,int((y-coast)/max(1,boundary-coast)*100))
            for y in range(top,high):
                b[y*W+x]=0xB79A6A
            foam_y=min(H-1,top-1)
            b[foam_y*W+x]=0xF5E9D7
            if foam_y+1<H:b[(foam_y+1)*W+x]=0xF5E9D7
        for j in range(3):
            yy=coast+(boundary-coast)*(.22+j*.24)
            for x in range(0,W,max(1,W//120)):
                y=yy+H*.0025*sin(x/W*19+t*.13+j*2)
                self._line(b,x,y,x+max(1,W//120),y,0xC0D9CE)
        return boundary

    def _footprints(self,b,t):
        W,H=self.W,self.H
        # Time-addressed footprints persist without accumulating frame history.
        steps=[]
        for i in range(13):
            when=6+i*3.2
            if t>=when:steps.append((.02+i*.031,.76+(.008 if i%2 else 0)))
        for trip in range(2):
            for i in range(9):
                when=52+trip*32+i*2.5
                if t>=when:steps.append((.48-i*.024,.75+(.009 if i%2 else 0)))
        if t>=512:
            for i in range(min(12,int((t-512)*.75))):steps.append((.41-i*.029,.77+(.008 if i%2 else 0)))
        for x,y in steps[:48]:
            self._oval(b,W*x,H*y,max(1,W*.004),max(1,H*.003),0xB59A72)

    def _tower(self,b,x,ground,w,h,g,shade_left=True):
        if g<=0:return
        W,H=self.W,self.H
        width=max(1,W*w*(.55+.45*g)); height=max(1,H*h*g)
        x=W*x; y=H*ground
        self._oval(b,x,y,max(2,width*.72),max(1,H*.01),0xB69669)
        self._rect(b,x-width*.50,y-height,x+width*.50,y,0xCCAF7D)
        self._rect(b,x-width*.50,y-height,x-width*.18,y,0xB89A6C)
        self._rect(b,x+width*.29,y-height,x+width*.50,y,0xE4C99A)
        self._oval(b,x,y-height,width*.50,max(1,H*.012),0xEAD3A8)
        if g>.75:
            for j in range(4):
                xx=x-width*.49+j*width*.27
                self._rect(b,xx,y-height-H*.011*g,xx+width*.16,y-height,0xD8BC8B)
            self._rect(b,x-width*.065,y-height*.77,x+width*.05,y-height*.62,0x8E7656)

    def _castle(self,b,t):
        W,H=self.W,self.H
        cx=.555+self.offset; ground=.765
        if 19<t<53:
            outline=self.growth(t,19,19)
            left=W*(cx-.125); right=W*(cx+.125)
            top=H*(ground-.025); bottom=H*(ground+.012)
            self._line(b,left,top,left+(right-left)*outline,top,0xAA8F69)
            self._line(b,left,top,left,bottom*outline+top*(1-outline),0xAA8F69)
            self._line(b,right,top,right,bottom*outline+top*(1-outline),0xAA8F69)
            self._line(b,left,bottom,right*outline+left*(1-outline),bottom,0xAA8F69)
        foundation=self.growth(t,43,72)
        if not foundation:return
        # Sand platform rises with patting; every architectural element grows separately.
        self._oval(b,W*cx,H*ground,W*.145*foundation,H*.022*foundation,0xBA9A6D)
        self._rect(b,W*(cx-.13)*foundation+W*cx*(1-foundation),H*(ground-.018*foundation),
                   W*(cx+.13)*foundation+W*cx*(1-foundation),H*ground,0xD7B783)
        keep=self.growth(t,185,30)
        self._tower(b,cx,ground,.055,.105,keep)
        for i,dx in enumerate(self.tower_x):
            start=125+i*21
            grow=self.growth(t,start,18)
            if i==self.failed_tower:
                collapse=self.growth(t,start+19,8)*(1-self.growth(t,start+43,18))
                grow*=1-collapse*.88
            if t>=488 and self.outcome>=2:
                if self.outcome==3:grow*=1-self.growth(t,488,18)
                elif i==self.failed_tower:grow*=1-self.growth(t,488,18)
            self._tower(b,cx+dx,ground,.038,.065+(i%2)*.022,grow)
            if t>=start+14 and t<start+24:
                self._oval(b,W*(cx+dx),H*(ground-.08),W*.015,H*.01*(1-self.growth(t,start+14,10)),0xE8D2A6)
        wall=self.growth(t,244,47)
        if t>=488:
            wall*=1-self.growth(t,488,20) if self.outcome==3 else 1-self.growth(t,488,20)*.65 if self.outcome==2 else 1
        if wall>0:
            top=ground-.050*wall
            self._rect(b,W*(cx-.10),H*top,W*(cx+.10),H*(ground-.012),0xC9A978)
            self._rect(b,W*(cx-.10),H*top,W*(cx-.085),H*(ground-.012),0xA98B63)
            for i in range(14):
                if t>=258+i*3:
                    x=W*(cx-.095+i*.014)
                    self._rect(b,x,H*(top-.009),x+W*.008,H*top,0xE2C495)
            # Arch opening and individually appearing windows.
            if t>=283:
                self._oval(b,W*cx,H*(ground-.036),W*.014,H*.018,0x806A4B)
                self._rect(b,W*(cx-.014),H*(ground-.036),W*(cx+.014),H*ground,0x806A4B)
            for i in range(4):
                if t>=295+i*6:
                    x=W*(cx-.067+i*.044)
                    self._rect(b,x,H*(ground-.041),x+W*.006,H*(ground-.035),0x907758)
        for i in range(7):
            if t>=303+i*4:
                xx=W*(cx-.13+i*.043)
                self._tower(b,xx/W,ground,.009,.023,self.growth(t,303+i*4,8))
        if t>=314:
            flag=self.growth(t,314,12)
            fx=W*(cx+.026); fy=H*(ground-.105)
            self._line(b,fx,fy,fx,fy-H*.065*flag,0x67583F,max(1,W*.002))
            self._oval(b,fx+W*.011,fy-H*.056*flag,W*.013*flag,H*.007,0x7B9C66)
        for x,y,c in self.shells:
            if t>300+(x-.39)*100:self._oval(b,W*x,H*y,max(1,W*.004),max(1,H*.004),c)
        if t>=333:
            m=self.growth(t,333,40)
            self._oval(b,W*cx,H*(ground+.023),W*.16*m,H*.028*m,0xA9895D)
            self._oval(b,W*cx,H*(ground+.023),W*.13*m,H*.018*m,0xD3B581)
            if t>=395:
                fill=self.growth(t,395,99)
                self._oval(b,W*cx,H*(ground+.023),W*.15*m,H*.021*m, mix(0xA9895D,0x65A7A4,int(fill*230)))
            channel=self.growth(t,352,35)
            self._line(b,W*(cx+.135),H*(ground+.035),W*(cx+.25*channel),H*.685,0xA9895D,max(1,H*.009))
            if t>=415:
                self._line(b,W*(cx+.135),H*(ground+.035),W*(cx+.25),H*.685,0x72AAA7,max(1,H*.006))
        if t>=488 and self.outcome==3:
            self._oval(b,W*cx,H*ground,W*.115*self.growth(t,488,18),H*.013,0xB79A6A)

    def _make_child_poses(self):
        """Six opaque-on-transparent poses, rasterized once per episode and size."""
        size=max(14,self.H*.145)
        sw=max(18,round(size*1.35)); sh=max(19,round(size*1.19))
        artist=Sandcastle.__new__(Sandcastle)
        artist.W,artist.H=sw,sh
        cx=sw*.48; feet=sh-1; skin=0xB88362
        poses=[]
        # Walking A/B, digging, patting, bucket flip, admiring/waving.
        for pose in range(6):
            b=[-1]*(sw*sh)
            kick=(.13 if pose==0 else -.13 if pose==1 else 0)*size
            artist._line(b,cx-size*.07,feet-size*.31,cx-size*.10+kick,feet,skin,max(1,size*.065))
            artist._line(b,cx+size*.07,feet-size*.31,cx+size*.10-kick,feet,skin,max(1,size*.065))
            artist._oval(b,cx,feet-size*.43,size*.17,size*.23,self.suit)
            left_y=feet-size*(.48 if pose in (0,1) else .24 if pose==2 else .33 if pose==3 else .82 if pose==4 else .72)
            right_y=feet-size*(.35 if pose in (0,1,2,3) else .78 if pose==4 else .68)
            artist._line(b,cx-size*.12,feet-size*.55,cx-size*.24,left_y,skin,max(1,size*.06))
            artist._line(b,cx+size*.12,feet-size*.55,cx+size*.23,right_y,skin,max(1,size*.06))
            artist._oval(b,cx,feet-size*.79,size*.17,size*.19,skin)
            artist._oval(b,cx,feet-size*.94,size*.25,size*.08,self.hat)
            artist._rect(b,cx-size*.15,feet-size*1.01,cx+size*.15,feet-size*.94,self.hat)
            artist._oval(b,cx+size*.075,feet-size*.80,max(1,size*.013),max(1,size*.013),0x4B3E36)
            bx=cx-size*.24; by=left_y+size*.11
            if pose==4:by=feet-size*.85
            artist._rect(b,bx-size*.10,by-size*.13,bx+size*.10,by+size*.12,self.bucket)
            rim=by+size*.12 if pose==4 else by-size*.13
            artist._line(b,bx-size*.09,rim,bx+size*.09,rim,0xF1D8AD)
            if pose in (0,1,2,3):
                artist._line(b,cx+size*.23,right_y,cx+size*.32,feet-size*.08,0x775B43,max(1,size*.027))
                artist._oval(b,cx+size*.32,feet-size*.08,size*.055,size*.05,0xA1A3A1)
            poses.append(b)
        return sw,sh,poses

    def _child(self,b,t):
        W,H=self.W,self.H
        if t<3 or t>537:return
        if t<39:x=.02+.40*self.ease((t-3)/33)
        elif t<120:
            phase=(t-40)%32
            x=.44-.22*self.ease(phase/13) if phase<16 else .22+.22*self.ease((phase-16)/14)
        elif t<330:x=.405+.018*sin(t*.10)
        elif t<387:x=.40+.06*self.ease((t-330)/44)
        elif t<510:x=.39+(.009*sin(t*1.4) if self.outcome==1 and t>490 else 0)
        else:x=.39-.43*self.ease((t-510)/27)
        walking=(t<40 or 40<=t<120 or t>=510)
        if walking:pose=int(t*1.8)%2
        elif t<120:pose=2
        elif t<240:
            collapse_time=125+self.failed_tower*21+24
            pose=5 if collapse_time<=t<collapse_time+8 else 4 if ((t-120)%21)<9 else 2
        elif t<330:pose=3 if int(t*.55)%2 else 2
        elif t<390:pose=2 if int(t*.7)%2 else 3
        elif t>490 and t<510:pose=5 if int(t*1.4)%2 else 4
        else:pose=5
        sw,sh,poses=self.child_poses
        feet=int(H*(.773+.005*sin(t*.22) if walking else .773))
        cx=int(W*x)
        shadow=sh*(.30+.45*t/540)
        self._oval(b,cx+shadow*.35,feet+H*.004,shadow,max(1,sh*.045),0xBBA274)
        left=cx-sw//2; top=feet-sh+1
        sprite=poses[pose]
        for yy in range(sh):
            y=top+yy
            if not 0<=y<H:continue
            src=yy*sw
            dst=y*W+left
            for xx in range(sw):
                if 0<=left+xx<W and sprite[src+xx]>=0:
                    b[dst+xx]=sprite[src+xx]

    def _wildlife(self,b,t):
        W,H=self.W,self.H
        for j in range(2):
            x=W*((.12+j*.4+t*(.00036+j*.00012))%1.)
            y=H*(.20+j*.075+.012*sin(t*.14+j))
            wing=H*.011*sin(t*.55+j)
            self._line(b,x-W*.014,y+wing,x,y,0x58676B)
            self._line(b,x,y,x+W*.014,y-wing,0x58676B)
        if t>345 and t<525:
            x=W*(.78-.00038*(t-345)+.008*sin(t*.19)); y=H*.792
            self._oval(b,x,y,W*.008,H*.006,0xB76F58)
            for d in (-1,1):
                for k in range(2):self._line(b,x+d*W*.006,y,x+d*W*(.011+k*.004),y+H*.007,0x9B6452)
        if 363<t<435:
            x=W*(.83-.001*(t-363)); y=H*.70
            self._oval(b,x,y,W*.011,H*.007,0xD8D2BE)
            self._line(b,x,y,x-W*.008,y+H*.018,0x716C62)

    def frame(self,t,dt):
        number,local,opacity=self.episode.clock(t)
        if number!=self.number:self._new_episode(number)
        b=self._background(local)
        self._sand_and_water(b,local)
        self._footprints(b,local)
        self._castle(b,local)
        self._child(b,local)
        self._wildlife(b,local)
        if opacity<1:
            level=int(opacity*256)
            palette={c:shade(c,level) for c in set(b)}
            b=list(map(palette.__getitem__,b))
        return b


SCENES = {
    'aurora': Aurora, 'ripples': Ripples, 'fireflies': Fireflies, 'snow': Snow, 'lava': Lava,
    'waves': Waves, 'galaxy': Galaxy, 'mistwood': Mistwood,
    'school': School, 'lighthouse': Lighthouse, 'donut': Donut, 'sakura': Sakura, 'skyline': Skyline,
    'matrix': Matrix, 'pendulum': Pendulum,
    'constellation': Constellation, 'sonar': Sonar, 'streetlamp': Streetlamp, 'fireworks': Fireworks,
    'boids': Boids, 'fire': Fire,
    'koi': Koi,
    'bokeh': Bokeh,
    'lanterns': Lanterns,
    'nebula': Nebula,
    'prism': Prism,
    'flyover': Flyover,
    'attractor': Attractor,
    'jellyfish': Jellyfish,
    'dunes': Dunes,
    'orrery': Orrery,
    'thunder': Thunder,
    'kaleido': Kaleido,
    'fractal': Fractal,
    'cyclic': Cyclic,
    'stainedglass': StainedGlass,
    'metropolis': Metropolis,
    'silk': Silk,
    'filings': Filings,
    'startrails': StarTrails,
    'sandcastle': Sandcastle,
}

ALIASES = {
    'plexus': 'constellation',
    'spiro': 'kaleido',
    'tesseract': 'kaleido',
    'lissajous': 'sonar',
    'mystify': 'lighthouse',
    'wormhole': 'streetlamp',
    'circuit': 'metropolis',
}


if __name__ == '__main__':
    sys.exit(main())
