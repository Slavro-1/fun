"""Shared, GTK-free settings for fun and fun-idle."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import tomllib

DEFAULTS = dict(minutes=10, quality='ultra', order='random', idle_enabled=True,
                idle_minutes=13, charging_only=True, scenes=[])
QUALITY = {'auto', 'low', 'medium', 'high', 'ultra'}
ORDER = {'random', 'sequential'}
FILE = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'fun' / 'settings.toml'
RETIRED_SCENES = {'synthwave', 'cumulus', 'pulsar', 'plasma-lite'}


def validate(data, active=None):
    if not isinstance(data, dict):
        raise ValueError('settings must be a TOML table')
    result = DEFAULTS.copy()
    result.update(data)
    for key in result:
        if key not in DEFAULTS:
            raise ValueError('unknown setting: ' + key)
    for key in ('minutes', 'idle_minutes'):
        value = result[key]
        if type(value) not in (int, float) or not 1 <= value <= 1440:
            raise ValueError(f'{key} must be between 1 and 1440')
    if not isinstance(result['quality'], str) or result['quality'] not in QUALITY:
        raise ValueError('invalid quality')
    if not isinstance(result['order'], str) or result['order'] not in ORDER:
        raise ValueError('invalid order')
    for key in ('idle_enabled', 'charging_only'):
        if type(result[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    scenes = result['scenes']
    if not isinstance(scenes, list) or any(not isinstance(s, str) for s in scenes) or len(set(scenes)) != len(scenes):
        raise ValueError('scenes must be a list of unique names')
    if active is not None and scenes and not set(scenes) <= set(active):
        raise ValueError('scenes contains an inactive name')
    if data.get('scenes') == []:
        raise ValueError('at least one scene must be enabled')
    return result


def load(active=None):
    result = dict(DEFAULTS, scenes=[])
    try:
        with FILE.open('rb') as stream:
            data = tomllib.load(stream)
    except FileNotFoundError:
        return result
    except (OSError, ValueError, RecursionError) as exc:
        print(f'fun: ignoring invalid settings ({exc})', file=sys.stderr)
        return result
    for key, value in data.items():
        try:
            validate({key: value})
            if key == 'scenes':
                value = [s for s in value if s not in RETIRED_SCENES]
                if active is not None:
                    inactive = [s for s in value if s not in active]
                    if inactive:
                        print(f'fun: ignoring inactive scenes: {inactive!r}', file=sys.stderr)
                    value = [s for s in value if s in active]
                if not value:
                    raise ValueError('no active scenes remain')
            result[key] = value
        except ValueError as exc:
            print(f'fun: ignoring setting {key!r} ({exc}); using default', file=sys.stderr)
    return result


def save(data, active):
    data = validate(data, active)
    if not data['scenes']:
        raise ValueError('at least one scene must be enabled')
    lines = [f'minutes = {data["minutes"]}', f'quality = "{data["quality"]}"',
             f'order = "{data["order"]}"',
             f'idle_enabled = {str(data["idle_enabled"]).lower()}',
             f'idle_minutes = {data["idle_minutes"]}',
             f'charging_only = {str(data["charging_only"]).lower()}',
             'scenes = [' + ', '.join('"' + s + '"' for s in data['scenes']) + ']']
    FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.settings-', dir=FILE.parent, text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def shell(scope):
    active = None
    if scope == 'launcher':
        engine = Path(__file__).with_name('extras.py')
        if engine.is_file():
            try:
                active = subprocess.run([sys.executable, str(engine), '--list'],
                                        capture_output=True, text=True, check=True).stdout.splitlines()
            except (OSError, subprocess.SubprocessError):
                pass
    data = load(active)
    mapping = ({'FUN_MINUTES': data['minutes'], 'FUN_RES': {'medium': 'med', 'auto': 'ultra'}.get(data['quality'], data['quality']),
                'FUN_ORDER': data['order'], 'FUN_SCENES': ','.join(data['scenes'])} if scope == 'launcher' else
               {'FUN_IDLE_MIN': data['idle_minutes'], 'FUN_IDLE_ENABLED': int(data['idle_enabled']),
                'FUN_IDLE_CHARGING_ONLY': int(data['charging_only'])})
    for key, value in mapping.items():
        print(f'export {key}={shlex.quote(str(os.environ.get(key, value)))}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['shell'])
    parser.add_argument('scope', choices=['launcher', 'idle'])
    args = parser.parse_args()
    shell(args.scope)


if __name__ == '__main__':
    main()
