"""Exercise push barriers without a network, privileged account or real remote."""
from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from scripts import prepush as gate


class GateTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.enterContext(redirect_stdout(io.StringIO()))
        self.branch = 'maintenance/test'
        self.head = 'a' * 40
        self.state = self.branch, self.head, 'b' * 40

    def mock(self, target, attr, **kwargs):
        return self.stack.enter_context(patch.object(target, attr, **kwargs))

    def fixture(self, answer):
        self.enterContext(patch.dict(os.environ))
        self.mock(os, 'chdir')
        self.status = self.mock(gate, 'candidate', return_value=self.state)
        self.mock(gate, 'review_commits')
        self.mock(gate, 'git', return_value='tester@laptop')
        self.mock(gate.subprocess, 'check_output', side_effect=['', b'archive'])
        self.mock(gate, 'unpack')
        self.mock(gate, 'remote_tests')
        self.run = self.mock(gate.subprocess, 'run')
        self.mock(gate, 'open', create=True, side_effect=[io.StringIO(answer), io.StringIO()])

    def test_refuses_root_before_git_or_session(self):
        self.mock(os, 'getuid', return_value=0)
        run = self.mock(gate.subprocess, 'check_output')
        with self.assertRaisesRegex(ValueError, 'normal user'):
            gate.main()
        run.assert_not_called()

    def test_real_shell_entry_refuses_nonroot(self):
        r = subprocess.run([gate.ROOT / 'scripts/final-prepush.sh'], capture_output=True, text=True,
                           env={'SUDO_UID': str(os.getuid()), 'SUDO_USER': 'nobody'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('FAIL', r.stderr)

    def test_sudo_dispatch_and_mismatched_audit_login(self):
        # Replace OS boundaries in a private copy. The test never requests sudo.
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / 'id').write_text('#!/bin/sh\nif [ "$#" = 1 ]; then echo 0; else echo 1234; fi\n')
        (root / 'sudo').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        for name in ('id', 'sudo'):
            (root / name).chmod(0o755)
        wrapper = root / 'final-prepush.sh'
        source = (gate.ROOT / 'scripts/final-prepush.sh').read_text()
        for old, new in [('/usr/bin/id', root / 'id'), ('/usr/bin/sudo', root / 'sudo'),
                         ('/proc/self/loginuid', root / 'loginuid')]:
            source = source.replace(old, str(new))
        wrapper.write_text(source)
        wrapper.chmod(0o755)
        env = {'SUDO_USER': 'example', 'SUDO_UID': '1234'}
        for login in ('0', '1235', '4294967295'):
            (root / 'loginuid').write_text(login)
            result = subprocess.run([wrapper], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(result.stdout)
        (root / 'loginuid').write_text('1234')
        args = subprocess.check_output([wrapper], env=env, text=True).splitlines()
        self.assertEqual(args[:6], ['-H', '-u', '#1234', '--', '/usr/bin/env', '-i'])
        self.assertEqual(args[-3:], ['/usr/bin/python3', '-I', str(root / 'prepush.py')])

    def test_no_push_after_failed_desktop(self):
        self.fixture('yes')
        self.run.side_effect = subprocess.CalledProcessError(1, 'desktop')
        with self.assertRaises(subprocess.CalledProcessError):
            gate.main()
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.run.call_args.args[0][0], 'systemd-run')

    def test_no_push_on_decline(self):
        self.fixture('yes')
        gate.main()
        self.assertEqual(self.run.call_count, 1)

    def test_no_push_after_commit_changes(self):
        self.fixture(f'PUSH {self.branch} {self.head}\n')
        self.status.side_effect = [self.state, self.state, (self.branch, 'changed', self.state[2])]
        with self.assertRaisesRegex(ValueError, 'changed'):
            gate.main()
        self.assertEqual(self.run.call_count, 1)

    def test_only_exact_confirmed_refspec(self):
        self.fixture(f'PUSH {self.branch} {self.head}\n')
        gate.main()
        command = self.run.call_args.args[0]
        self.assertIn('push', command)
        self.assertIn('--no-follow-tags', command)
        self.assertEqual(command[-2:], [gate.URL, self.head + ':refs/heads/' + self.branch])

    def test_secret_scan_positive_and_negative(self):
        self.assertTrue(gate.SECRET.search(b'ghp_' + b'a' * 36))
        self.assertFalse(gate.SECRET.search(b'git config --local user.name'))
