"""Login-scoped coordination in the user's private runtime directory."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


class Runtime:
    def __init__(self, display):
        key = hashlib.sha256(display.encode()).hexdigest()[:16]
        self.unit = 'fun-idle-' + key
        root = Path(os.getenv('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
        st = root.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise OSError('a private XDG_RUNTIME_DIR is required')
        self.path = root / self.unit
        self.path.mkdir(mode=0o700, exist_ok=True)

    @contextlib.contextmanager
    def claim(self, name):
        # Never unlink a lock inode while another process can hold it.
        with (self.path / name).open('a+') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield None
                return
            yield stream

    def holder(self, name):
        try:
            with (self.path / name).open() as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    return stream.read().strip()
        except FileNotFoundError:
            pass
        return None

    def publish(self, state):
        tmp = self.path / 'state.tmp'
        tmp.write_text(json.dumps(state))
        tmp.replace(self.path / 'state')

    def state(self):
        if self.holder('watcher') is None:
            return {}
        try:
            return json.loads((self.path / 'state').read_text())
        except FileNotFoundError:
            return {}

    def test(self):
        if self.holder('watcher') is None:
            print('No watcher in this login. Enable idle in fun-config and log in again.')
            return 1
        with self.claim('test') as stream:
            if stream is None:
                print('Another idle test is running.')
                return 1
            token = uuid.uuid4().hex
            stream.truncate(0)
            stream.write(token)
            stream.flush()
            print('Leave input untouched for 10 seconds. Move the mouse once the saver is visible.', flush=True)
            deadline = time.monotonic() + 120
            last = ''
            while time.monotonic() < deadline:
                state = self.state()
                if self.holder('watcher') is None:
                    print('Watcher stopped. Check fun-idle --diagnose.')
                    return 1
                if state.get('test') == token:
                    message = state['result']
                    if message != last:
                        print(time.strftime('%T'), message, flush=True)
                        last = message
                    if message.startswith(('PASS', 'FAIL')) and state.get('threshold') == state['minutes'] * 60:
                        return int(message.startswith('FAIL'))
                time.sleep(.2)
            print('Test timed out. Check fun-idle --diagnose for blockers.')
            return 1
