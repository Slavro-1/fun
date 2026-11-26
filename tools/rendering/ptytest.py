import os, pty, sys, time, signal, fcntl, termios, struct, select, resource, re
EXTRAS = sys.argv[1]
names = sys.argv[2].split(',') if len(sys.argv) > 2 and sys.argv[2] != 'all' else None
mode = sys.argv[3] if len(sys.argv) > 3 else 'term'
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('ex', EXTRAS); ex = importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)
if not names: names = list(ex.SCENES)

def run(name, how, secs=3.0, size=(49,118)):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ['TERM'] = 'xterm-kitty'
        os.execvp('python3', ['python3', '-I', EXTRAS, name])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', size[0], size[1], 0, 0))
    os.kill(pid, signal.SIGWINCH)
    buf = b''; t0 = time.time(); sent = False
    def pump(dur):
        nonlocal buf
        end = time.time() + dur
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try: d = os.read(fd, 1 << 20)
                except OSError: return False
                if not d: return False
                buf += d
        return True
    pump(secs)
    mid = len(buf)
    if how == 'resize':
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 90, 0, 0)); os.kill(pid, signal.SIGWINCH); pump(1.5)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 8, 24, 0, 0)); os.kill(pid, signal.SIGWINCH); pump(1.0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 60, 240, 0, 0)); os.kill(pid, signal.SIGWINCH); pump(1.5)
        how = 'term'
    if how == 'q': os.write(fd, b'q')
    elif how == 'ctrlc': os.write(fd, b'\x03')
    elif how == 'term': os.kill(pid, signal.SIGTERM)
    elif how == 'hup': os.kill(pid, signal.SIGHUP)
    pump(0.3)
    deadline = time.time() + 4
    status = None; ru = None
    while time.time() < deadline:
        p, st, ru = os.wait4(pid, os.WNOHANG)
        if p: status = st; break
        pump(0.1)
    if status is None:
        os.kill(pid, signal.SIGKILL)
        os.wait4(pid, 0)
        os.close(fd)
        return dict(name=name, ok=False, why='did not exit within 4 s of ' + how)
    pump(0.1)
    os.close(fd)
    code = os.waitstatus_to_exitcode(status)
    tail = buf[-80:]
    leave = b'\x1b[?25h' in tail and b'\x1b[?1049l' in tail and b'\x1b[?7h' in tail
    cpu = (ru.ru_utime + ru.ru_stime) / secs if ru else 0
    return dict(name=name, ok=(code == 0 and leave), code=code, leave=leave, cpu=cpu, kbs=mid / secs / 1024.0, tail=tail)

bad = 0
print('%-14s %-6s %5s %8s %8s' % ('scene', 'result', 'code', 'cpu%', 'KB/s'))
for n in names:
    r = run(n, mode)
    if not r['ok']: bad += 1
    print('%-14s %-6s %5s %7.1f%% %8.1f %s' % (n, 'OK' if r['ok'] else 'FAIL', r.get('code'), r.get('cpu', 0) * 100, r.get('kbs', 0), r.get('why', '') or ('' if r['ok'] else repr(r.get('tail')))))
print('FAILURES:', bad)
sys.exit(bool(bad))
