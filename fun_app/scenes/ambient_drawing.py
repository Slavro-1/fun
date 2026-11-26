"""Drawing helpers for ambient and cinematic scenes."""
from functools import lru_cache

from .drawing import fill_row, gradient, shade, sqrt, up2


def _ambient_scale(W, H, pixel_scale=1.0):
    return min(W / 118, H / 98, 1.4 * pixel_scale)


def _ambient_palette(stops, count=256):
    return gradient([(p, (c >> 16, c >> 8 & 255, c & 255)) for p, c in stops], count)


def _ambient_disc(buf, W, H, x, y, radius, color):
    x, y = round(x), round(y)
    rr = radius * radius
    for dy in range(max(-radius, -y), min(radius + 1, H - y)):
        dx = int(sqrt(rr - dy * dy))
        fill_row(buf, W, y + dy, max(0, x - dx), min(W, x + dx + 1), color)


def _ambient_stars(buf, W, H, rng, count, ceiling):
    for _ in range(count):
        c = shade(rng.choice((0x9CB9FF, 0xFFD9AA, 0xCCD6EE)), rng.randrange(22, 114))
        buf[rng.randrange(ceiling) * W + rng.randrange(W)] = c


def _ambient_grid(W, H, step):
    return (W + step - 1) // step, (H + step - 1) // step


def _ambient_expand(field, W, H, sw, step, pal):
    """Expand a regularly sampled field using nearest-neighbour cells."""
    if step == 2:
        out = []
        for i in range(0, len(field), sw):
            colors = list(map(pal.__getitem__, field[i:i + sw]))
            row = [0] * (2 * sw)
            row[::2] = row[1::2] = colors
            row = row[:W]
            out.extend(row)
            out.extend(row)
        return out[:W * H]
    out = []
    for i in range(0, len(field), sw):
        row = [c for k in field[i:i + sw] for c in (pal[k],) * step][:W]
        out.extend(row * step)
    return out[:W * H]


@lru_cache(maxsize=3)
def _field_blends(step):
    """Weights for integer palette indices between adjacent field samples."""
    return tuple(tuple(bytes((a*(step-phase)+b*phase)//step for b in range(256))
                       for a in range(256))
                 for phase in range(1,step))


class _FieldGrid:
    """Keep smooth field work bounded and interpolate before drawing details."""

    def __init__(self, width, height, limit):
        self.W, self.H = width, height
        self.step = max(2, round(sqrt(width*height/limit)))
        self.sw, self.sh = _ambient_grid(width, height, self.step)
        self.blends = _field_blends(self.step) if self.step > 2 else ()

    def expand(self, indices, palette):
        if self.step == 2:
            return up2(indices, self.sw, self.sh, self.W, self.H, palette)

        sw, step = self.sw, self.step
        rows = [indices[i:i+sw] for i in range(0, len(indices), sw)]
        rows.append(rows[-1])
        output = []
        for y in range(self.H):
            iy, phase = divmod(y, step)
            samples = rows[iy]
            if phase:
                blend = self.blends[phase-1]
                samples = [blend[a][b] for a,b in zip(samples,rows[iy+1])]
            right = samples[1:]+samples[-1:]
            row = [0]*(sw*step)
            row[::step] = map(palette.__getitem__, samples)
            for phase, blend in enumerate(self.blends, 1):
                row[phase::step] = [palette[blend[a][b]] for a,b in zip(samples,right)]
            output.extend(row[:self.W])
        return output


def _ambient_smooth(v):
    v = max(0., min(1., v))
    return v * v * (3 - 2 * v)
