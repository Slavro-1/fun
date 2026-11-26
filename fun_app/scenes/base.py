"""Shared scene and episode lifecycle."""
import random


class Scene:
    fps = 15
    text = False
    mask = 0xFFFFFF        # colour quantisation applied by the half-block encoder
    S = 1.0                 # physical pixel scale for scene details
    gfx = False
    gfx_reference = None    # prior medium grid for resolution-independent seeded detail
    gfx_pixels = 85_000     # prior medium ceiling used for the detail grid
    gfx_fps = 22
    gfx_dither = False

    def __init__(self, W, H, *, scale=1.0, gfx=False):
        self.W = W
        self.H = H
        self.S = scale
        self.gfx = gfx
        self.rng = random.Random()
        self.setup()

    def px(self, value):
        return max(1, round(self.S * value))

    @property
    def logical_area(self):
        if self.gfx_reference:
            w, h = self.gfx_reference
            logical_h = self.H / self.S
            return w / h * logical_h * logical_h
        return self.W * self.H / (self.S * self.S)

    @property
    def detail_scale(self):
        return self.H / self.gfx_reference[1] if self.gfx_reference else 1.

    def detail_coord(self, stop, vertical=False, reference_stop=None):
        if self.gfx_reference is None:
            return self.rng.randrange(stop)
        axis = int(vertical)
        size = self.H if vertical else self.W
        reference = self.gfx_reference[axis]
        limit = reference_stop if reference_stop is not None else max(1, round(stop*reference/size))
        return min(stop-1, int(self.rng.randrange(limit)*size/reference))

    def setup(self):
        pass

    def frame(self, t, dt):
        raise NotImplementedError


class Episode:
    """Time-addressable seeded story with a short dark seam between episodes."""

    def __init__(self, rng, stages, fade=2.0):
        self.seed = rng.getrandbits(64)
        self.stages = tuple(stages)  # (name, start, duration)
        self.length = max(start + duration for _, start, duration in stages)
        self.fade = fade

    def clock(self, t):
        span = self.length + self.fade
        number = max(0, int(t // span))
        local = max(0., t - number * span)
        opacity = max(0., 1. - max(0., local - self.length) / self.fade)
        return number, min(local, self.length), opacity

    def rng(self, number):
        return random.Random((self.seed + number * 0x9E3779B97F4A7C15) & ((1 << 64) - 1))

    def stage(self, t):
        _, local, _ = self.clock(t)
        for i in range(len(self.stages) - 1, -1, -1):
            _, start, duration = self.stages[i]
            if local >= start:
                return i, min(1., max(0., (local - start) / duration))
        return 0, 0.


def make_scene(cls, cols, rows):
    if cls.text:
        return cls(cols, rows)
    return cls(cols, rows * 2)
