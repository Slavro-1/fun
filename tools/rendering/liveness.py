"""Check scene animation, buffer integrity and resident memory on Linux."""

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import extras


def rss_kib():
    with open('/proc/self/status', encoding='ascii') as status:
        return next(int(row.split()[1]) for row in status if row.startswith('VmRSS:'))


def scene_for(name):
    cls = extras.SCENES[name]
    scene = cls.__new__(cls)
    scene.W, scene.H = 118, 98
    scene.rng = extras.random.Random(41209)
    scene.setup()
    return scene


def verify(name):
    scene = scene_for(name)
    first = tenth = None
    for i in range(150):
        dt = .1 if i <= 100 else min(.1, 1 / scene.fps)
        t = i / 10 if i <= 100 else 10 + (i - 100) * dt
        frame = scene.frame(t, dt)
        assert len(frame) == 118 * 98, f'{name}: incorrect buffer length'
        assert all(type(c) is int and 0 <= c <= 0xFFFFFF for c in frame), f'{name}: invalid color'
        assert min(frame) != max(frame), f'{name}: uniform frame at {t:.2f}s'
        luminance = sum(.2126 * (c >> 16) + .7152 * (c >> 8 & 255) + .0722 * (c & 255)
                        for c in frame) / len(frame)
        assert 1 < luminance < 242, f'{name}: mean luminance {luminance:.2f} at {t:.2f}s'
        if i == 0:
            first = [c & scene.mask for c in frame]
        if i == 100:
            tenth = [c & scene.mask for c in frame]
    changed = sum(a != b for a, b in zip(first, tenth)) / len(first)
    assert changed >= .008, f'{name}: only {changed:.2%} of visible pixels changed in 10s'

    scene = scene_for(name)
    encoder = extras.Encoder()
    dt = 1 / scene.fps
    baseline = peak = rss_kib()
    for i in range(3000):
        frame = scene.frame(i * dt, min(.1, dt))
        encoder.blocks(frame, 118, 49, scene.mask)
        if i % 25 == 0:
            peak = max(peak, rss_kib())
    growth = max(peak, rss_kib()) - baseline
    assert growth < 6144, f'{name}: peak RSS grew {growth} KiB'
    print(f'{name:14} {changed:7.2%} pixels changed, {growth:4d} KiB peak RSS growth', flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--one':
        verify(sys.argv[2])
    else:
        if len(sys.argv) == 1:
            sys.exit('usage: python3 tools/rendering/liveness.py SCENE [SCENE ...]')
        outcomes = [subprocess.run([sys.executable, __file__, '--one', name]).returncode for name in sys.argv[1:]]
        sys.exit(any(outcomes))
