"""Terminal I/O, window sizing, and terminal state restoration."""
import os
import re
import select
import struct
import time


try:
    import fcntl
    import termios
except ImportError:  # pragma: no cover
    fcntl = termios = None


_CELL_PIXELS = re.compile(rb'\x1b\[6;(\d+);(\d+)t')


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
