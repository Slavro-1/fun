"""Verify the exact tree on both desktops, then offer one explicit branch push."""
import io
import os
from pathlib import Path
import pwd
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = 'Slavro-1 <Slavro-1@users.noreply.github.com>'
URL = 'https://github.com/Slavro-1/fun.git'
SSH = ['ssh', '-oBatchMode=yes', '-oStrictHostKeyChecking=yes', '-oConnectTimeout=8',
       '-oForwardAgent=no', '-oClearAllForwardings=yes']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def candidate():
    require(Path(git('rev-parse', '--show-toplevel')) == ROOT, 'Unexpected repository')
    require(not git('status', '--porcelain=v1', '--untracked-files=all'), 'Dirty checkout')
    branch = git('symbolic-ref', '--short', 'HEAD')
    require(branch not in ('main', 'master'), 'Select a maintenance branch')
    require(git('remote', 'get-url', '--all', 'origin') == URL and
            git('remote', 'get-url', '--push', '--all', 'origin') == URL, 'Unexpected origin')
    main = git('ls-remote', '--exit-code', 'origin', 'refs/heads/main').split()[0]
    require(main == git('rev-parse', 'origin/main'), 'Fetch and review the updated main')
    git('merge-base', '--is-ancestor', main, 'HEAD')
    head = git('rev-parse', 'HEAD')
    require(head != main, 'Empty maintenance branch')
    return branch, head, main


# Scan all blobs in the candidate and each outgoing commit, including intermediate
# files removed before HEAD. Report paths only. Never echo matching secret bytes.
SECRET = re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----|'
                    rb'(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{30,}|'
                    rb'(?:AKIA|ASIA)[A-Z0-9]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}|'
                    rb'(?i:(?:password|api[_-]?key|access[_-]?token|client[_-]?secret)'
                    rb'\s*[:=]\s*["\'][^"\'\s]{12,}["\'])')


def review_commits(main, head):
    seen = set()
    for commit in git('rev-list', main + '..' + head).splitlines():
        meta = git('show', '-s', '--format=%an <%ae>%n%cn <%ce>%n%B', commit).splitlines()
        require(meta[:2] == [IDENTITY, IDENTITY], 'Wrong commit identity on ' + commit)
        require(not any(re.match(r'(?i)(?:co-authored-by:.*(?:ai|codex|openai)|generated .*with .*codex)', line)
                        for line in meta[2:]), 'Unexpected attribution on ' + commit)
        tree = subprocess.check_output(['git', 'ls-tree', '-rz', commit], cwd=ROOT)
        for entry in tree.split(b'\0')[:-1]:
            header, rawname = entry.split(b'\t', 1)
            mode, kind, oid = header.split()
            name = os.fsdecode(rawname)
            require(mode in (b'100644', b'100755') and kind == b'blob', f'Review special entry {name!r}')
            path = Path(name)
            require(not ({'.aws', '.ssh', '.codex', '__pycache__', 'work', 'outputs', 'previews'} & set(path.parts))
                    and not (path.name.startswith('.env') or path.suffix in ('.pem', '.key', '.pyc')
                             or '.bak-' in path.name or path.name in ('id_rsa', 'id_ed25519')),
                    f'Sensitive or generated tracked path {name!r}')
            if oid not in seen:
                blob = subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=ROOT)
                require(not SECRET.search(blob), f'Possible tracked secret in {name!r} at {commit[:12]}')
                seen.add(oid)
    git('diff', '--check', main, head)
    print(git('diff', '--name-status', main, head), flush=True)


# Only the user creates and reads the private candidate directories.
def desktop(root, kind):
    return ['systemd-run', '--user', '--wait', '--collect', '--quiet', '--pty',
            '/usr/bin/python3', '-I', str(Path(root) / 'scripts/verify_desktop.py'), kind]


def unpack(archive, directory):
    with tarfile.open(fileobj=archive, mode='r|') as tar:
        for member in tar:
            require(member.isfile() or member.isdir(), 'Unexpected type in commit archive')
            tar.extract(member, directory, filter='data')


