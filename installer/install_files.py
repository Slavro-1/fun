"""Transactional file installation for the Linux installer. Uses only the stdlib."""
from contextlib import contextmanager, ExitStack
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path('/usr/local')
# Keep the legacy install paths so existing ownership manifests remain valid.
SOURCES = {
    'fun': 'bin/fun',
    'fun-idle': 'bin/fun-idle',
    'fun-config': 'bin/fun-config',
    'extras.py': 'lib/fun/extras.py',
    'installer/compat/fun_settings.py': 'lib/fun/fun_settings.py',
    'installer/compat/fun_wayland.py': 'lib/fun/fun_wayland.py',
    'installer/compat/fun_runtime.py': 'lib/fun/fun_runtime.py',
    'installer/compat/fun_session.py': 'lib/fun/fun_session.py',
    'fun_app/gui/preview.py': 'lib/fun/snap.py',
    **{name: f'lib/fun/{name}' for name in (
        'fun_app/__init__.py',
        'fun_app/legacy_savers.sh',
        'fun_app/paths.py',
        'fun_app/settings.py',
        'fun_app/gui/__init__.py',
        'fun_app/gui/config.py',
        'fun_app/idle/__init__.py',
        'fun_app/idle/runtime.py',
        'fun_app/idle/session.py',
        'fun_app/idle/watcher.py',
        'fun_app/idle/wayland.py',
        'fun_app/renderers/__init__.py',
        'fun_app/renderers/half_block.py',
        'fun_app/renderers/kitty.py',
        'fun_app/renderers/playback.py',
        'fun_app/renderers/terminal.py',
        'fun_app/scenes/__init__.py',
        'fun_app/scenes/ambient.py',
        'fun_app/scenes/ambient_drawing.py',
        'fun_app/scenes/base.py',
        'fun_app/scenes/cinematic.py',
        'fun_app/scenes/classic.py',
        'fun_app/scenes/drawing.py',
        'fun_app/scenes/registry.py',
    )},
}
STARTUP = """[Desktop Entry]
Type=Application
Name=fun idle screensaver
Comment=Start the fun terminal screensavers using saved idle settings
Exec={prefix}/bin/fun-idle --autostart
TryExec={prefix}/bin/fun-idle
Terminal=false
NoDisplay=true
"""
OLD_STARTUP = STARTUP.split('Exec=')[0] + """Exec={prefix}/bin/fun-idle
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""
MENU = """[Desktop Entry]
Type=Application
Name=fun settings
Comment=Configure terminal screensavers
Exec={prefix}/bin/fun-config
Icon=preferences-system
Categories=Settings;Graphics;
Terminal=false
"""


class Conflict(ValueError):
    pass


def note(message):
    print(message, file=sys.stderr)


class Files:
    """Pin each parent directory and never follow links during traversal or reads."""

    def __init__(self, stack, create, system=False):
        self.stack = stack
        self.create = create
        self.system = system
        self.dirs = {}

    def directory(self, path, create=False):
        if not path.is_absolute() or '..' in path.parts:
            raise Conflict(f'Expected an absolute destination: {path}')
        if path in self.dirs:
            return self.dirs[path]
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if path == path.parent:
            fd = os.open(path, flags)
        else:
            parent = self.directory(path.parent, create)
            try:
                fd = os.open(path.name, flags, dir_fd=parent)
            except FileNotFoundError:
                if not (self.create and create):
                    raise
                try:
                    os.mkdir(path.name, 0o755, dir_fd=parent)
                except FileExistsError:
                    pass
                fd = os.open(path.name, flags, dir_fd=parent)
        self.stack.callback(os.close, fd)
        if self.system and path.is_relative_to(PREFIX):
            info = os.fstat(fd)
            # Debian may grant the local administrators in "staff" group write access.
            try:
                group = grp.getgrgid(info.st_gid).gr_name
            except KeyError:
                group = None
            if (info.st_uid != os.geteuid() or info.st_mode & 0o002
                    or (info.st_mode & 0o020 and group not in ('root', 'staff'))):
                raise Conflict(f'Unsafe owner or write permissions on {path}')
        self.dirs[path] = fd
        return fd

    def lock(self, path):
        try:
            fd = self.directory(path, create=True)
        except FileNotFoundError:
            return
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def inspect(self, path, read=False, limit=65536):
        try:
            parent = self.directory(path.parent)
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None, None
        if not stat.S_ISREG(info.st_mode):
            raise Conflict(f'Unexpected file type at {path}')
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(path.name, flags, dir_fd=parent), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise Conflict(f'File type changed at {path}')
            if read and limit is not None and info.st_size > limit:
                raise Conflict(f'Oversized metadata at {path}')
            data = stream.read() if read else None
            digest = hashlib.sha256(data) if read else hashlib.file_digest(stream, 'sha256')
            return [info.st_dev, info.st_ino, info.st_uid, info.st_mode, digest.hexdigest()], data

    def writable(self, path):
        fd = self.directory(path.parent, create=True)
        if not os.access('.', os.W_OK | os.X_OK, dir_fd=fd, effective_ids=True):
            raise Conflict(f'Destination is not writable: {path.parent}')

    def unlink(self, path):
        os.unlink(path.name, dir_fd=self.directory(path.parent))

    def link(self, src, dst):
        fd = self.directory(src.parent)
        os.link(src.name, dst.name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)

    def replace(self, src, dst):
        fd = self.directory(src.parent)
        os.replace(src.name, dst.name, src_dir_fd=fd, dst_dir_fd=fd)

    def stage(self, path, data, mode):
        temp = path.with_name('.fun-stage-' + secrets.token_hex(12))
        fd = os.open(temp.name, os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600,
                     dir_fd=self.directory(temp.parent))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
        except BaseException:
            self.unlink(temp)
            raise
        return temp


class Transaction:
    def __init__(self, files):
        self.fs = files
        self.observed = {}
        self.changes = []
        self.temporary = {}
        self.applied = []
        self.keep = set()

    def change(self, path, before, data=None, mode=0o644, backup=False):
        self.fs.writable(path)
        temp = None
        after = None
        if data is not None:
            temp = self.fs.stage(path, data, mode)
            after, _ = self.fs.inspect(temp)
            self.temporary[temp] = after
        self.changes.append((path, before, temp, after, backup))
        return after

    def apply(self):
        for directory, fd in self.fs.dirs.items():
            if directory != directory.parent:
                parent_fd = self.fs.dirs[directory.parent]
                actual = os.stat(directory.name, dir_fd=parent_fd, follow_symlinks=False)
                if not os.path.samestat(actual, os.fstat(fd)):
                    raise Conflict(f'Destination directory changed: {directory}')
        for path, expected in self.observed.items():
            if self.fs.inspect(path)[0] != expected:
                raise Conflict(f'File changed since preflight: {path}')
        for path, before, temp, after, backup in self.changes:
            if temp and self.fs.inspect(temp)[0] != after:
                raise Conflict(f'Staged file changed: {temp}')
            if self.fs.inspect(path)[0] != before:
                raise Conflict(f'File changed during installation: {path}')
            old = None
            if before:
                old = path.with_name(path.name + '.bak-' + secrets.token_hex(10))
                self.fs.link(path, old)
                self.temporary[old] = before
                if self.fs.inspect(old)[0] != before:
                    raise Conflict(f'File changed during backup: {path}')
            if temp is None:
                self.fs.unlink(path)
            elif before is None:
                self.fs.link(temp, path)  # exclusive creation
            else:
                self.fs.replace(temp, path)
            self.applied.append((path, after, old))
            if backup:
                self.keep.add(old)

    def finish(self, success):
        if not success:
            self.keep.clear()
            for path, after, old in reversed(self.applied):
                try:
                    if self.fs.inspect(path)[0] != after:
                        raise Conflict('destination changed')
                    if old and self.fs.inspect(old)[0] != self.temporary[old]:
                        raise Conflict('backup changed')
                    if old and after is None:
                        self.fs.link(old, path)
                    elif old:
                        self.fs.replace(old, path)
                    else:
                        self.fs.unlink(path)
                except (ValueError, OSError) as exc:
                    self.keep.add(old)
                    note(f'Could not restore {path}: {exc}. Prior copy: {old}')
        for path, expected in self.temporary.items():
            if path in self.keep:
                note(f'Kept backup {path}')
                continue
            try:
                current, _ = self.fs.inspect(path)
                if current == expected:
                    self.fs.unlink(path)
                elif current:
                    note(f'Retained changed transaction file {path}')
            except (OSError, ValueError) as exc:
                note(f'Could not remove transaction file {path}: {exc}')


def manifest(fs, path, allowed):
    identity, data = fs.inspect(path, read=True)
    if not identity:
        return None, {}
    if identity[2] != os.geteuid() or identity[3] & 0o022:
        raise Conflict(f'Unexpected owner or permissions on {path}')
    value = json.loads(data)
    if not isinstance(value, dict) or value.get('format') != 'fun-install-1':
        raise Conflict(f'Invalid ownership manifest: {path}')
    entries = value.get('files')
    if not isinstance(entries, dict) or not entries.keys() <= {str(p) for p in allowed}:
        raise Conflict(f'Unexpected paths in {path}. Check the original XDG directories.')
    for record in entries.values():
        if not (isinstance(record, list) and len(record) == 5
                and all(type(n) is int for n in record[:4]) and isinstance(record[4], str)
                and len(record[4]) == 64 and all(c in '0123456789abcdef' for c in record[4])):
            raise Conflict(f'Invalid identity in {path}')
    return identity, entries


def layout(fs, system, installing):
    if system:
        targets = {}
        for src, destination in SOURCES.items():
            path = PREFIX / destination
            executable = destination.startswith('bin/') or src == 'extras.py'
            content = None
            if installing:
                _, content = fs.inspect(ROOT / src, read=True, limit=None)
                if content is None:
                    raise Conflict(f'Missing source file: {src}')
            targets[path] = (content, 0o755 if executable else 0o644)
        return PREFIX, PREFIX / 'lib/fun/ownership.json', targets, {}
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    data = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
    startup = config / 'autostart/fun-idle.desktop'
    menu = data / 'applications/fun-config.desktop'
    current, old, app = [s.format(prefix=PREFIX).encode() for s in (STARTUP, OLD_STARTUP, MENU)]
    targets = {startup: (current, 0o644), menu: (app, 0o644)}
    known = {startup: (current, old), menu: (app,)}
    for path, templates in [(home / '.config/autostart/fun-idle.desktop', (old, current)),
                            (home / '.local/share/applications/fun-config.desktop', (app,))]:
        if path not in targets:
            targets[path] = (None, 0)
            known[path] = templates
    return home, config / 'fun/desktop-ownership.json', targets, known


def plan(tx, system, installing):
    lock, record_path, targets, known = layout(tx.fs, system, installing)
    fs = tx.fs
    fs.lock(lock)
    owner, records = manifest(fs, record_path, targets)
    tx.observed[record_path] = owner
    adopt = []
    new = {}
    for path, (content, mode) in targets.items():
        try:
            before, data = fs.inspect(path, read=path in known)
        except Conflict as exc:
            if installing:
                raise
            note(f'Retained {path}: {exc}')
            continue
        tx.observed[path] = before
        tracked = records.get(str(path))
        if not installing:
            if before:
                if before == tracked:
                    tx.change(path, before)
                else:
                    note(f'Retained {path}: modified or unowned')
            continue
        if tracked and before and before != tracked:
            raise Conflict(f'Installed file has changed: {path}. Move it aside before upgrading.')
        if before and not tracked:
            if path in known and data not in known[path]:
                raise Conflict(f'Unrecognized desktop entry: {path}')
            if system:
                if owner:
                    raise Conflict(f'Unowned program file: {path}')
                adopt.append(str(path))
        if content is None:
            if before:
                tx.change(path, before, backup=True)
            continue
        if (before and before[2] == os.geteuid() and before[3] == (stat.S_IFREG | mode)
                and before[4] == hashlib.sha256(content).hexdigest()):
            new[str(path)] = before
        else:
            new[str(path)] = tx.change(path, before, content, mode, backup=bool(before))
    if installing and (not owner or new != records):
        data = json.dumps({'format': 'fun-install-1', 'files': new}, indent=2).encode() + b'\n'
        tx.change(record_path, owner, data, 0o600)
    elif not installing and owner:
        tx.change(record_path, owner)
    return adopt


@contextmanager
def prepared(action, system):
    installing = action == 'install'
    with ExitStack() as stack:
        tx = Transaction(Files(stack, installing, system))
        success = False
        try:
            adopt = plan(tx, system, installing)
            yield adopt, tx.apply
            success = True
        finally:
            tx.finish(success)


@contextmanager
def system_worker(action):
    # Only the fixed program layout is handled with elevated privileges.
    command = [sys.executable, '-I', str(Path(__file__).resolve()), action, 'system']
    if os.geteuid() != 0:
        command.insert(0, 'sudo')
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as worker:
        try:
            ready = worker.stdout.readline()
            if not ready:
                raise Conflict('Program preflight failed. See the preceding error.')
            def commit():
                worker.stdin.write('commit\n')
                worker.stdin.flush()
                if worker.wait() != 0:
                    raise Conflict('Program transaction failed. Restoring desktop entries.')
            yield json.loads(ready), commit
        finally:
            worker.stdin.close()  # EOF before commit cancels the staged transaction


def protect_commit(stack):
    # Both scopes must finish applying or rolling back before a normal termination.
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous = signal.signal(sig, signal.SIG_IGN)
        stack.callback(signal.signal, sig, previous)


def operate(action, system=False):
    with ExitStack() as signals, prepared(action, system) as (adopt, apply):
        if system:
            print(json.dumps(adopt), flush=True)
            if sys.stdin.readline() == 'commit\n':
                protect_commit(signals)
                apply()
            return
        with system_worker(action) as (programs, commit):
            if programs:
                note('No program manifest. Confirm ALL these files belong to your earlier fun installation:')
                for path in programs:
                    note(f'  {path}')
                note('Type ADOPT to claim these files and back up replaced versions:')
                if sys.stdin.readline().strip() != 'ADOPT':
                    raise Conflict('Legacy adoption declined. Existing files preserved.')
            protect_commit(signals)
            apply()
            commit()


def validate_sources():
    for name in SOURCES:
        path = ROOT / name
        if name in ('fun', 'fun_app/legacy_savers.sh'):
            subprocess.run(['/bin/bash', '-n', path], check=True)
        else:
            compile(path.read_bytes(), str(path), 'exec')


if __name__ == '__main__':
    try:
        action, *args = sys.argv[1:]
        if action == 'validate' and not args:
            validate_sources()
            sys.exit(0)
        if action not in ('install', 'uninstall') or args not in ([], ['system']):
            raise ValueError('invalid installer arguments')
        operate(action, bool(args))
    except (ValueError, OSError, RecursionError, SyntaxError, subprocess.CalledProcessError) as exc:
        sys.exit(f'fun setup: {exc}')
