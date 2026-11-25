"""Exercise GTK controls on a real display using disposable preferences."""
import os
from pathlib import Path
import runpy
import sys
import tempfile
import tomllib

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk


def widgets(root):
    yield root
    child = root.get_first_child()
    while child:
        yield from widgets(child)
        child = child.get_next_sibling()


def exercise(window, config):
    assert window.get_mapped(), 'Settings window did not map'
    controls = list(widgets(window))
    rows = [w for w in controls if isinstance(w, Gtk.CheckButton)]
    assert len(rows) == 41, 'Incorrect scene count'
    search = next(w for w in controls if isinstance(w, Gtk.SearchEntry))
    search.set_text('koi')
    search.emit('search-changed')
    assert [w.get_label() for w in rows if w.get_parent().get_visible()] == ['Koi']
    buttons = {w.get_label(): w for w in controls if isinstance(w, Gtk.Button)}
    buttons['Deselect All'].emit('clicked')
    assert not buttons['Save / Apply'].get_sensitive(), 'Empty selection was accepted'
    next(w for w in rows if w.get_label() == 'Koi').set_active(True)
    buttons['Save / Apply'].emit('clicked')
    data = tomllib.loads(config.read_text())
    assert data['scenes'] == ['koi'] and not data['idle_enabled']
    assert (data['minutes'], data['idle_minutes']) == (1.5, 5.25), 'Interval rounded on save'


def main():
    if os.getuid() == 0 or sys.flags.optimize:
        sys.exit('FAIL run GUI verification as a normal user with assertions enabled')
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(XDG_CONFIG_HOME=tmp, XDG_CACHE_HOME=tmp)
        config = Path(tmp) / 'fun/settings.toml'
        config.parent.mkdir()
        config.write_text('minutes = 1.5\nidle_minutes = 5.25\nidle_enabled = false\n')
        script = Path(__file__).resolve().parents[1] / 'fun-config'
        app = runpy.run_path(str(script))
        result = []

        def inspect():
            instance = Gio.Application.get_default()
            window = instance.get_active_window() if instance else None
            if window is None or not window.get_mapped():
                return True
            try:
                exercise(window, config)
            except Exception as exc:
                result.append(exc)
            else:
                result.append(None)
            instance.quit()
            return False

        GLib.timeout_add(250, inspect)
        status = app['main']()
        if status or not result:
            sys.exit('FAIL could not exercise the settings window')
        if result[0] is not None:
            raise result[0]
        print('PASS mapped GTK window, scene search, selection and saved fractional settings')


if __name__ == '__main__':
    main()