def remote_tests(host, archive):
    def remote(code, *args, **kwargs):
        command = shlex.join(['/usr/bin/python3', '-I', '-c', code, *args])
        return subprocess.run([*SSH, host, command], check=True, **kwargs)

    create = """import os, tempfile
if not os.getuid() or os.getuid() != os.geteuid(): raise SystemExit('FAIL SSH account must be unprivileged')
path = tempfile.mkdtemp(dir='/tmp', prefix='fun-verify-')
print(path, os.lstat(path).st_ino)"""
    directory, inode = remote(create, capture_output=True, text=True).stdout.strip().split()
    require(re.fullmatch(r'/tmp/fun-verify-[a-zA-Z0-9_]+', directory) and inode.isdecimal(),
            'Unexpected remote candidate path')
    guard = """import os, sys, stat
path, ino = sys.argv[1:]
st = os.lstat(path)
if not (os.getuid() == os.geteuid() != 0 and st.st_uid == os.getuid()
        and st.st_ino == int(ino) and st.st_mode == stat.S_IFDIR | 0o700):
    raise SystemExit('FAIL remote candidate directory identity changed')
"""
    try:
        remote(guard + """import tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as src:
    for member in src:
        if not (member.isdir() or member.isfile()): raise SystemExit('FAIL special archive entry')
        src.extract(member, path, filter='data')""", directory, inode, input=archive)
        subprocess.run([*SSH, '-t', host, shlex.join(desktop(directory, 'wayland'))], check=True)
    finally:
        # Only remove our own mkdtemp directory, after rechecking its identity.
        remote(guard + 'import shutil; shutil.rmtree(path)', directory, inode)


def main():
    uid = os.getuid()
    require(uid != 0 and uid == os.geteuid(), 'Verifier must run as the normal user')
    user = pwd.getpwuid(uid)
    os.environ.update(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name, GIT_NO_REPLACE_OBJECTS='1')
    os.chdir(ROOT)
    # Recover the caller's agent and normal executable search path from the
    # desktop manager. Never source shell output.
    env = subprocess.check_output(['systemctl', '--user', 'show-environment'], text=True)
    for line in env.splitlines():
        key, _, value = line.partition('=')
        if key in ('PATH', 'SSH_AUTH_SOCK') and value:
            os.environ[key] = value
    branch, head, base = candidate()
    review_commits(base, head)
    print('PASS Git state, outgoing identities, changed paths and secret-pattern scan', flush=True)
    host = git('config', '--local', '--get', 'fun.verifyHost')
    require(re.fullmatch(r'[a-z_][a-z0-9_-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*', host),
            'Set repository-local fun.verifyHost to the Debian user@host')
    archive = subprocess.check_output(['git', 'archive', head], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='fun-verify-') as local:
        unpack(io.BytesIO(archive), local)
        subprocess.run(desktop(local, 'x11'), check=True)
    remote_tests(host, archive)
    require(candidate() == (branch, head, base), 'Candidate or upstream changed during verification')
    with open('/dev/tty') as reader, open('/dev/tty', 'w') as writer:
        prompt = 'PUSH ' + branch + ' ' + head
        print(f'PASS both desktops. Destination {URL}\nBranch {branch}\nCommit {head}\nType {prompt} to push:', file=writer, flush=True)
        if reader.readline().rstrip('\n') != prompt:
            print('SKIPPED push. Confirmation declined.')
            return
    require(candidate() == (branch, head, base), 'Candidate changed after confirmation')
    # Explicit SHA/refspec, one destination, no tags, force, mirror or submodules.
    subprocess.run(['git', '-c', 'push.followTags=false', '-c', 'push.recurseSubmodules=no',
                    'push', '--no-follow-tags', URL, head + ':refs/heads/' + branch], check=True)
    print('PASS branch pushed')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        sys.exit(f'FAIL {exc}\nSKIPPED remaining checks and any pending push.')
