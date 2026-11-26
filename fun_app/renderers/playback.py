"""Terminal playback, frame pacing, headless checks, and renderer CLI."""
import atexit
import gc
import os
import signal
import sys
import time
import traceback

from .half_block import Encoder
from .kitty import (
    KittyGraphics,
    _GFX_CAPS,
    _GFX_DEFAULT,
    _GFX_LEVELS,
    _GFX_MAX_BPS,
    _GFX_ZLIB_CAPS,
    _PosixShm,
    _gfx_size,
    make_gfx_scene,
)
from .terminal import Terminal, termios
from ..scenes.base import make_scene
from ..scenes.registry import ALIASES, SCENES


HELP = """
extras.py - terminal screensavers for the `fun` launcher.

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

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "fun")
LOG_FILE = os.path.join(CACHE_DIR, "errors.log")
DUTY = 0.35            # max fraction of one core a scene may use
MIN_COLS, MIN_ROWS = 24, 8


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
        sys.stderr.write(HELP + '\nscenes: ' + ', '.join(SCENES) + '\n')
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
