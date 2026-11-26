"""Headless idle, session policy, process ownership and wire protocol regressions."""
from contextlib import ExitStack, nullcontext
import os
from pathlib import Path
import shlex
import time
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fun_app.idle import runtime, session, watcher as idle, wayland as wl


def packet(obj, op, body=b''):
    return struct.pack('=II', obj, ((len(body) + 8) << 16) | op) + body


def advertised(num, name, version):
    return packet(2, 0, wl.uints(num) + wl.string(name) + wl.uints(version))


class WaylandTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-7', 'XDG_RUNTIME_DIR': '/run/private',
                                                    'XDG_SESSION_TYPE': 'wayland', 'XDG_CURRENT_DESKTOP': 'KDE'}, clear=True))
        self.sock = stack.enter_context(patch.object(wl.socket, 'socket')).return_value
        stack.enter_context(patch.object(wl.select, 'select', return_value=([self.sock], [], [])))

    def handshake(self, version=1):
        registry = advertised(18, 'wl_seat', 9) + advertised(90, 'ext_idle_notifier_v1', version)
        return [registry[:5], registry[5:] + packet(3, 0, wl.uints(0)), packet(7, 0, wl.uints(0))]

    def test_kde_prefers_native_and_negotiates_v1_with_inhibitors(self):
        for version in (1, 2, 5):
            with self.subTest(version=version):
                self.sock.recv.side_effect = self.handshake(version) + [packet(6, 0), packet(6, 1), b'']
                backend = idle.pick_backend(10.25, '3', [])
                self.assertIsInstance(backend, wl.Wayland)
                self.sock.connect.assert_called_with('/run/private/wayland-7')
                sent = [call.args[0] for call in self.sock.sendall.call_args_list]
                self.assertIn(packet(2, 0, wl.uints(90) + wl.string('ext_idle_notifier_v1') + wl.uints(1, 4)), sent)
                self.assertIn(packet(4, 1, wl.uints(6, 10250, 5)), sent)
                self.assertNotIn(packet(4, 2, wl.uints(6, 10250, 5)), sent)
                self.assertEqual(backend.idle(), 0)
                self.assertFalse(backend.pump(0))
                self.assertEqual(backend.idle(), 10.25)
                self.assertTrue(backend.pump(0))
                self.assertEqual(backend.idle(), 0)
                with self.assertRaises(ConnectionError):
                    backend.pump(0)
                backend.close()

    def test_unusable_global_seat_or_connection_never_uses_xwayland(self):
        for globals_ in [advertised(18, 'wl_seat', 1), advertised(90, 'ext_idle_notifier_v1', 0),
                         advertised(90, 'ext_idle_notifier_v1', 1),
                         b''.join(self.handshake()[:2]) + advertised(19, 'wl_seat', 1)]:
            self.sock.recv.side_effect = [globals_ + packet(3, 0, wl.uints(0))]
            with patch.object(idle, 'x11_time', side_effect=AssertionError):
                self.assertIsNone(idle.pick_backend(300, None, []))
            self.sock.close.assert_called()

    def test_seat_removal_invalidates_subscription(self):
        self.sock.recv.side_effect = self.handshake() + [packet(2, 1, wl.uints(18))]
        backend = wl.Wayland(10)
        with self.assertRaisesRegex(OSError, 'removed'):
            backend.pump(0)


