"""Kitty graphics transport, frame packing, and framebuffer sizing."""
import array
import base64
import errno
import os
import re
import sys
import zlib

from ..scenes.base import make_scene
from ..scenes.drawing import sqrt


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