class SessionTests(unittest.TestCase):
    def test_session_resolution_without_self_excludes_manager_and_other_seats(self):
        env = {'XDG_SESSION_TYPE': 'wayland', 'XDG_SEAT': 'seat0', 'XDG_SESSION_ID': 'stale'}
        user = dict(User=str(os.getuid()), Type='wayland', Class='user', Remote='no', Seat='seat0')
        rows = {'3': dict(user, Id='3'), '4': dict(user, Id='4', Class='manager'),
                '5': dict(user, Id='5', Seat='seat1')}
        with patch.dict(os.environ, env, clear=True), patch.object(session, 'output', return_value='3 4 5'), \
                patch.object(session, 'properties', side_effect=lambda sid: rows.get(sid, {})):
            self.assertEqual(session.resolve_session(), '3')
            rows['5']['Seat'] = 'seat0'
            self.assertIsNone(session.resolve_session())
            rows.clear()
            self.assertIsNone(session.resolve_session())

    def test_late_display_import_must_match_the_identified_login(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland'}, clear=True), \
                patch.object(session, 'resolve_session', return_value='3'), patch.object(session.time, 'sleep'), \
                patch.object(session, 'output') as output:
            output.return_value = 'XDG_SESSION_ID=4\nXDG_SESSION_TYPE=wayland\nWAYLAND_DISPLAY=wrong'
            session.recover_login_display()
            self.assertNotIn('WAYLAND_DISPLAY', os.environ)
            output.return_value = 'XDG_SESSION_ID=3\nXDG_SESSION_TYPE=wayland\nWAYLAND_DISPLAY=wayland-2'
            session.recover_login_display()
            self.assertEqual(os.environ['WAYLAND_DISPLAY'], 'wayland-2')

    def test_stale_hints_never_arm_and_transitions_use_conservative_delay(self):
        p = {'IdleHint': 'no', 'IdleSinceHintMonotonic': '0'}
        with patch.object(session, 'properties', return_value=p), patch.object(session.time, 'monotonic') as clock:
            clock.return_value = 100
            hint = session.Hint('3')
            clock.return_value = 1000
            hint.sample()
            self.assertEqual(hint.idle(), 0)
            p.update(IdleHint='yes', IdleSinceHintMonotonic='1000000')
            hint.sample()
            self.assertIn('unverified', hint.evidence)
            self.assertEqual(hint.idle(), 0)
            for t, val in [(1001, 'no'), (1003, 'yes')]:
                clock.return_value = t
                p.update(IdleHint=val, IdleSinceHintMonotonic=str(t * 1000000))
                hint.sample()
            clock.return_value = 1008
            hint.sample()
            self.assertEqual(hint.idle(), 5)
            p.update(IdleHint='no', IdleSinceHintMonotonic='1008000000')
            self.assertTrue(hint.sample())
            self.assertEqual(hint.idle(), 0)

    def test_classify_exact_fields_and_include_browser(self):
        rows = [('shutdown:sleep', 'helper', 'idle block', 'block', 1, 99),
                ('handle-lid-switch', 'idle', 'block', 'block', 1, 99),
                ('idle', 'delay', 'delay', 'delay', 1, 99),
                ('sleep:idle', 'Firefox', 'movie', 'block', 1, 99),
                ('idle', 'slides', 'presenting', 'block-weak', 1, 99)]
        self.assertEqual(session.system_inhibitors(rows), ['Firefox', 'slides'])

    def test_lock_policy_and_unavailable_bus_fail_closed(self):
        props = dict(Active='yes', LockedHint='no', State='active')
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE'}), patch.object(session, 'bus') as bus:
            bus.side_effect = [[], False, False]
            self.assertEqual(session.blockers(props), [])
            bus.side_effect = [[], True, None, [], True]
            self.assertEqual(session.blockers(props), ['KDE PowerDevil screen inhibition', 'desktop screen locker active'])
            bus.side_effect = [None, None, None]
            self.assertEqual(len(session.blockers(dict(props, LockedHint='yes'))), 4)

    def test_kde_inhibition_labels_are_diagnostic_only(self):
        props = dict(Active='yes', LockedHint='no', State='active')
        cases = [
            ([{'data': [['sleep', 'backup', 'busy'], ['idle', 'player', 'movie']]}],
             ' (screen requests: player — movie)'),
            ([None, [['AC Screen Lock', 'reason\x1b\n']]], ' (active requests, all types: AC Screen Lock — reason)'),
            ([None, None], ''),
        ]
        for replies, detail in cases:
            with self.subTest(replies=replies), patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE'}), \
                    patch.object(session, 'bus', side_effect=[[], True, *replies, False]):
                self.assertEqual(session.blockers(props), ['KDE PowerDevil screen inhibition' + detail])

    def test_gnome_filters_sleep_only_inhibitor_and_names_idle_app(self):
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'GNOME'}), patch.object(session, 'bus') as bus:
            bus.side_effect = [[], True, ['/a', '/b'], 4, 8, 'Slides', False]
            self.assertEqual(session.blockers(dict(Active='yes', LockedHint='no', State='active')),
                             ['GNOME session idle inhibition (Slides)'])

    def test_gnome_wayland_and_native_x11_counters(self):
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'GNOME'}, clear=True), \
                patch.object(wl.Wayland, '__init__', side_effect=OSError('no global')), \
                patch.object(session, 'bus', side_effect=[6416, 6560, 0]), \
                patch.object(idle.time, 'sleep'):
            os.environ['XDG_SESSION_TYPE'] = 'wayland'
            backend = idle.pick_backend(10, None, [])
            self.assertEqual(backend.name, 'GNOME Mutter')
            self.assertEqual(backend.idle(), 6.560)
            self.assertTrue(backend.pump(0))
            os.environ.update(XDG_SESSION_TYPE='x11', XDG_CURRENT_DESKTOP='KDE')
            with patch.object(session, 'output', side_effect=['416', '612']):
                self.assertEqual(idle.pick_backend(10, None, []).name, 'X11 xprintidle')

    def test_connected_counter_that_freezes_loses_eligibility(self):
        with patch.object(idle.time, 'monotonic', side_effect=[10, 11, 22]), patch.object(idle.time, 'sleep'):
            counter = idle.Counter('fixture', Mock(side_effect=[500, 501, 501]))
            counter.pump(1)
            with self.assertRaisesRegex(OSError, 'stopped changing'):
                counter.pump(10)

    def test_fixed_counter_falls_back_without_claiming_success(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11', 'XDG_CURRENT_DESKTOP': 'GNOME'}, clear=True), \
                patch.object(session, 'bus', return_value=0), patch.object(idle.time, 'sleep'), \
                patch.object(session, 'output', side_effect=['100', '200']):
            notes = []
            self.assertEqual(idle.pick_backend(10, None, notes).name, 'X11 xprintidle')
            self.assertIn('no movement', notes[0])


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.backend = Mock(name='backend')
        self.backend.name = 'fake compositor'
        self.backend.pump.return_value = False
        self.backend.idle.return_value = 0
        self.proc = Mock()
        self.proc.poll.return_value = None
        self.launch = self.mock(idle, 'start_saver', return_value=self.proc)
        self.stop = self.mock(idle, 'stop_saver')
        self.policy = self.mock(idle, 'conditions', return_value=[])
        self.mock(idle, 'refresh_settings')
        self.mock(idle, 'log')
        self.mock(session, 'resolve_session', return_value='3')
        self.mock(session, 'properties', return_value={'State': 'active'})
        self.pick = self.mock(idle, 'pick_backend', return_value=self.backend)
        self.stack.enter_context(patch.multiple(idle, IDLE_MIN=5, IDLE_ENABLED=True, create=True))
        self.rt = Mock()
        self.rt.claim.side_effect = lambda _: nullcontext(object())
        self.rt.holder.return_value = None
        self.w = idle.Watcher(self.rt)
        self.addCleanup(self.w.reset)
        self.clock = self.mock(idle.time, 'monotonic', return_value=1000)

    def mock(self, obj, name, **kwargs):
        return self.stack.enter_context(patch.object(obj, name, **kwargs))

    def test_delay_dismiss_immediately_and_latch_closed_window(self):
        self.backend.idle.return_value = 299.99
        self.w.step()
        self.launch.assert_not_called()
        self.backend.idle.return_value = 300
        self.w.step()
        self.launch.assert_called_once()
        self.proc.poll.return_value = 0
        self.w.step()
        self.w.step()
        self.launch.assert_called_once()
        self.proc.poll.return_value = None
        self.backend.idle.return_value = 0
        self.w.step()
        self.backend.idle.return_value = 300
        self.w.step()
        self.backend.pump.return_value = True
        self.w.step()
        self.assertIsNone(self.w.proc)
        self.assertEqual(self.stop.call_count, 2)

    def test_inhibitor_and_power_recovery(self):
        self.backend.idle.return_value = 300
        self.policy.return_value = ['Firefox']
        self.w.step()
        self.launch.assert_not_called()
        self.policy.return_value = []
        self.w.step()
        self.launch.assert_called_once()
        self.clock.return_value += 2
        self.policy.return_value = ['lid closed']
        self.w.step()
        self.stop.assert_called_once()
        self.policy.return_value = ['charger unplugged']
        self.w.step()
        self.assertIsNone(self.w.proc)
        self.policy.return_value = []
        self.w.step()
        self.assertIs(self.w.proc, self.proc)

    def test_failure_latched_and_disabled_cleanup(self):
        self.backend.idle.return_value = 300
        self.launch.side_effect = FileNotFoundError('kitty')
        self.w.step()
        self.w.step()
        self.assertIn('launch failed', self.w.reason)
        self.launch.assert_called_once()
        self.launch.side_effect = None
        self.w.latched = False
        self.w.step()
        with patch.object(idle, 'IDLE_ENABLED', False):
            self.assertFalse(self.w.step())
        self.w.reset()
        self.stop.assert_called_once_with(self.proc)

    def test_test_uses_same_loop_requires_resume_and_restores_delay(self):
        self.rt.holder.return_value = 'token'
        self.backend.idle.return_value = 10
        self.w.step()
        self.launch.assert_not_called()
        self.clock.return_value += 10
        self.w.step()
        self.assertIn('launched', self.w.result)
        self.backend.pump.return_value = True
        self.backend.idle.return_value = 0
        self.w.step()
        self.assertTrue(self.w.result.startswith('PASS'))
        self.w.step()
        self.assertEqual(self.w.threshold, 300)
        self.assertTrue(self.w.result.startswith('PASS'))

    def test_disconnect_cleans_child_and_session_logout_exits(self):
        self.backend.idle.return_value = 300
        self.w.step()
        self.backend.pump.side_effect = ConnectionError('closed')
        self.w.step()
        self.stop.assert_called_once_with(self.proc)
        self.assertIsNone(self.w.backend)
        self.clock.return_value += 16
        with patch.object(session, 'properties', return_value={'State': 'closing'}):
            self.assertFalse(self.w.step())

    def test_test_does_not_pass_on_an_already_dead_terminal(self):
        self.rt.holder.return_value = 'test'
        self.backend.idle.return_value = 10
        self.w.step()
        self.clock.return_value += 10
        self.w.step()
        self.proc.poll.return_value = 1
        self.proc.returncode = 1
        self.backend.pump.return_value = True
        self.w.step()
        self.assertTrue(self.w.result.startswith('FAIL'))

    def test_fresh_activity_during_policy_query_cancels_launch(self):
        self.backend.idle.return_value = 300
        self.backend.pump.side_effect = [False, True]
        self.w.step()
        self.launch.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def test_live_singleton_and_automatic_unlock_on_death(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_RUNTIME_DIR': tmp}):
            rt = runtime.Runtime('wayland/test')
            code = ("from fun_app.idle.runtime import Runtime; import time; rt=Runtime('wayland/test'); "
                    "lock=rt.claim('watcher'); lock.__enter__(); print('ready',flush=True); time.sleep(10)")
            with subprocess.Popen([sys.executable, '-c', code], cwd=ROOT, stdout=subprocess.PIPE) as proc:
                try:
                    self.assertEqual(proc.stdout.readline(), b'ready\n')
                    with rt.claim('watcher') as lock:
                        self.assertIsNone(lock)
                finally:
                    proc.kill()
            with rt.claim('watcher') as lock:
                self.assertIsNotNone(lock)

    def test_terminal_group_cleanup_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp, 'ready')
            child = f"trap 'echo stopped > {tmp}/stopped; exit' TERM; touch {marker}; while :; do sleep 1; done"
            # Explicit argv through a foreground shell, with its child surviving the leader.
            env = {'FUN_TERMINAL': shlex.join(['sh', '-c', shlex.join(['sh', '-c', child]) + ' &'])}
            with patch.dict(os.environ, env), patch.object(idle, 'CACHE', tmp), patch.object(idle, 'log'):
                proc = idle.start_saver()
                try:
                    self.assertEqual(proc.wait(timeout=2), 0)
                    for _ in range(100):
                        if marker.exists():
                            break
                        time.sleep(.01)
                    self.assertTrue(marker.exists())
                finally:
                    idle.stop_saver(proc)
                self.assertTrue(Path(tmp, 'stopped').is_file())

    def test_autostart_obeys_setting_and_scopes_restart_to_login(self):
        rt = Mock(unit='fun-idle-test')
        rt.holder.return_value = None
        with patch.object(idle, 'IDLE_ENABLED', False, create=True), patch.object(idle.subprocess, 'run') as run:
            idle.autostart(rt)
            run.assert_not_called()
        with patch.object(idle, 'IDLE_ENABLED', True, create=True), patch.object(session, 'output', return_value='active'), \
                patch.object(idle.subprocess, 'run') as run, patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-7'}, clear=True):
            run.return_value.returncode = 0
            self.assertEqual(idle.autostart(rt), 0)
            cmd = run.call_args.args[0]
            for arg in ('PartOf=graphical-session.target', 'StartLimitBurst=3', '--setenv=WAYLAND_DISPLAY=wayland-7'):
                self.assertIn(arg, cmd)
            unset = next(arg for arg in cmd if arg.startswith('UnsetEnvironment='))
            self.assertIn('XDG_CACHE_HOME', unset.partition('=')[2].split())
            self.assertNotIn('--setenv=XDG_CACHE_HOME=', cmd)
            rt.holder.return_value = '123'
            idle.autostart(rt)
            run.assert_called_once()

    def test_unsupervised_login_retries_crashes_with_a_bound(self):
        rt = Mock()
        rt.holder.return_value = None
        with patch.object(idle, 'IDLE_ENABLED', True, create=True), patch.object(session, 'output', return_value=None), \
                patch.object(idle, 'watch', side_effect=RuntimeError('fixture crash')) as watch, \
                patch.object(idle.time, 'sleep') as sleep, patch.object(idle, 'log'):
            with self.assertRaisesRegex(RuntimeError, 'fixture crash'):
                idle.autostart(rt)
            self.assertEqual(watch.call_count, 3)
            self.assertEqual([c.args for c in sleep.call_args_list], [(5,), (5,)])

    def test_actual_power_files_and_setting_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            supply = Path(tmp)
            (supply / 'type').write_text('Mains')
            (supply / 'online').write_text('0')
            lid = supply / 'lid'
            lid.write_text('state: closed')
            with patch.object(idle.glob, 'glob', side_effect=lambda s: [str(lid)] if 'acpi' in s else [tmp]):
                self.assertFalse(idle.lid_open())
                self.assertFalse(idle.on_ac())
                (supply / 'online').write_text('1')
                self.assertTrue(idle.on_ac())
            cfg = supply / 'settings.toml'
            with patch.object(idle._settings, 'FILE', cfg), patch.object(idle, '_config_stamp', None), \
                    patch.dict(os.environ, {'FUN_IDLE_MIN': '7'}, clear=True):
                data = dict(idle._settings.DEFAULTS, scenes=['koi'], idle_minutes=5, idle_enabled=False, charging_only=False)
                idle._settings.save(data, ['koi'])
                idle.refresh_settings()
                self.assertEqual((idle.IDLE_MIN, idle.IDLE_ENABLED, idle.CHARGING_ONLY), (7, False, False))
                self.assertEqual(idle._settings.load(), data)


if __name__ == '__main__':
    unittest.main()
