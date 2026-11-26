"""The original terminal scenes."""
import math

from .ambient_drawing import _ambient_disc, _ambient_grid, _ambient_palette, _ambient_smooth
from .base import Scene
from .drawing import (
    PI,
    SIN256,
    TAU,
    _gfx_line_add,
    _gfx_line_set,
    _gfx_point_rim,
    addp,
    atan2,
    clamp8,
    cos,
    exp,
    fill_row,
    gradient,
    hypot,
    line_add,
    line_set,
    make_sprite,
    mix,
    plot,
    plota,
    rgb,
    shade,
    sin,
    sqrt,
    stamp,
    up2,
    vgrad,
)


# ------------------------------------------------------------------- aurora
class Aurora(Scene):
    """Layered curtains of northern lights over snowy mountains."""
    fps = 9
    mask = 0xF8F8F8
    gfx_fps = 20
    gfx_pixels = 69000
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.Lmax = L = max(12, int(H * 0.40))
        bg = vgrad(W, H, [(0.0, (3, 4, 16)), (0.45, (6, 10, 34)), (0.75, (9, 24, 50)), (1.0, (16, 40, 66))])
        ph = [rng.uniform(0, 6.3) for _ in range(8)]
        far_c = rgb(9, 17, 36)
        rim_c = rgb(34, 58, 92)
        near_c = rgb(2, 4, 8)
        ridge2 = []
        for x in range(W):
            u = x / W
            ry = int(H * 0.85 - H * (0.05 * sin(u * 9 + ph[0]) + 0.03 * sin(u * 23 + ph[1]) + 0.012 * sin(u * 61 + ph[2])))
            ry = max(0, min(H - 1, ry))
            bg[ry * W + x::W] = [far_c] * (H - ry)
            bg[ry * W + x] = rim_c
        sample_w, sample_h = self.gfx_reference or (W,H)
        edge = [rng.random()*2.4 if x%2 == 0 else 0 for x in range(sample_w)]
        for x in range(W):
            u = x / W
            ry = H * 0.94 - H * (0.03 * sin(u * 14 + ph[3]) + 0.015 * sin(u * 40 + ph[4]))
            ry = int(ry - edge[x*sample_w//W]*self.detail_scale)
            ry = max(0, min(H - 1, ry))
            ridge2.append(ry)
            bg[ry * W + x::W] = [near_c] * (H - ry)
        cx = int(W * 0.72)           # tiny cabin with a warm window
        cy = ridge2[cx] + self.px(2)
        pane = max(1,round(self.detail_scale))
        for dx, c in ((0, rgb(255, 200, 100)), (1, rgb(255, 190, 90))):
            for xx in range(pane):
                for yy in range(pane):
                    plota(bg, W, H, cx + dx*pane+xx, cy+yy, c)
        for dx, dy in ((-1, 0), (2, 0), (0, -1), (1, -1), (0, 1), (1, 1)):
            plota(bg, W, H, cx + dx, cy + dy, rgb(60, 42, 14))
        self.bg = bg
        starc = [rgb(200, 210, 255), rgb(255, 245, 220), rgb(255, 220, 200)]
        self.stars = [(self.detail_coord(W), self.detail_coord(max(1,int(H*.72)), True, max(1,int(sample_h*.72))), rng.choice(starc),
                       rng.uniform(0, 6.3), rng.uniform(0.6, 2.4)) for _ in range(int(self.logical_area // 110))]
        # curtain ramps: [layer][hue variant][intensity level] -> colours top..bottom
        specs = [  # (centre frac, palettes per hue variant, sway speed)
            (0.40, [[(70, 210, 170), (40, 130, 170), (50, 60, 150)],
                    [(110, 220, 170), (60, 150, 190), (60, 70, 160)],
                    [(60, 200, 200), (30, 120, 190), (40, 60, 160)]], 0.8),
            (0.53, [[(150, 255, 150), (60, 230, 110), (30, 140, 120), (40, 60, 150)],
                    [(200, 255, 130), (90, 240, 100), (40, 160, 110), (40, 70, 150)],
                    [(110, 255, 190), (40, 230, 140), (30, 150, 140), (40, 70, 160)]], 1.0),
            (0.57, [[(255, 110, 190), (190, 60, 220), (70, 50, 170)],
                    [(255, 90, 150), (200, 60, 200), (80, 50, 170)],
                    [(230, 110, 230), (150, 70, 230), (60, 50, 180)]], 1.3),
        ]
        self.layers = []
        for li, (f0, pals, spd) in enumerate(specs):
            ramps = []
            for hue in range(17):
                lower = min(1,hue//8)
                upper = lower+1
                weight = (hue-lower*8)*32
                colors = [mix(rgb(*a),rgb(*b),weight) for a,b in zip(pals[lower],pals[upper])]
                stops = [(i/(len(colors)-1),(c>>16,c>>8&255,c&255)) for i,c in enumerate(colors)]
                base = gradient(stops, L)
                per_q = []
                for q in range(8):
                    lv = (q + 1) / 8.0
                    col = []
                    for d in range(L):             # d = distance above the lower edge
                        edge = min(1.0, (d + self.S) / (3 * self.S))
                        prof = exp(-d / (0.30 * L)) * edge
                        col.append(shade(base[min(L - 1, d * 2)],
                                         int(256 * min(1.0, prof * lv * 1.35))))
                    col.reverse()                  # top -> bottom
                    per_q.append(col)
                ramps.append(per_q)
            self.layers.append((f0, 0.07 if li < 2 else 0.05, 0.04, 0.02,
                                rng.uniform(0, 6.3), rng.uniform(0, 6.3), rng.uniform(0, 6.3),
                                rng.uniform(0, 6.3), rng.uniform(0, 6.3), ramps, rng.uniform(0, 6.3), spd))

    def frame(self, t, dt):
        W, H, L = self.W, self.H, self.Lmax
        buf = self.bg[:]
        bg = self.bg
        hymax = int(H * 0.70)
        t *= .78
        for x in range(W):
            u = x / W
            ymin = H
            ymax = 0
            items = []
            for (f0, a1, a2, a3, p0, p1, p2, p3, pr, ramps, hoff, spd) in self.layers:
                by = H * (f0 + a1 * sin(u * 5.0 + t * 0.31 * spd + p0) + a2 * sin(u * 11.0 - t * 0.47 * spd + p1)
                          + a3 * sin(u * 23.0 + t * 0.8 * spd + p2))
                env = 0.5 + 0.5 * sin(u * 3.2 + t * 0.21 * spd + p3)
                ray = 0.5 + 0.5 * sin(x * 0.42 / self.S + t * 1.3 * spd + pr + 2.6 * sin(x * 0.09 / self.S - t * 0.5))
                inten = min(1.0, (0.25 + 0.95 * env) * (0.45 + 0.55 * ray))
                q = int(inten * 7.99)
                if q <= 0:
                    continue
                n = int(L * (0.3 + 0.7 * inten))
                by = int(by)
                if by > hymax:
                    by = hymax
                y1 = by + 1
                y0 = y1 - n
                hq = round(8+8*sin(u*2.1+t*.045+hoff))
                seg = ramps[hq][q][L - n:]
                if y0 < 0:
                    seg = seg[-y0:]
                    y0 = 0
                if not seg:
                    continue
                items.append((y0, y1, seg))
                if y0 < ymin:
                    ymin = y0
                if y1 > ymax:
                    ymax = y1
            if not items:
                continue
            col = bg[ymin * W + x:ymax * W + x:W]
            for (y0, y1, seg) in items:
                o = y0 - ymin
                n = y1 - y0
                col[o:o + n] = map(addp, col[o:o + n], seg)
            buf[ymin * W + x:ymax * W + x:W] = col
        for (x, y, c, p, s) in self.stars:
            f = int(256 * (.65+.27*sin(t*s*.45+p)))
            plota(buf, W, H, x, y, shade(c, f))
        return buf


# ------------------------------------------------------------------ ripples
class Ripples(Scene):
    """Raindrops on a moonlit pond."""
    fps = 15
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (4, 12, 28)), (0.5, (7, 24, 44)), (1.0, (4, 16, 30))])
        mx = int(W * 0.68)
        self.reflection = []
        for y in range(int(H * 0.08), H, self.px(2)):               # moon-path glitter
            w = self.px(3) + int(y * 0.10)
            for _ in range(2):
                dx = int(rng.gauss(0, w))
                ln = rng.randint(self.px(1), self.px(2) + w // 3)
                c = shade(rgb(190, 215, 235), rng.randint(40, 130))
                for k in range(ln):
                    self.reflection.append((mx+dx+k,y,shade(c,128),rng.random()*TAU))
        for _ in range(max(3, int(W / self.S) // 16)):                    # lily pads
            px, py = rng.randrange(W), rng.randrange(int(H * 0.25), H)
            rx = self.px(rng.randint(3, 6))
            ry = max(1, rx // 2)
            ang = rng.uniform(0, 6.3)
            for yy in range(-ry, ry + 1):
                for xx in range(-rx, rx + 1):
                    if (xx / rx) ** 2 + (yy / ry) ** 2 <= 1.0:
                        if abs((atan2(yy,xx)-ang+PI)%TAU-PI) < .29:
                            continue
                        edge = (xx / rx) ** 2 + (yy / ry) ** 2 > 0.6
                        plot(bg, W, H, px + xx, py + yy, rgb(34, 92, 62) if edge else rgb(18, 62, 42))
            if rng.random() < 0.35:
                plot(bg, W, H, px, py, rgb(255, 160, 195))
                plot(bg, W, H, px + 1, py, rgb(255, 215, 230))
        self.bg = bg
        self.rips = []
        self.acc = 0.0
        self.next = 0.2
        self.ring = [shade(rgb(150, 215, 245), int(256 * i / 31.0)) for i in range(32)]

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        for x,y,c,phase in self.reflection:
            drift = round(self.S*(1+2*y/H)*sin(t*.51+phase+y*.15))
            plota(buf,W,H,x+drift,y,shade(c,int(124+83*sin(t*.87+phase))))
        self.acc += dt
        if self.acc >= self.next and len(self.rips) < 9:
            self.acc = 0.0
            self.next = rng.uniform(0.25, 0.9)
            y = rng.uniform(H * 0.2, H * 0.97)
            s = 0.45 + 0.9 * (y / H)
            self.rips.append([rng.uniform(W * 0.04, W * 0.96), y, 0.0, rng.uniform(3.0, 4.6),
                              H * 0.28 * s * rng.uniform(0.7, 1.15)])
        keep = []
        ring = self.ring
        for rp in self.rips:
            rp[2] += dt
            age = rp[2] / rp[3]
            if age >= 1.0:
                continue
            keep.append(rp)
            x0, y0 = rp[0], rp[1]
            amp = (1.0-age)**1.6 * _ambient_smooth(age/.13)
            rr = rp[4] * age ** 0.7
            if rp[2] < 0.15:                                    # the falling drop
                yy = y0 + self.S*(-14 + rp[2] * 90)
                line_add(buf, W, H, x0, yy - self.px(3), x0, yy, shade(0xABC4D7,int(119*sin(PI*rp[2]/.15))))
            for k, (rf, af) in enumerate(((1.0, 1.0), (0.76, 0.6), (0.54, 0.35))):
                r = rr * rf
                if r < 1.2:
                    continue
                n = int(TAU * r * 0.9) + 8
                a = amp * af
                step = TAU / n
                for i in range(n):
                    ang = i * step
                    lf = 0.55 + 0.45 * cos(ang + 2.2)
                    c = ring[int(31 * min(1.0, a * lf))]
                    xx = int(x0 + r * cos(ang))
                    yy = int(y0 + 0.5 * r * sin(ang))
                    if 0 <= xx < W and 0 <= yy < H:
                        j = yy * W + xx
                        q = buf[j]
                        s = q + c
                        m = (s ^ q ^ c) & 0x1010100
                        if m:
                            s = (s | (m - (m >> 8))) & 0xFFFFFF
                        buf[j] = s
        self.rips = keep
        return buf


# --------------------------------------------------------------- fireflies
class Fireflies(Scene):
    """Summer-night meadow with softly pulsing fireflies."""
    fps = 18
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (6, 8, 26)), (0.5, (14, 22, 44)), (0.78, (14, 34, 40)), (1.0, (6, 16, 14))])
        for _ in range(int(self.logical_area // 400)):
            plot(bg, W, H, rng.randrange(W), rng.randrange(int(H * 0.5)), rgb(150, 160, 200))
        # crescent moon
        mx, my, mr = int(W * 0.14), int(H * 0.17), max(3, int(H * 0.06))
        halo = self.px(6)
        for yy in range(-mr - halo, mr + halo + 1):
            for xx in range(-mr - halo, mr + halo + 1):
                d = sqrt(xx * xx + yy * yy)
                d2 = sqrt((xx - mr * 0.55) ** 2 + (yy + mr * 0.2) ** 2)
                if d < mr and d2 >= mr * 0.92:
                    plot(bg, W, H, mx + xx, my + yy, rgb(250, 240, 200))
                elif mr <= d < mr + halo:
                    plota(bg, W, H, mx + xx, my + yy, shade(rgb(70, 70, 40), int(256 * (1 - (d - mr) / halo) ** 2)))
        for layer, (base, amp, col) in enumerate(((0.62, 0.05, (10, 20, 30)), (0.74, 0.06, (7, 15, 20)))):
            ph = rng.uniform(0, 6.3)
            for x in range(W):
                u = x / W
                ry = int(H * base + H * amp * (sin(u * 11 + ph) * 0.6 + sin(u * 29 + ph * 2) * 0.4)) + rng.randint(0, 1)
                if ry < H:
                    bg[ry * W + x::W] = [rgb(*col)] * (H - ry)
        self.bg = bg
        n = max(30, min(150, int(self.logical_area // 170)))
        self.flies = []
        for i in range(n):
            far = rng.random() < 0.3
            self.flies.append((rng.uniform(0, W), rng.uniform(H * 0.28, H * 0.9),
                               self.S * rng.uniform(3, 12), self.S * rng.uniform(2, 8), rng.uniform(0.15, 0.5), rng.uniform(0.2, 0.7),
                               rng.uniform(0, 6.3), rng.uniform(0, 6.3), rng.uniform(2.4, 6.0), rng.uniform(0, 1),
                               far))
        col = rgb(205, 255, 90)
        self.sp_big = make_sprite(col, self.px(3), 8, 2.2)
        self.sp_small = make_sprite(col, self.px(1), 8, 1.5)
        self.blades = []
        x = 0
        while x < W:
            h = rng.randint(max(2, int(H * 0.05)), max(3, int(H * 0.19)))
            self.blades.append((x, h, rng.uniform(0, 6.3), rng.uniform(0.8, 1.8)))
            x += self.px(rng.choice((1, 1, 2)))
        self.gcols = [rgb(5 + k / (2*self.S), 14 + k/self.S, 11 + k/(2*self.S)) for k in range(max(b[1] for b in self.blades) + 1)]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for (hx, hy, a1, a2, w1, w2, p1, p2, per, ph, far) in self.flies:
            x = hx + a1 * sin(t * w1 + p1) + 0.4 * a1 * sin(t * w1 * 2.7 + p2)
            y = hy + a2 * sin(t * w2 + p2) + 0.4 * a2 * sin(t * w2 * 2.3 + p1)
            s = sin(TAU * (t / per + ph))
            if s <= 0:
                s = 0.04
            e = s * s * s
            lv = min(7, int(e * 7.99))
            xi = int(x % W)
            yi = int(y)
            if far:
                stamp(buf, W, H, xi, yi, self.sp_small[lv])
            else:
                stamp(buf, W, H, xi, yi, self.sp_big[lv])
                if lv >= 5:
                    plota(buf, W, H, xi, yi, rgb(255, 255, 200))
        gc_ = self.gcols
        for (x, h, ph, sp) in self.blades:
            for k in range(h):
                off = int(sin(t * sp + ph + x * 0.05 / self.S) * (3.0*self.S) * (k / h) ** 2)
                xx = x + off
                if 0 <= xx < W:
                    buf[(H - 1 - k) * W + xx] = gc_[k]
        return buf


# --------------------------------------------------------------------- snow
class Snow(Scene):
    """Quiet snowfall over a pine forest, with a pale moon."""
    fps = 20
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (6, 10, 30)), (0.55, (18, 30, 66)), (0.85, (60, 84, 128)), (1.0, (110, 130, 170))])
        sample_w, sample_h = self.gfx_reference or (W,H)
        for _ in range(int(self.logical_area // 140)):
            plot(bg, W, H, self.detail_coord(W), self.detail_coord(max(1,int(H*.55)), True, max(1,int(sample_h*.55))), shade(rgb(190, 200, 235), rng.randint(60, 200)))
        mx, my, mr = int(W * 0.8), int(H * 0.2), max(3, int(H * 0.065))
        for yy in range(-mr * 4, mr * 4 + 1):
            for xx in range(-mr * 4, mr * 4 + 1):
                d = sqrt(xx * xx + yy * yy)
                if d < mr:
                    plot(bg, W, H, mx + xx, my + yy, rgb(245, 245, 225))
                elif d < mr * 4:
                    plota(bg, W, H, mx + xx, my + yy, shade(rgb(60, 70, 110), int(256 * (1 - (d - mr) / (3.0 * mr)) ** 2)))
        for (base, amp, col, rim) in ((0.70, 0.12, (36, 52, 92), (120, 140, 180)),
                                      (0.79, 0.08, (24, 38, 72), (90, 110, 150))):
            ph = [rng.uniform(0, 6.3) for _ in range(3)]
            for x in range(W):
                u = x / W
                ry = int(H * base - H * amp * (0.5 * abs(sin(u * 5 + ph[0])) + 0.3 * abs(sin(u * 13 + ph[1])) + 0.2 * sin(u * 31 + ph[2])))
                ry = max(0, min(H - 1, ry))
                bg[ry * W + x::W] = [rgb(*col)] * (H - ry)
                bg[ry * W + x] = rgb(*rim)
        gy = int(H * 0.86)
        for y in range(gy, H):
            f = (y - gy) / max(1, H - gy)
            fill_row(bg, W, y, 0, W, rgb(205 - 50 * f, 220 - 50 * f, 245 - 40 * f))
        sample_ground = int(sample_h*.86)
        for x in range(sample_w):
            if rng.random() < 0.12:
                y = rng.randrange(sample_ground,sample_h)
                plot(bg, W, H, x*W//sample_w, y*H//sample_h, 0xFFFFFF)
        dark = rgb(7, 16, 28)
        lit = rgb(55, 80, 112)
        ref_scale = self.S/self.detail_scale
        pad, offset = max(1,round(3*ref_scale)), max(1,round(4*ref_scale))
        trees = sorted(((rng.randrange(-pad,sample_w+pad)*W//sample_w,
                         rng.randint(int(sample_h*.12),int(sample_h*.30))*H//sample_h,
                         rng.randint(0,offset)*H//sample_h)
                        for _ in range(max(6,int(sample_w/ref_scale)//8))), key=lambda a: a[2])
        mark_interval = max(1,round(3*self.detail_scale))
        for (tx, th, off) in trees:
            base = gy + off
            tiers = 4
            for k in range(tiers):
                top = base - th + int(k * th * 0.2)
                bot = base - int(th * (tiers - 1 - k) * 0.17) - int(th * 0.05)
                wmax = max(2, int(th * (0.26 + 0.07 * k)))
                for y in range(top, bot):
                    half = int(wmax * (y - top) / max(1, bot - top))
                    if 0 <= y < H:
                        x0 = max(0, tx - half)
                        x1 = min(W, tx + half + 1)
                        fill_row(bg, W, y, x0, x1, dark)
                        if 0 <= tx - half < W and (y - top) % mark_interval == 0:
                            bg[y * W + tx - half] = lit
            for y in range(base - self.px(3), min(H, base + self.px(2))):
                plot(bg, W, H, tx, y, rgb(30, 20, 18))
        # A single lit pane at the foot of the trees.
        wx, wy = round(W*.29), round(H*.80)
        pane_w = max(2, self.px(1.8))
        pane_h = max(2, self.px(1.35))
        spill = make_sprite(0x9A441E, max(3, self.px(2.6)), 1, 2.7)[0]
        stamp(bg, W, H, wx, wy, spill)
        for y in range(wy-pane_h//2, wy-pane_h//2+pane_h):
            for x in range(wx-pane_w//2, wx-pane_w//2+pane_w):
                plot(bg, W, H, x, y, 0xE7AC61 if y == wy-pane_h//2 else 0xB96936)
        self.bg = bg
        n = max(60, int(self.logical_area // 55))
        layers = ((0.50, 7.0, 3.0, rgb(115, 135, 175)), (0.33, 15.0, 5.0, rgb(200, 215, 240)),
                  (0.17, 26.0, 8.0, rgb(255, 255, 255)))
        self.flakes = []
        for i in range(n):
            li = 0 if i < n * 0.5 else (1 if i < n * 0.83 else 2)
            self.flakes.append([rng.uniform(0, W), rng.uniform(0, H), li, rng.uniform(0, 6.3),
                                rng.uniform(1.0, 2.2), rng.uniform(0.85, 1.15)])
        self.layers = layers
        self.flake_glow = make_sprite(0xCAD8EF,self.px(2),4,1.45)[-1] if self.gfx else None

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        wind = 6.0 * sin(t * 0.23) + 4.0 * sin(t * 0.51 + 1.3)
        layers = self.layers
        for f in self.flakes:
            li = f[2]
            vy, amp, col = layers[li][1], layers[li][2], layers[li][3]
            f[3] += dt * f[4]
            f[1] += vy * f[5] * dt * self.S
            f[0] += (wind * (0.4 + 0.5 * li) + sin(f[3]) * amp) * dt * self.S
            if f[1] >= H:
                f[1] -= H + self.px(4)
                f[0] = rng.uniform(0, W)
            x = int(f[0]) % W
            y = int(f[1])
            if 0 <= y < H:
                buf[y * W + x] = col
                if self.flake_glow and li==2:
                    stamp(buf,W,H,x,y,self.flake_glow)
                elif li == 2:
                    xr = (x + 1) % W
                    buf[y * W + xr] = col
                    if y + 1 < H:
                        buf[(y + 1) * W + x] = col
                        buf[(y + 1) * W + xr] = shade(col, 170)
        return buf


# --------------------------------------------------------------------- lava
class Lava(Scene):
    """An amber-wax lava lamp in a dark brass case."""
    fps = 10
    mask = 0xF8F8F8
    gfx_fps = 20
    gfx_pixels = 68000
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.left = max(0, round(W*.5-min(W*.48,H*.235)))
        self.top = round(H*.235)
        self.width = W-2*self.left
        self.height = round(H*.765)-self.top
        width,height = self.width,self.height
        self.sw,self.sh = _ambient_grid(width,height,2)
        self.pal = _ambient_palette(((0,0x100D21),(.35,0x251329),(.47,0x431B30),
                                     (.54,0xA72E21),(.58,0xDC5529),(.75,0xF88B3B),
                                     (1,0xFFCA76)))
        self.bg = []
        for y in range(H):
            v = y/H
            for x in range(W):
                u = (x-W*.5)/H
                spill = exp(-((u/.44)**2+((v-.73)/.39)**2)*1.55)
                wall = shade(0x1D1F2A,int(124+56*v))
                self.bg.append(addp(wall,shade(0xB54D25,int(spill*90))))
        self.glass = []
        for y in range(height):
            u = y/max(1,height-1)
            taper = .69+.20*_ambient_smooth(u/.91)
            shoulder = .19*(1-_ambient_smooth(u/.16))+.17*_ambient_smooth((u-.88)/.12)
            half = max(1,round(width*(taper-shoulder)*.5))
            left,right = width//2-half,min(width,width//2+half)
            rim = max(1,round(self.S*.85))
            row = (self.top+y)*W+self.left
            for x in range(left,right):
                if x-left < rim or right-1-x < rim:
                    warm = int(128+87*u)
                    self.bg[row+x] = shade(0x917063 if x-left < rim else 0x674A52,warm)
            lo,hi = left+rim,right-rim
            # The mask uses contiguous spans so clipping never touches the wall or metal.
            if lo<hi:
                self.glass.append((y,lo,hi))
        self.glints = []
        for y,lo,hi in self.glass:
            u = y/max(1,height-1)
            strip = min(hi-lo,max(1,round(1.4*self.S)))
            strength = int(46*sin(PI*u)**.65)
            for d in range(strip):
                self.glints.append(((self.top+y)*W+self.left+lo+d,
                                    shade(0xE2AAC5,strength//(d+1))))
        self._brass(round(H*.155),self.top, .22,.31)
        self._brass(round(H*.765),round(H*.917), .36,.47)
        self.blobs = [(rng.uniform(-.23,.23),rng.uniform(.03,.14),
                       rng.uniform(.075,.16),rng.random()*TAU,rng.random()*TAU)
                      for _ in range(7)]

    def _brass(self, top, bottom, narrow, wide):
        W = self.W
        for y in range(top,bottom):
            v = (y-top)/max(1,bottom-top-1)
            half = round(self.width*(narrow+(wide-narrow)*v))
            for dx in range(-half,half+1):
                if 0 <= W//2+dx < W:
                    u = dx/max(1,half)
                    curve = sqrt(max(0.,1-u*u))
                    spec = exp(-((u+.36)/.27)**2)
                    seam = .62 if y in (top,bottom-1) else 1.
                    lighting = int(seam*(45+70*curve+65*spec))
                    self.bg[y*W+W//2+dx] = shade(0xAB7843,lighting)

    def frame(self,t,dt):
        W,sw,sh = self.W,self.sw,self.sh
        heat = exp(-((t-300)/146)**2)
        travel = .19*t+102*(1+math.erf((t-300)/146))
        field = []
        for y in range(sh):
            depth = y/max(1,sh-1)
            field.extend([1.64*max(0.,(depth-.82)/.18)**2]*sw)
        for drift,rate,radius,phase,sway in self.blobs:
            lift = .5-.5*cos(travel*rate+phase)
            x = sw*(.5+drift+.13*sin(travel*.102+sway))
            y = sh*(.91-lift*(.29+.61*heat))
            r = max(1.1,min(sw,sh)*radius*2.1)
            ir = 1/(r*r)
            lo,hi = max(0,int(x-r)),min(sw,int(x+r)+1)
            xd = [(j-x)**2*ir for j in range(lo,hi)]
            for yy in range(max(0,int(y-r)),min(sh,int(y+r)+1)):
                a = 1-(yy-y)**2*ir
                base = yy*sw+lo
                for j,b in enumerate(xd):
                    k = a-b
                    if k>0:
                        field[base+j] += 2.38*k*k
        indices = [min(255,int(255*v/(.97+v))) for v in field]
        wax = up2(indices,sw,sh,self.width,self.height,self.pal)
        buf = self.bg[:]
        for row,lo,hi in self.glass:
            source = row*self.width
            dest = (self.top+row)*W+self.left
            buf[dest+lo:dest+hi] = wax[source+lo:source+hi]
        for i,color in self.glints:
            buf[i] = addp(buf[i],color)
        return buf


# -------------------------------------------------------------------- waves
class Waves(Scene):
    """Layered ocean swells at sunset."""
    fps = 16
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        hy = int(H * 0.50)
        self.hy = hy
        sky = gradient([(0.0, (18, 10, 52)), (0.35, (80, 20, 110)), (0.65, (210, 60, 110)),
                        (0.85, (255, 140, 90)), (1.0, (255, 210, 140))], hy)
        bg = []
        for c in sky:
            bg += [c] * W
        bg += [rgb(255, 210, 140)] * (W * (H - hy))
        self.sx = int(W * 0.68)
        sr = max(3, int(H * 0.11))
        for y in range(max(0, hy - sr * 3), hy):
            for x in range(max(0, self.sx - sr * 3), min(W, self.sx + sr * 3)):
                d = hypot(x - self.sx, y - (hy - sr * 0.2))
                j = y * W + x
                if d < sr:
                    bg[j] = rgb(255, 238, 180)
                elif d < sr * 3:
                    bg[j] = addp(bg[j], shade(rgb(255, 150, 90), int(256 * (1 - (d - sr) / (2.0 * sr)) ** 2 * 0.8)))
        for _ in range(6):                                          # streaky clouds
            cx, cy = rng.uniform(0, W), rng.uniform(H * 0.06, H * 0.4)
            rx, ry = rng.uniform(W * 0.08, W * 0.22), rng.uniform(0.8, 1.8)*self.S
            for y in range(int(cy-self.px(3)),int(cy+self.px(4))):
                for x in range(int(cx - rx), int(cx + rx)):
                    q = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                    if q < 1 and 0 <= x < W and 0 <= y < hy:
                        j = y * W + x
                        bg[j] = mix(bg[j], rgb(255, 170, 160), int(110 * (1 - q)))
        self.bg = bg
        n = 10
        self.layers = []
        for i in range(n):
            d = i / (n - 1)
            base = hy + self.px(2) + (H - hy - self.px(2)) * d ** 1.35
            col = mix(rgb(226, 112, 128), rgb(6, 26, 58), int(256 * d ** 0.7))
            crest = mix(col, rgb(255, 205, 175), int(256 * (0.42 * (1 - d) + 0.12)))
            ramp = [crest]*self.px(2) + [mix(crest, col, 128)]*self.px(1) + [shade(col, int(256 * (1.0 - 0.35 * min(1.0, k / (28.0*self.S))))) for k in range(H)]
            self.layers.append((base, (0.006 + 0.05 * d) * H, (0.09 * (1 - 0.7 * d) + 0.02)/self.S, (0.7 + 1.0 * d) * (1 if i % 2 else -1),
                                rng.uniform(0, 6.3), ramp, d))

    def frame(self, t, dt):
        W, H, hy, rng = self.W, self.H, self.hy, self.rng
        buf = self.bg[:]
        sx = self.sx
        for (base, amp, k, w, ph, ramp, d) in self.layers:
            for x in range(W):
                y = int(base + amp * (sin(k * x + w * t + ph) + 0.45 * sin(2.1 * k * x - 1.3 * w * t + 2 * ph)))
                if y >= H:
                    continue
                if y < hy:
                    y = hy
                n = H - y
                buf[y * W + x::W] = ramp[:n]
        for li, (base, amp, k, w, ph, ramp, d) in enumerate(self.layers):
            gw = int(self.S*(3+12*d))
            for x in range(sx-gw,sx+gw,self.px(1)):
                if 0 <= x < W and (sin(x/self.S*1.3+t*2.1+li*.83)>.61 if self.gfx else rng.random() < .32):
                    y = int(base + amp * (sin(k * x + w * t + ph) + 0.45 * sin(2.1 * k * x - 1.3 * w * t + 2 * ph)))
                    if hy <= y < H:
                        buf[y * W + x] = rgb(255, 225, 170)
        return buf


# ------------------------------------------------------------------- galaxy
class Galaxy(Scene):
    """Slowly rotating spiral galaxy over a twinkling star field."""
    fps = 12
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.cx, self.cy = W * .45, H * .53
        self.R = 1.30 * min(W * 0.46, H * 0.47)
        bg = vgrad(W, H, [(0.0, (1, 1, 6)), (0.5, (3, 4, 14)), (1.0, (1, 1, 6))])
        self.bgstars = []
        for _ in range(int(self.logical_area // 60)):
            x, y = self.detail_coord(W), self.detail_coord(H, True)
            c = shade(rgb(*rng.choice(((200, 210, 255), (255, 245, 225), (255, 215, 190)))), rng.randint(40, 230))
            self.bgstars.append((x, y, c, rng.uniform(0, 6.3), rng.uniform(0.5, 3.0), rng.random() < 0.18))
        for (x, y, c, p, s, tw) in self.bgstars:
            if not tw:
                bg[y * W + x] = c
        self.bgtw = [s for s in self.bgstars if s[5]]
        cr = max(3, int(self.R * 0.22))                                    # core glow
        for y in range(-cr * 2, cr * 2 + 1):
            for x in range(-cr * 2, cr * 2 + 1):
                d = hypot(x, y) / cr
                if d < 2:
                    plota(bg, W, H, int(self.cx) + x, int(self.cy) + y, shade(rgb(255, 215, 150), int(256 * 0.75 * (1 - d / 2) ** 2.4)))
        self.bg = bg
        stars = []
        for _ in range(1800 if not self.gfx else min(3050,int(1800*sqrt(self.S/self.detail_scale)))):
            k = rng.random()
            if k < 0.52:                              # spiral arms
                r = 0.10 + 0.9 * rng.random() ** 0.8
                arm = 0 if rng.random() < 0.5 else 1
                th = arm * PI + 2.2 * math.log(1 + r * 8.0) + rng.gauss(0, 0.20 + 0.16 * (1 - r))
                tight = abs(th - (arm * PI + 2.2 * math.log(1 + r * 8.0)))
                if rng.random() < 0.07 and tight < 0.15:
                    col = rgb(255, 120, 175)
                else:
                    col = rgb(175, 205, 255)
                lv = (0.30 + 0.7 * rng.random() ** 2) * (1.0 - 0.55 * r)
            elif k < 0.78:                            # diffuse disc
                r = rng.random() ** 0.85
                th = rng.uniform(0, TAU)
                col = rgb(235, 215, 195)
                lv = (0.18 + 0.4 * rng.random()) * (1.0 - 0.6 * r)
            else:                                     # bulge
                r = abs(rng.gauss(0, 0.11))
                th = rng.uniform(0, TAU)
                col = rgb(255, 225, 170)
                lv = .24+.52*rng.random()
            stars.append((r * cos(th), r * sin(th), shade(col, int(256 * lv)), lv))
        self.stars = stars
        self.big = [s for s in stars if s[3] > .63][:170]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for (x, y, c, p, s, tw) in self.bgtw:
            buf[y * W + x] = shade(c, int(256 * (0.35 + 0.65 * (0.5 + 0.5 * sin(t * s + p)))))
        th = t * 0.10
        psi = 0.5 + 0.35 * sin(t * 0.023)
        ci = 0.44 + 0.08 * sin(t * 0.017)
        ct, st = cos(th), sin(th)
        cp, sp = cos(psi), sin(psi)
        m00 = cp * ct - sp * ci * st
        m01 = -cp * st - sp * ci * ct
        m10 = sp * ct + cp * ci * st
        m11 = -sp * st + cp * ci * ct
        cx, cy, R = self.cx, self.cy, self.R
        # Grow subpixel coverage with output area while keeping each star's core color.
        detail = self.detail_scale
        rim = min(132, round(64*max(0., detail**2-1.)))
        corner = min(104, round(78*max(0., detail-1.45)))
        for (bx, by, c, lv) in self.stars:
            x = int(cx + R * (m00 * bx + m01 * by))
            y = int(cy + R * (m10 * bx + m11 * by))
            if 0 <= x < W and 0 <= y < H:
                i = y * W + x
                a = buf[i]
                s = a + c
                m = (s ^ a ^ c) & 0x1010100
                if m:
                    s = (s | (m - (m >> 8))) & 0xFFFFFF
                buf[i] = s
                if rim:
                    _gfx_point_rim(buf,W,H,x,y,shade(c,rim))
                if corner:
                    soft = shade(c,corner)
                    plota(buf,W,H,x-1,y-1,soft)
                    plota(buf,W,H,x+1,y-1,soft)
                    plota(buf,W,H,x-1,y+1,soft)
                    plota(buf,W,H,x+1,y+1,soft)
        halo = self.px(1)
        for (bx, by, c, lv) in self.big:
            x = int(cx + R * (m00 * bx + m01 * by))
            y = int(cy + R * (m10 * bx + m11 * by))
            g = shade(c, 70)
            plota(buf, W, H, x + halo, y, g)
            plota(buf, W, H, x - halo, y, g)
            plota(buf, W, H, x, y + halo, g)
            plota(buf, W, H, x, y - halo, g)
        return buf


# ------------------------------------------------------------------- plexus
class Plexus(Scene):
    """Drifting glowing nodes joined by fading links, with a roaming hub."""
    fps = 12
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = []
        cx, cy = W / 2.0, H / 2.0
        md = hypot(cx, cy)
        for y in range(H):
            for x in range(W):
                d = hypot(x - cx, y - cy) / md
                bg.append(rgb(11 - 9 * d, 15 - 12 * d, 38 - 30 * d))
        self.bg = bg
        nx = max(5,min(11,int(W/self.S)//14))
        ny = max(4,min(8,int(H/self.S)//14))
        self.nx = nx
        self.pts = [(W*(x+rng.uniform(.25,.75))/nx,H*(y+rng.uniform(.25,.75))/ny,
                     rng.random()*TAU,rng.uniform(.13,.30))
                    for y in range(ny) for x in range(nx)]
        self.pal = _ambient_palette(((0,0x5486A4),(.48,0xB58CC5),(1,0xBA8A76)),64)
        self.link = max(6.*self.S,min(25.*self.S,hypot(W/nx,H/ny)*1.28))
        self.swing = min(W/nx,H/ny)*.64
        self.sp = make_sprite(0x70A6C2, self.px(2), 8, 2.0)
        self.hubsp = make_sprite(rgb(190, 215, 255), self.px(4), 8, 2.4)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        hx = W * (.5 + .34 * sin(t * .11))
        hy = H * (.5 + .31 * sin(t * .093 + 1))
        pts = []
        for x,y,a,speed in self.pts:
            wave = t*speed+a
            motion = self.swing * (.78+.22*sin(t*.021+a))
            x += sin(wave)*motion
            y += cos(wave*.79+a)*motion
            dx,dy = hx-x,hy-y
            bend = .24*exp(-(dx*dx+dy*dy)/(2.5*self.link**2))
            pts.append((x+dx*bend,y+dy*bend,a))
        pal = self.pal
        np_ = len(pal)
        thr2 = self.link * self.link
        n = len(pts)
        cols = [pal[int((np_-1)*(.5+.5*sin(t*.045+p[2])))] for p in pts]
        for i in range(n):
            pi = pts[i]
            xi, yi = pi[0], pi[1]
            for j in range(i+1,min(i+2*self.nx+1,n)):
                pj = pts[j]
                dx = pj[0] - xi
                dy = pj[1] - yi
                d2 = dx * dx + dy * dy
                if d2 < thr2:
                    a = 1.0 - d2 / thr2
                    c = shade(mix(cols[i], cols[j], 128), int(111 * a))
                    line_add(buf, W, H, xi, yi, pj[0], pj[1], c)
        hub2 = (self.link * 1.5) ** 2
        for i in range(n):
            pi = pts[i]
            dx = hx - pi[0]
            dy = hy - pi[1]
            d2 = dx * dx + dy * dy
            if d2 < hub2:
                a = 1.0 - d2 / hub2
                line_add(buf, W, H, hx, hy, pi[0], pi[1], shade(0x87A4CA, int(112 * a)))
        for i in range(n):
            p = pts[i]
            stamp(buf, W, H, int(p[0]), int(p[1]), self.sp[5])
            plota(buf, W, H, int(p[0]), int(p[1]), cols[i])
        stamp(buf, W, H, int(hx), int(hy), self.hubsp[3])
        return buf


# -------------------------------------------------------------------- spiro
class Spiro(Scene):
    """Three nested hypotrochoid rosettes, counter-rotating, with flowing colour."""
    fps = 14
    mask = 0xF8F8F8

    def setup(self):
        W, H = self.W, self.H
        self.pal = _ambient_palette(((0,0x526B92),(.34,0x4DADA8),(.68,0xA977AA),
                                     (1,0xE8AE78)),128)
        self.R = min(W * 0.5, H * 0.5) * 0.93
        self.bg = vgrad(W, H, [(0.0, (5, 3, 14)), (0.5, (9, 5, 22)), (1.0, (5, 3, 14))])
        self.curves = [(7, 3, 1.00, 1.0), (9, 4, 0.72, -1.3), (8, 3, 0.46, 0.8)]   # (R, r, scale, spin)
        self.geometry = []
        for outer,inner,_,_ in self.curves:
            count = min(460,max(150,int(7*self.R)))
            period = TAU*inner
            k = (outer-inner)/inner
            self.geometry.append([(cos(a)*(outer-inner),sin(a)*(outer-inner),cos(k*a),-sin(k*a))
                                  for a in (i*period/count for i in range(count+1))])

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        cx, cy = W / 2.0, H / 2.0
        stroke = _gfx_line_set if self.gfx else line_set
        pal = self.pal
        for ci, (Rr, r, scl, spin) in enumerate(self.curves):
            d = r*(.93+.42*sin(t*.057+ci*2.1)+.12*sin(t*.021+ci))
            sc = self.R * scl / ((Rr - r) + d)
            shape = self.geometry[ci]
            n = len(shape)-1
            rot = t * .092 * spin
            cr, sr = cos(rot), sin(rot)
            px = py = None
            for i,(u,v,dx,dy) in enumerate(shape):
                x,y = u+d*dx,v+d*dy
                xx = cx + (x * cr - y * sr) * sc * 1.0
                yy = cy + (x * sr + y * cr) * sc * 1.0
                if px is not None:
                    color = pal[int(63.5+63.5*sin(i*TAU/n+t*.071+ci*2))]
                    stroke(buf,W,H,px,py,xx,yy,shade(color,211-ci*20))
                px, py = xx, yy
        return buf


# ------------------------------------------------------------------- school
class School(Scene):
    """A school of fish with real flocking, over light shafts and plankton."""
    fps = 15

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W,H,((0,(47,118,134)),(.10,(14,79,108)),(.46,(5,40,73)),(1,(2,11,31))))
        for y in range(max(1,round(H*.20))):
            for x in range(W):
                u,v = x/W,y/H
                wave = .5+.5*sin(39*u+92*v+1.3*sin(15*u-64*v))
                glow = int(115*wave**6*exp(-v*17))
                self.bg[y*W+x] = addp(self.bg[y*W+x],shade(0xB7ECD1,glow))
        self.kelp = [(W*u,H*h,rng.random()*TAU,depth)
                     for u,h,depth in ((.045,.49,0),(.111,.29,1),(.018,.36,2),
                                       (.918,.36,1),(.969,.63,0),(.992,.47,2))]
        for i in range(5):                                                  # light shafts
            x0 = rng.uniform(W * 0.1, W * 0.9)
            sl = rng.uniform(0.2, 0.5)
            wd = rng.uniform(3, 8)*self.S
            for y in range(int(H * 0.75)):
                xc = x0 + y * sl
                a = (1 - y / (H * 0.75)) * 0.10
                for x in range(int(xc - wd), int(xc + wd)):
                    if 0 <= x < W:
                        j = y * W + x
                        self.bg[j] = addp(self.bg[j], shade(rgb(120, 190, 220), int(256 * a * (1 - abs(x - xc) / wd))))
        n = max(30, min(90, int(self.logical_area // 130)))
        self.fish = []
        for i in range(n):
            a = rng.uniform(0, TAU)
            self.fish.append([rng.uniform(W * 0.3, W * 0.7), rng.uniform(H * 0.3, H * 0.7),
                              cos(a)*8*self.S, sin(a)*6*self.S, rng.uniform(0, 6.3), rng.uniform(0.8, 1.2), 0.])
        self.motes = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(0.5, 2.0), rng.uniform(0, 6.3)) for _ in range(int(self.logical_area // 110))]
        self.pal = (0xD8B478,0xBC8057,0xDECDA0,0x82BCCC)
        self.silver = 0xD5EEED

    def _seaweed(self,buf,t):
        W,H = self.W,self.H
        for origin,height,phase,depth in self.kelp:
            ink = (0x061D29,0x092734,0x0E3640)[depth]
            previous = None
            for k in range(13):
                u = k/12
                x = origin+sin(t*.34+phase+u*3.4)*height*.27*u
                y = H-1-u*height
                if previous:
                    line_set(buf,W,H,*previous,x,y,ink)
                    if self.S>1.2:
                        line_set(buf,W,H,previous[0]+self.S*.55,previous[1],x+self.S*.55,y,ink)
                previous = x,y
                if 1<k<12 and k%2==0:
                    side = -1 if k%4==0 else 1
                    reach = side*height*(.31-.18*u)
                    old = None
                    for j in range(6):
                        v = j/5
                        xx = x+reach*v+sin(t*.34+phase+v*2)*height*.10*u*v
                        yy = y-height*(.13*v+.065*sin(v*PI))
                        if old:
                            leaf = max(1,round(height*.036*sin(v*PI)))
                            _ambient_disc(buf,W,H,xx,yy,leaf,ink)
                            line_set(buf,W,H,*old,xx,yy,ink)
                        old = xx,yy

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        self._seaweed(buf,t)
        for (x, y, s, p) in self.motes:
            xx = int(x + 3*self.S*sin(t * 0.3 + p)) % W
            yy = int((y - t * s * 1.5*self.S) % H)
            plota(buf, W, H, xx, yy, rgb(30, 60, 80))
        fish = self.fish
        n = len(fish)
        gx = hx = 0.0
        gy = hy = 0.0
        for f in fish:
            gx += f[0]
            gy += f[1]
            hx += f[2]
            hy += f[3]
        gx /= n
        gy /= n
        hx /= n
        hy /= n
        px = W*(.5+.116*sin(t*.094))
        py = H*(.46+.126*sin(t*.131+1))
        margin_x,margin_y = W*.24,H*.22
        scale = self.S
        base_sq = scale*scale
        choose_distance, minimum_distance = 60*base_sq,2*base_sq
        speed_limit = min(10.8*scale,max(4.*scale,min(W,H)*.21))
        for i in range(n):
            f = fish[i]
            ax = (gx - f[0]) * 0.10 + (hx - f[2]) * 0.9 + (px - f[0]) * 0.22
            ay = (gy - f[1])*.13+(hy-f[3])*.96+(py-f[1])*.24
            ax += 3.4*(max(0.,margin_x-f[0])-max(0.,f[0]-W+margin_x))
            ay += 3.1*(max(0.,margin_y-f[1])-max(0.,f[1]-H+margin_y))
            for j in range(i + 1, min(n, i + 12)):                    # cheap separation on a window
                o = fish[j]
                dx = f[0] - o[0]
                dy = f[1] - o[1]
                d2 = dx * dx + dy * dy
                if d2 < choose_distance and d2 > 1e-3:
                    k = 62.0*base_sq/max(minimum_distance,d2)
                    ax += dx * k
                    ay += dy * k
                    o[2] -= dx * k * dt
                    o[3] -= dy * k * dt
            vx,vy = f[2],f[3]
            f[2] += ax * dt
            f[3] += ay * dt
            turn = abs(vx*f[3]-vy*f[2])/max(base_sq,vx*vx+vy*vy)
            f[6] = min(1.,max(0.,f[6]-2.4*dt)+max(0.,turn-.052)*2.3)
            sp = sqrt(f[2] * f[2] + f[3] * f[3]) + 1e-6
            mx = speed_limit*f[5]
            if sp > mx:
                f[2] *= mx / sp
                f[3] *= mx / sp
            elif sp < 3*scale:
                f[2] *= 3*scale/sp
                f[3] *= 3*scale/sp
            f[0] += f[2] * dt
            f[1] += f[3] * dt * 0.8
            f[4] += dt * (4 + sp * 0.5/scale)
            for axis,limit in enumerate((W,H)):
                if f[axis] < 2 or f[axis] > limit-3:
                    f[axis] = max(2.,min(limit-3.,f[axis]))
                    f[axis+2] *= -.45
        for i in range(n):
            f = fish[i]
            ang = atan2(f[3], f[2])
            ca, sa = cos(ang), sin(ang)
            light = (.48+.52*abs(ca))*(1-.40*f[1]/H)
            col = mix(self.pal[i & 3],self.silver,int(256*light*f[6]))
            wag = sin(f[4]) * .7
            if self.gfx:
                x,y = f[:2]
                line_set(buf,W,H,x-1.7*scale*ca,y-1.7*scale*sa,
                         x+2.3*scale*ca,y+2.3*scale*sa,col)
                _ambient_disc(buf,W,H,x+.3*scale*ca,y+.3*scale*sa,self.px(1),shade(col,212))
                for side in (-1,1):
                    wing = (wag+side*.72)*scale
                    _gfx_line_set(buf,W,H,x-1.3*scale*ca,y-1.3*scale*sa,
                                  x-2.9*scale*ca-wing*sa,y-2.9*scale*sa+wing*ca,shade(col,166))
                continue
            for (u, v, k) in ((2.2, 0, 256), (1.4, 0, 256), (0.6, 0, 240), (-0.2, 0.0, 220), (-1.0, 0.0, 200), (0.4, -0.7, 190), (0.4, 0.7, 190), (-0.4, -0.6, 170), (-0.4, 0.6, 170)):
                xx = int(f[0] + u * ca - v * sa)
                yy = int(f[1] + u * sa + v * ca)
                plot(buf, W, H, xx, yy, shade(col, k))
            tx, ty = f[0] - 1.8 * ca, f[1] - 1.8 * sa
            for s_ in (-1, 0, 1):
                xx = int(tx - 1.0 * ca - (wag + s_ * 0.8) * -sa)
                yy = int(ty - 1.0 * sa + (wag + s_ * 0.8) * ca)
                plot(buf, W, H, xx, yy, shade(col, 160))
        return buf


# ------------------------------------------------------------------ mystify
class Mystify(Scene):
    """Classic Mystify: bouncing polygons trailing rainbow echoes."""
    fps = 15
    mask = 0xF8F8F8
    gfx_pixels = 68000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.polys = []
        for p in range(2):
            vs = []
            for i in range(4):
                a = rng.uniform(0, TAU)
                s = rng.uniform(8,16) * min(1.2,H/(90*self.S))*self.S
                vs.append([rng.uniform(0, W - 1), rng.uniform(0, H - 1), cos(a) * s * 1.6, sin(a) * s])
            self.polys.append(vs)
        self.hist = [[] for _ in self.polys]
        self.pal = _ambient_palette(((0,0x366090),(.46,0x676998),(.78,0xA88173),(1,0xCB9E77)),64)
        self.bg = [rgb(2, 2, 8)] * (W * H)
        self.n = 19 if self.gfx else 14

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for pi, vs in enumerate(self.polys):
            for v in vs:
                v[0] += v[2] * dt
                v[1] += v[3] * dt
                if v[0] < 0:
                    v[0] = 0
                    v[2] = -v[2]
                elif v[0] > W - 1:
                    v[0] = W - 1
                    v[2] = -v[2]
                if v[1] < 0:
                    v[1] = 0
                    v[3] = -v[3]
                elif v[1] > H - 1:
                    v[1] = H - 1
                    v[3] = -v[3]
            h = self.hist[pi]
            h.append([(v[0], v[1]) for v in vs])
            if len(h) > self.n:
                h.pop(0)
            for k, poly in enumerate(h):
                lv = (k + 1) / len(h)
                color = self.pal[int(31.5+31.5*sin(t*.061+pi*2.4-lv*1.2))]
                c = shade(color,int(184*lv**2.15))
                m = len(poly)
                for a in range(m):
                    x0, y0 = poly[a]
                    x1, y1 = poly[(a + 1) % m]
                    line_set(buf, W, H, x0, y0, x1, y1, c)
        return buf


# -------------------------------------------------------------------- donut
class Donut(Scene):
    """A glazed ring tips gently above a soft studio-floor shadow."""
    fps = 14
    mask = 0xF8F8F8
    gfx_fps = 20
    gfx_pixels = 57500

    def setup(self):
        W, H = self.W, self.H
        self.bg = vgrad(W,H,((0,(10,7,21)),(.54,(26,14,34)),(.77,(40,26,44)),(1,(24,17,34))))
        for y in range(round(H*.63),round(H*.91)):
            for x in range(W):
                d = ((x-W*.53)/(min(W,H)*.36))**2+((y-H*.777)/(H*.059))**2
                if d<3.2:
                    i = y*W+x
                    self.bg[i] = shade(self.bg[i],int(256-136*exp(-1.4*d)))
        self.ramp = gradient([(0.0, (22, 8, 44)), (0.3, (150, 40, 120)), (0.62, (255, 120, 92)), (0.9, (255, 220, 190)), (1.0, (255, 250, 235))], 64)
        self.hw = W // 2
        self.hh = H // 2
        self.sc = min(self.hw * .42 / 3.4, self.hh * .45 / 3.0)
        n1 = int(min(208,max(100,self.hw * 2.9)))
        n2 = min(56,max(32,self.hh+4))
        if self.gfx:
            n1,n2 = 44,18
            self.faces = []
            for row in range(n1):
                for col in range(n2):
                    a,b = row*n2+col,((row+1)%n1)*n2+col
                    c,d = row*n2+(col+1)%n2,((row+1)%n1)*n2+(col+1)%n2
                    self.faces.extend(((a,b,c),(c,b,d)))
        self.pts = []
        for i in range(n1):
            th = i * TAU / n1
            ct, st = cos(th), sin(th)
            for j in range(n2):
                ph = j * TAU / n2
                cp, sp = cos(ph), sin(ph)
                self.pts.append(((2 + cp * 0.95) * ct, (2 + cp * 0.95) * st, sp * 0.95, cp * ct, cp * st, sp, 2*cp+.95))

    def frame(self, t, dt):
        W, H, hw, hh = self.W, self.H, self.hw, self.hh
        buf = self.bg[:]
        A = .49+.16*sin(t*.21)
        B = .33*sin(t*.147+.37)
        ca, sa = cos(A), sin(A)
        cb, sb = cos(B), sin(B)
        lx, ly, lz = -0.45, -0.6, -0.66
        ln = sqrt(lx * lx + ly * ly + lz * lz)
        lx /= ln
        ly /= ln
        lz /= ln
        hx, hy, hz = lx, ly, lz - 1
        hn = sqrt(hx * hx + hy * hy + hz * hz)
        hx /= hn
        hy /= hn
        hz /= hn
        cx, cy, sc = hw / 2.0, hh / 2.0, self.sc
        ramp = self.ramp
        if self.gfx:
            return self._mesh(buf,ca,sa,cb,sb,(lx,ly,lz),(hx,hy,hz))
        zb = [1e9] * (hw * hh)
        hit = {}
        for (x, y, z, nx, ny, nz, surface) in self.pts:
            # A cheap normal test rejects the hidden half before projection.
            nz1 = ny * sa + nz * ca
            nz2 = -nx * sb + nz1 * cb
            if surface+6*nz2 > .07:
                continue
            y1 = y * ca - z * sa
            z1 = y * sa + z * ca
            x2 = x * cb + z1 * sb
            z2 = -x * sb + z1 * cb
            zz = z2 + 6.0
            k = 5.0 / zz
            sx = int(cx + x2 * k * sc * 1.15)
            sy = int(cy + y1 * k * sc)
            if 0 <= sx < hw and 0 <= sy < hh:
                key = sy * hw + sx
                if zz < zb[key]:
                    ny1 = ny * ca - nz * sa
                    nx2 = nx * cb + nz1 * sb
                    zb[key] = zz
                    dif = nx2 * lx + ny1 * ly + nz2 * lz
                    spc = nx2 * hx + ny1 * hy + nz2 * hz
                    v = .16 + .64 * max(0.,dif) + max(0.,spc) ** 18 * .27
                    hit[key] = ramp[min(63, int(v * 63))]
        fill = {}
        for key, c in hit.items():
            if (key + 2) in hit and (key + 1) not in hit and key % hw < hw - 2:
                fill[key + 1] = mix(c,hit[key+2],128)
            if (key + 2 * hw) in hit and (key + hw) not in hit:
                fill[key + hw] = mix(c,hit[key+2*hw],128)
        hit.update(fill)
        # The first pass can restore the rim of a two-cell hole. Close its interior
        # only when the pixels above, below and to one side are already covered.
        for key,c in hit.items():
            gap = key+hw
            if (gap not in hit and gap+hw in hit and 0 < gap%hw < hw-1
                    and (gap-1 in hit or gap+1 in hit)):
                fill[gap] = mix(c,hit[gap+hw],128)
        hit.update(fill)
        # Suppress isolated undersampled flecks along a lit surface, leaving silhouettes alone.
        for key,c in hit.items():
            r = c>>16
            if r >= 170 or not 0 < key%hw < hw-1:
                continue
            for offset in (1,hw):
                low,high = hit.get(key-offset,0),hit.get(key+offset,0)
                if min(low>>16,high>>16)>r+44:
                    fill[key] = mix(low,high,128)
                    break
        hit.update(fill)
        for key, c in hit.items():
            y, x = divmod(key, hw)
            o = 2 * y * W + 2 * x
            buf[o] = buf[o + 1] = buf[o + W] = buf[o + W + 1] = c
        return buf

    def _mesh(self, buf, ca, sa, cb, sb, light, highlight):
        W,hw,hh,sc = self.W,self.hw,self.hh,self.sc
        lx,ly,lz = light
        hx,hy,hz = highlight
        points = []
        for x,y,z,nx,ny,nz,_ in self.pts:
            screen_y,rot_z = y*ca-z*sa,y*sa+z*ca
            inverse_z = 1/(6-x*sb+rot_z*cb)
            zoom = 5*sc*inverse_z
            normal_y,normal_z = ny*ca-nz*sa,ny*sa+nz*ca
            normal_x,normal_z = nx*cb+normal_z*sb,-nx*sb+normal_z*cb
            diffuse = max(0,normal_x*lx+normal_y*ly+normal_z*lz)
            specular = max(0,normal_x*hx+normal_y*hy+normal_z*hz)
            points.append((hw/2+(x*cb+rot_z*sb)*zoom*1.15,hh/2+screen_y*zoom,
                           inverse_z,63*(.16+.64*diffuse+.27*specular**18)))
        depth = [0.]*(hw*hh)
        surface = [-1]*(hw*hh)
        visible = []
        ramp = self.ramp
        for i,j,k in self.faces:
            ax,ay,az,al = points[i]
            bx,by,bz,bl = points[j]
            cx,cy,cz,cl = points[k]
            abx,aby,acx,acy = bx-ax,by-ay,cx-ax,cy-ay
            area = abx*acy-aby*acx
            if area >= -1e-8:
                continue
            left,right = max(0,math.ceil(min(ax,bx,cx))),min(hw-1,math.floor(max(ax,bx,cx)))
            top,bottom = max(0,math.ceil(min(ay,by,cy))),min(hh-1,math.floor(max(ay,by,cy)))
            if left>right or top>bottom:
                continue
            ur,vr = acy/area,-aby/area
            for y in range(top,bottom+1):
                u = (left-ax)*ur-(y-ay)*acx/area
                v = (left-ax)*vr+(y-ay)*abx/area
                for x in range(left,right+1):
                    if u >= -1e-7 and v >= -1e-7 and u+v <= 1.0000001:
                        key = y*hw+x
                        z = az+u*(bz-az)+v*(cz-az)
                        if z>depth[key]:
                            if surface[key] < 0:
                                visible.append(key)
                            depth[key] = z
                            surface[key] = ramp[min(63,int(al+u*(bl-al)+v*(cl-al)))]
                    u += ur
                    v += vr
        for key in visible:
            y,x = divmod(key,hw)
            i = 2*y*W+2*x
            color = surface[key]
            right = surface[key+1] if x+1<hw else color
            below = surface[key+hw] if y+1<hh else -1
            if right < 0:
                right = buf[i+1]
            if below < 0:
                below = buf[i+W]
            # Each component is halved before addition, matching mix(c1,c2,128).
            half = (color >> 1) & 0x7F7F7F
            east = half + ((right >> 1) & 0x7F7F7F)
            south = half + ((below >> 1) & 0x7F7F7F)
            buf[i],buf[i+1],buf[i+W] = color,east,south
            buf[i+W+1] = ((east >> 1) & 0x7F7F7F) + ((south >> 1) & 0x7F7F7F)
        return buf


# ------------------------------------------------------------------- sakura
class Sakura(Scene):
    """Cherry blossom branch with tumbling petals in a soft dusk sky."""
    fps = 16
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (70, 50, 110)), (0.45, (190, 120, 150)), (0.8, (250, 190, 175)), (1.0, (255, 220, 190))])
        sr = max(3, int(H * 0.09))
        sx, sy = int(W * 0.72), int(H * 0.62)
        for y in range(-sr * 3, sr * 3):
            for x in range(-sr * 3, sr * 3):
                d = hypot(x, y)
                if d < sr:
                    plot(bg, W, H, sx + x, sy + y, rgb(255, 240, 215))
                elif d < sr * 3:
                    plota(bg, W, H, sx + x, sy + y, shade(rgb(255, 170, 140), int(256 * 0.45 * (1 - (d - sr) / (2.0 * sr)) ** 2)))
        for _ in range(8):                                                # far haze hills
            pass
        ph = rng.uniform(0, 6)
        for x in range(W):
            ry = int(H * 0.88 - H * 0.04 * sin(x / W * 6 + ph) - H * 0.02 * sin(x / W * 17))
            bg[ry * W + x::W] = [rgb(150, 100, 130)] * (H - ry)
        # main branch from top-left
        self.blossoms = []
        branch = [(-2, H * 0.12)]
        x, y, ang = -2.0, H * 0.12, 0.25
        wdt = max(2.0, H * 0.035)
        segs = []

        def grow(x, y, ang, w, depth):
            ln = W * (0.07 if depth else 0.09)
            for _ in range(int(W * 0.5 / ln) + 1 if depth == 0 else 3):
                nx = x + cos(ang) * ln
                ny = y + sin(ang) * ln
                segs.append((x, y, nx, ny, w))
                x, y = nx, ny
                ang += rng.uniform(-0.28, 0.28)
                w *= 0.82
                if x > W * (0.55 if depth == 0 else 0.7) or w < 0.5:
                    break
                if depth < 2 and rng.random() < 0.55:
                    grow(x, y, ang + rng.choice((-1, 1)) * rng.uniform(0.5, 0.9), w * 0.7, depth + 1)
                if rng.random() < 0.6:
                    self.blossoms.append((x, y))
            self.blossoms.append((x, y))

        grow(x, y, ang, wdt, 0)
        bark = rgb(48, 26, 36)
        for (x0, y0, x1, y1, w) in segs:
            n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
            for i in range(n):
                f = i / n
                xx = x0 + (x1 - x0) * f
                yy = y0 + (y1 - y0) * f
                for k in range(int(w) + 1):
                    plot(bg, W, H, int(xx), int(yy) + k - int(w // 2), bark)
        cols = [rgb(255, 190, 215), rgb(255, 160, 195), rgb(255, 225, 235), rgb(240, 130, 175)]
        for (bx, by) in self.blossoms:
            for _ in range(7):
                dx = rng.gauss(0, 2.2)*self.S
                dy = rng.gauss(0, 1.8)*self.S
                c = rng.choice(cols)
                plot(bg, W, H, int(bx + dx), int(by + dy), c)
                plot(bg, W, H, int(bx + dx) + 1, int(by + dy), shade(c, 220))
            plot(bg, W, H, int(bx), int(by), rgb(255, 235, 150))
        self.bg = bg
        self.blossoms = [(bx, by) for (bx, by) in self.blossoms]
        n = max(30, min(120, int(self.logical_area // 90)))
        self.petals = []
        for i in range(n):
            self.petals.append(self._new(rng.uniform(0, W), rng.uniform(-H * 0.1, H), True))
        self.pc = [rgb(255, 196, 218), rgb(255, 170, 205), rgb(255, 222, 234), rgb(248, 150, 190)]

    def _new(self, x, y, anywhere=False):
        r = self.rng
        s = r.uniform(0.6, 1.5)
        return [x, y, r.uniform(0, 6.3), r.uniform(1.4, 3.2), s, r.uniform(0, 6.3), r.uniform(0, 3)]

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        wind = 7.0 + 4.0 * sin(t * 0.3) + 3 * sin(t * 0.91)
        for p in self.petals:
            p[2] += dt * p[3]
            p[5] += dt * (1.5 + p[4])
            p[0] += (wind * p[4] * 0.8 + 9.0 * sin(p[2] * 0.7)) * dt*self.S
            p[1] += (5.0 + 5.0 * p[4] + 2.5 * sin(p[2] * 1.3)) * dt*self.S
            if p[1] > H + 2 or p[0] > W + 3:
                if rng.random() < 0.6 and self.blossoms:
                    bx, by = rng.choice(self.blossoms)
                    p[0], p[1] = bx, by
                else:
                    p[0], p[1] = rng.uniform(-W * 0.2, W), -2
        pc = self.pc
        for i, p in enumerate(self.petals):
            x, y = int(p[0]), int(p[1])
            c = pc[i & 3]
            fl = cos(p[5])
            if self.gfx:
                _gfx_line_set(buf,W,H,x,y,x+self.S*fl,y+self.S*.62,c)
            elif abs(fl) > 0.55:
                plot(buf, W, H, x, y, c)
                plot(buf, W, H, x + 1, y, shade(c, 215))
                if p[4] > 1.0:
                    plot(buf, W, H, x, y + 1, shade(c, 190))
            else:
                plot(buf, W, H, x, y, shade(c, 235))
        return buf


# ------------------------------------------------------------------ skyline
class Skyline(Scene):
    """Night city: parallax towers, twinkling windows, blinking beacons, a moving train."""
    fps = 12
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (6, 6, 24)), (0.45, (28, 16, 60)), (0.75, (110, 40, 100)), (1.0, (240, 110, 110))])
        for _ in range(int(self.logical_area // 130)):
            plot(bg, W, H, rng.randrange(W), rng.randrange(int(H * 0.45)), shade(rgb(230, 230, 255), rng.randint(60, 200)))
        mr = max(2, int(H * 0.05))
        mx, my = int(W * 0.2), int(H * 0.16)
        for y in range(-mr, mr + 1):
            for x in range(-mr, mr + 1):
                if hypot(x, y) < mr:
                    plot(bg,W,H,mx+x,my+y,0xDAD6CC)
        moon_halo = make_sprite(0x5B5173,mr*4,3,2.8)
        stamp(bg,W,H,mx,my,moon_halo[1])
        windows = {}
        self.beacons = []
        specs = [(0.34, (30, 22, 58), (12, 3, 9), 0.5), (0.46, (18, 14, 40), (14, 4, 11), 0.8), (0.58, (8, 7, 20), (16, 5, 13), 1.0)]
        for (hf, col, bw, lit) in specs:
            x = -round(rng.randint(0,6)*self.S)
            while x < W:
                bw_ = self.px(rng.randint(bw[0] // 2 + 3, bw[0] + 5))
                bh = int(H * rng.uniform(hf * 0.5, hf * 1.15))
                top = H - bh
                left,right = max(0,x),min(W,x+bw_)
                for y in range(max(0,top),H):
                    fill_row(bg,W,y,left,right,rgb(*col))
                    for wx in range(left,right):
                        windows.pop((wx,y),None)
                self.beacons = [(bx,by,p) for bx,by,p in self.beacons
                                if not (left <= bx < right and by >= top)]
                if rng.random() < 0.4 and top > 3:
                    plot(bg, W, H, x + bw_ // 2, top - 1, rgb(*col))
                    plot(bg, W, H, x + bw_ // 2, top - 2, rgb(*col))
                    if hf > 0.4:
                        self.beacons.append((x + bw_ // 2, top - 3, rng.uniform(0, 6.3)))
                for wy in range(top+self.px(2),H-self.px(2),self.px(3)):
                    for wx in range(x+self.px(1),x+bw_-self.px(1),self.px(2)):
                        if rng.random() < 0.5 and 0 <= wx < W:
                            windows[wx,wy] = (wx,wy,rng.random()*TAU,rng.uniform(.025,.12),
                                              rng.choice((0xD5AB74,0xDEB581,0x93ADC7,0xCECAB7)),lit)
                x += bw_ + rng.randint(0, 2)
        for y in range(int(H * 0.93), H):
            fill_row(bg, W, y, 0, W, rgb(6, 5, 12))
        self.bg = bg
        self.train_y = int(H*.91)
        self.wins = [w for w in windows.values() if w[1]<self.train_y]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        for (x, y, p, flick, c, lit) in self.wins:
            dim = _ambient_smooth((sin(t*flick+p)-.58)/.4)
            light = shade(c,int((100+135*lit)*(1-.79*dim)))
            fill_row(buf,W,y,x,min(W,x+self.px(1)),light)
        for (x, y, p) in self.beacons:
            if sin(t * 2.2 + p) > 0.6 and 0 <= y < H:
                plota(buf, W, H, x, y, rgb(255, 40, 40))
                plota(buf, W, H, x + 1, y, rgb(90, 10, 10))
                plota(buf, W, H, x - 1, y, rgb(90, 10, 10))
        ty = self.train_y
        pos = (t*14*self.S)%(W+40*self.S)-20*self.S
        for k in range(8):
            x0 = int(pos-k*5*self.S)
            for xx in range(x0,x0+self.px(4)):
                plot(buf, W, H, xx, ty, rgb(40, 40, 60))
                plot(buf, W, H, xx, ty + 1, rgb(255, 235, 170))
        return buf


# ------------------------------------------------------------------- matrix
class Matrix(Scene):
    """Digital rain with real glyphs, per-column speed and bright heads (text mode)."""
    fps = 20
    text = True
    GL = ('ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ'
          '0123456789:.=*+-<>|')

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        # fullwidth-free: half-width katakana is 1 cell in kitty/most fonts
        self.cols = []
        for x in range(W):
            self.cols.append([rng.uniform(-H, 0), rng.uniform(6, 20), rng.randint(8, max(9, H)), rng.random() < 0.15])
        self.glyph = [[self.GL[rng.randrange(len(self.GL))] for _ in range(H)] for _ in range(W)]
        self.ramp = gradient([(0.0, (0, 20, 6)), (0.25, (0, 90, 30)), (0.6, (10, 200, 70)), (1.0, (120, 255, 150))], 24)
        self.head = rgb(215, 255, 225)
        self.empty = [' '] * (W * H)
        self.zero = [0] * (W * H)

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        chars = self.empty[:]
        fgs = self.zero[:]
        ramp = self.ramp
        glyph = self.glyph
        GL = self.GL
        nl = len(GL)
        for x in range(W):
            c = self.cols[x]
            c[0] += c[1] * dt
            if c[0] - c[2] > H:
                c[0] = rng.uniform(-H * 0.6, 0)
                c[1] = rng.uniform(6, 20)
                c[2] = rng.randint(8, max(9, H))
                c[3] = rng.random() < 0.15
            head = int(c[0])
            tl = c[2]
            gx = glyph[x]
            if 0 <= head < H and rng.random() < 0.6:
                gx[head] = GL[rng.randrange(nl)]
            for k in range(int(tl)):
                y = head - k
                if 0 <= y < H:
                    i = y * W + x
                    chars[i] = gx[y]
                    if k == 0:
                        fgs[i] = self.head
                    else:
                        fgs[i] = ramp[int(23 * (1 - k / tl) ** 1.5)]
                    if k > 1 and rng.random() < 0.01:
                        gx[y] = GL[rng.randrange(nl)]
        return chars, fgs


# ---------------------------------------------------------------- tesseract
class Tesseract(Scene):
    """Rotating 4-D hypercube: glowing wireframe in perspective."""
    fps = 15
    mask = 0xF8F8F8

    def setup(self):
        W, H = self.W, self.H
        self.bg = vgrad(W, H, [(0.0, (3, 4, 14)), (1.0, (7, 6, 22))])
        self.v = [[(1 if (i >> k) & 1 else -1) for k in range(4)] for i in range(16)]
        self.e = [(i, i ^ (1 << k)) for i in range(16) for k in range(4) if i < i ^ (1 << k)]
        self.sc = min(W*.42,H*.49)
        self.pal = _ambient_palette(((0,0x596BA0),(.53,0x6BADB9),(1,0xE4B484)),64)
        self.nodesp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 1.8)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        a = [t*.14,t*.109,t*.172,t*.079,t*.133,t*.071]
        planes = ((0, 3), (1, 3), (2, 3), (0, 1), (0, 2), (1, 2))
        cs = [(cos(x), sin(x)) for x in a]
        P = []
        cx, cy = W / 2.0, H / 2.0
        for v in self.v:
            p = list(v)
            for (i, j), (c, s) in zip(planes, cs):
                u, w = p[i], p[j]
                p[i] = u * c - w * s
                p[j] = u * s + w * c
            k4 = 1.0 / (2.6 - p[3])
            x, y, z = p[0] * k4, p[1] * k4, p[2] * k4
            k3 = 1.0 / (3.0 - z * 0.9)
            P.append((cx + x * k3 * self.sc * 2.3, cy + y * k3 * self.sc * 2.3, z))
        pal = self.pal
        width = min(1.45, self.detail_scale) if self.detail_scale >= 1.45 else 1.
        for i,j in sorted(self.e,key=lambda edge:P[edge[0]][2]+P[edge[1]][2]):
            x0, y0, z0 = P[i]
            x1, y1, z1 = P[j]
            zz = (z0 + z1) * 0.5
            near = max(0.,min(1.,.48+zz*.49))
            c = shade(pal[int(near*63)],int(113+119*near))
            line_add(buf,W,H,x0+self.S,y0,x1+self.S,y1,shade(c,53))
            if self.gfx:
                _gfx_line_set(buf,W,H,x0,y0,x1,y1,c,width)
            else:
                line_set(buf,W,H,x0,y0,x1,y1,c)
        for (x, y, z) in P:
            stamp(buf, W, H, int(x), int(y), self.nodesp[min(7, max(2, int(4 + z * 3)))])
        return buf


# ---------------------------------------------------------------- lissajous
class Lissajous(Scene):
    """Phosphor-style Lissajous scope with a long glowing comet tail."""
    fps = 16
    mask = 0xF8F8F8

    def setup(self):
        W, H = self.W, self.H
        self.bg = vgrad(W, H, [(0.0, (2, 8, 6)), (1.0, (2, 8, 6))])
        for x in range(0, W, max(self.px(6), W // 14)):
            for y in range(H):
                self.bg[y * W + x] = rgb(5, 18, 12)
        for y in range(0, H, max(self.px(6), H // 8)):
            fill_row(self.bg, W, y, 0, W, rgb(5, 18, 12))
        self.pal = (0x72B7AA,0x789CC6,0xC6A778)
        self.sp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 1.6)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        cx, cy = W / 2.0, H / 2.0
        ax, ay = W * 0.45, H * 0.45
        stroke = _gfx_line_add if self.gfx else line_add
        for ci, (a, b, ph, sp) in enumerate(((3, 2, 0.0, 0.5), (5, 4, 1.1, 0.4), (7, 5, 2.0, 0.33))):
            A = .9*sin(t*.039+ci)
            B = .9*cos(t*.027+ci)
            n = 132
            px = py = None
            tail = 3.6
            for i in range(n):
                tt = t*sp*.74-(n-i)*tail/n*.48
                x = cx + ax * (0.75 - 0.2 * ci) * sin(a*tt + ph + A)
                y = cy + ay * (0.75 - 0.2 * ci) * sin(b*tt + B)
                if px is not None:
                    f = (i / n) ** 2.2
                    c = shade(self.pal[ci],int(164*f))
                    stroke(buf, W, H, px, py, x, y, c)
                px, py = x, y
            stamp(buf,W,H,int(px),int(py),self.sp[5])
        return buf


# ----------------------------------------------------------------- pendulum
class Pendulum(Scene):
    """Triple pendulum (real physics, RK4) painting a luminous trail."""
    fps = 16
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = [0x040615]*(W*H)
        self.state = [rng.uniform(1.8, 2.8), rng.uniform(1.8, 2.8), rng.uniform(1.8, 2.8), 0.0, 0.0, 0.0]
        self.trail = []
        self.pal = _ambient_palette(((0,0x263658),(.38,0x417C93),(.72,0xA886BD),(1,0xE1BB8A)),64)
        self.L = min(H * .144, W * .146)
        self.sp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 1.4)

    def _acc(self, s):
        # triple pendulum, equal masses/lengths; solve M a = f numerically (3x3)
        th = s[:3]
        w = s[3:]
        g = 9.8
        M = [[0.0] * 3 for _ in range(3)]
        f = [0.0] * 3
        for i in range(3):
            for j in range(3):
                M[i][j] = (3 - max(i, j)) * cos(th[i] - th[j])
            f[i] = -sum((3 - max(i, j)) * sin(th[i] - th[j]) * w[j] * w[j] for j in range(3)) - (3 - i) * g * sin(th[i])
        # gaussian elimination
        A = [M[i][:] + [f[i]] for i in range(3)]
        for c in range(3):
            p = max(range(c, 3), key=lambda r: abs(A[r][c]))
            A[c], A[p] = A[p], A[c]
            d = A[c][c] or 1e-9
            for r in range(c + 1, 3):
                k = A[r][c] / d
                for cc in range(c, 4):
                    A[r][cc] -= k * A[c][cc]
        a = [0.0] * 3
        for i in (2, 1, 0):
            a[i] = (A[i][3] - sum(A[i][j] * a[j] for j in range(i + 1, 3))) / (A[i][i] or 1e-9)
        return s[3:] + a

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        s = self.state
        n = 5
        h = min(dt, .08) / n * 1.10
        for _ in range(n):
            k1 = self._acc(s)
            k2 = self._acc([a + b * h / 2 for a, b in zip(s, k1)])
            k3 = self._acc([a + b * h / 2 for a, b in zip(s, k2)])
            k4 = self._acc([a + b * h for a, b in zip(s, k3)])
            s = [a + h / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(s, k1, k2, k3, k4)]
        for i in range(3):
            s[i] = (s[i] + PI) % TAU - PI if abs(s[i]) > 50 else s[i]
        if any(abs(x) > 60 or x != x for x in s[3:]):                  # numeric blow-up guard
            s = [self.rng.uniform(1.8, 2.8) for _ in range(3)] + [0.0, 0.0, 0.0]
            self.trail = []
        self.state = s
        ox, oy = W / 2.0, H * 0.50
        L = self.L
        x1, y1 = ox + L * sin(s[0]), oy + L * cos(s[0])
        x2, y2 = x1 + L * sin(s[1]), y1 + L * cos(s[1])
        x3, y3 = x2 + L * sin(s[2]), y2 + L * cos(s[2])
        self.trail.append((x3, y3))
        if len(self.trail) > (345 if self.gfx else 260):
            self.trail.pop(0)
        tr = self.trail
        m = len(tr)
        for i in range(1, m):
            f = (i / m) ** 1.7
            c = shade(self.pal[int(63*(.5+.5*sin(t*.05+i*.017)))], int(176 * f))
            line_add(buf, W, H, tr[i - 1][0], tr[i - 1][1], tr[i][0], tr[i][1], c)
        arm = 0x859BB6
        stroke = _gfx_line_set if self.gfx else line_set
        for (a, b, c_, d) in ((ox, oy, x1, y1), (x1, y1, x2, y2), (x2, y2, x3, y3)):
            stroke(buf, W, H, a, b, c_, d, arm)
        for (x, y) in ((ox, oy), (x1, y1), (x2, y2)):
            stamp(buf, W, H, int(x), int(y), self.sp[4])
        stamp(buf, W, H, int(x3), int(y3), self.sp[7])
        return buf


# ------------------------------------------------------------ constellation
class Constellation(Scene):
    """A slowly drifting star map with fading links and one roaming hub."""
    fps = 12
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W, H, [(0.0, (3, 4, 16)), (0.6, (10, 10, 36)), (1.0, (22, 12, 44))])
        for _ in range(int(self.logical_area // 90)):
            plot(self.bg, W, H, self.detail_coord(W), self.detail_coord(H,True), shade(rgb(130, 140, 190), rng.randint(40, 150)))
        n = max(32, min(77, int(self.logical_area // 160)))
        self.s = []
        for i in range(n):
            a = rng.uniform(0, TAU)
            sp = rng.uniform(.85, 3.5)*self.S
            self.s.append([rng.uniform(0, W), rng.uniform(0, H), cos(a) * sp, sin(a) * sp * 0.6, rng.uniform(0, 6.3), rng.random()])
        self.lk = max(9.*self.S,min(23.*self.S,H*.225))
        self.sp = make_sprite(rgb(255, 255, 255), self.px(2), 8, 2.0)
        self.tints = [rgb(190, 215, 255), rgb(255, 240, 215), rgb(255, 200, 190)]
        self.hub_glow = make_sprite(0xBFD7FF, self.px(4), 8, 2.25)

    @staticmethod
    def _thin_link(buf,W,H,x0,y0,x1,y1,color):
        # Star centers are in bounds. Use the two minor-axis samples without a fringe.
        steep = abs(y1-y0)>abs(x1-x0)
        if steep:
            x0,y0,x1,y1 = y0,x0,y1,x1
        if x0>x1:
            x0,x1,y0,y1 = x1,x0,y1,y0
        span = x1-x0
        slope = (y1-y0)/span if span else 0.
        major,minor = (H,W) if steep else (W,H)
        step = 1 if steep else W
        rb,g = color&0xFF00FF,color&0x00FF00
        floor = math.floor
        for x in range(round(x0),min(major,round(x1)+1)):
            y = y0+(x-x0)*slope
            base = floor(y)
            alpha = int((y-base)*256)
            offset = x*W+base if steep else base*W+x
            if 0<=base<minor:
                weight = 256-alpha
                ink = (((rb*weight)>>8)&0xFF00FF)|(((g*weight)>>8)&0x00FF00)
                pixel = buf[offset]
                total = pixel+ink
                carry = (total^pixel^ink)&0x1010100
                buf[offset] = (total|(carry-(carry>>8)))&0xFFFFFF if carry else total
            if alpha and 0<=base+1<minor:
                ink = (((rb*alpha)>>8)&0xFF00FF)|(((g*alpha)>>8)&0x00FF00)
                pixel = buf[offset+step]
                total = pixel+ink
                carry = (total^pixel^ink)&0x1010100
                buf[offset+step] = (total|(carry-(carry>>8)))&0xFFFFFF if carry else total

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        S = self.s
        for p in S:
            p[0] = (p[0] + p[2] * dt) % W
            p[1] = (p[1] + p[3] * dt) % H
        cell = self.lk
        grid = {}
        for i, p in enumerate(S):
            grid.setdefault((int(p[0] / cell), int(p[1] / cell)), []).append(i)
        thr2 = cell * cell
        link = self._thin_link if self.gfx else line_add
        line_c = mix(0x7492CE,0x947DB3,int(128+110*sin(t*.021)))
        hub_budget = 0
        for (gx, gy), idxs in grid.items():
            for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 1)):
                other = grid.get((gx + dx, gy + dy))
                if not other:
                    continue
                for i in idxs:
                    pi = S[i]
                    for j in other:
                        if (dx or dy) or j > i:
                            pj = S[j]
                            ddx = pj[0] - pi[0]
                            ddy = pj[1] - pi[1]
                            d2 = ddx * ddx + ddy * ddy
                            if 1 < d2 < thr2:
                                if i == 0 or j == 0:
                                    hub_budget += 1
                                    continue
                                a = (1.0 - d2 / thr2) ** 1.3
                                ink = shade(line_c, int(122*a))
                                if ink:
                                    link(buf,W,H,pi[0],pi[1],pj[0],pj[1],ink)
        hx = W*(.50+.32*sin(t*.046))
        hy = H*(.50+.31*sin(t*.039+1.0))
        if hub_budget:
            candidates = []
            radius_sq = thr2*1.85
            for x,y,*_ in S[1:]:
                d2 = (x-hx)**2+(y-hy)**2
                if 1<d2<radius_sq:
                    candidates.append((d2,x,y))
            # Reuse only the link slots freed by the star the hub replaces.
            for d2,x,y in sorted(candidates)[:min(3,hub_budget)]:
                link(buf,W,H,hx,hy,x,y,shade(0x9BB4DD,int(122*(1-d2/radius_sq))))
        stamp(buf,W,H,round(hx),round(hy),self.hub_glow[5+round(1+sin(t*.56))])
        plota(buf,W,H,round(hx),round(hy),0xD1DEFB)
        for i, p in enumerate(S[1:], 1):
            tw = 0.55 + 0.45 * sin(t * (.58 + p[5] * .95) + p[4])
            lv = int(2 + 5 * tw * (0.5 + 0.5 * p[5]))
            xi, yi = int(p[0]), int(p[1])
            stamp(buf, W, H, xi, yi, self.sp[min(7, lv)])
            plota(buf, W, H, xi, yi, shade(self.tints[i % 3], int(256 * tw)))
        return buf


# -------------------------------------------------------------------- sonar
class Sonar(Scene):
    """Radar scope: phosphor sweep with afterglow, range rings and blips that echo."""
    fps = 15

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.cx, self.cy = W / 2.0, H / 2.0
        self.R = min(W * 0.5, H * 0.5) * 0.94
        rr = self.R
        bg = [rgb(1, 8, 5)] * (W * H)
        for y in range(H):
            for x in range(W):
                d = hypot(x - self.cx, (y - self.cy)) / rr
                if d < 1.0:
                    bg[y * W + x] = rgb(2, 16 - 6 * d, 9 - 3 * d)
        for k in range(1, 5):
            r = rr * k / 4
            for i in range(int(TAU * r * 1.3)):
                a = i / (r * 1.3)
                plot(bg, W, H, int(self.cx + r * cos(a)), int(self.cy + r * sin(a)), rgb(10, 70, 36) if k < 4 else rgb(20, 130, 64))
        for i in range(12):
            a = i * TAU / 12
            line_set(bg, W, H, self.cx, self.cy, self.cx + rr * cos(a), self.cy + rr * sin(a), rgb(7, 40, 22))
        self.bg = bg
        self.blips = []
        for i in range(14):
            a = rng.uniform(0, TAU)
            r = rng.uniform(0.15, 0.95) * rr
            self.blips.append([a, r, rng.uniform(-0.05, 0.05), rng.uniform(-0.08, 0.08)])
        self.sweepcols = [shade(rgb(80, 255, 140), int(256 * (1 - i / 64) ** 2.2)) for i in range(64)]

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        cx, cy, R = self.cx, self.cy, self.R
        sw = (t * 1.3) % TAU
        for k in range(64):
            a = sw - k * 0.022
            line_add(buf, W, H, cx, cy, cx + R * cos(a), cy + R * sin(a) * 1.0, shade(self.sweepcols[k], 60 if k else 256))
        for b in self.blips:
            b[0] += b[2] * dt
            b[1] += b[3]*6*dt*self.S
            if b[1] > R * 0.97 or b[1] < R * 0.1:
                b[3] = -b[3]
            diff = (sw - b[0]) % TAU
            lv = max(0.0, 1.0 - diff / 4.4) ** 2.2
            if lv < 0.02:
                continue
            x, y = int(cx + b[1] * cos(b[0])), int(cy + b[1] * sin(b[0]))
            c = shade(rgb(120, 255, 170), int(256 * lv))
            plota(buf, W, H, x, y, c)
            plota(buf, W, H, x+self.px(1),y,c)
            plota(buf, W, H, x,y+self.px(1),shade(c,150))
            if lv > 0.7:
                ring = ((1-lv)*20+2)*self.S
                samples = self.px(14)
                for i in range(samples):
                    ang = i*TAU/samples
                    plota(buf, W, H, int(x + ring * cos(ang)), int(y + ring * sin(ang)), shade(c, 90))
        return buf


# ----------------------------------------------------------------- wormhole
class Wormhole(Scene):
    """Flight down a twisting, glowing tunnel with ring stripes and streaking stars."""
    fps = 11
    mask = 0xF0F0F0
    gfx_fps = 20
    gfx_pixels = 56000

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.cx, self.cy = W / 2.0, H / 2.0
        self.sh = H if self.gfx else (H+1)//2
        sh = self.sh
        cx, cy = W / 2.0, sh / 2.0
        hh = H * 0.5
        self.ang = []
        self.depth = []
        self.fog = []
        for y in range(sh):
            for x in range(W):
                dx = (x + 0.5 - cx) / hh
                dy = (y+.5-cy)*H/sh/hh if self.gfx else 2.0*(y+.5-cy)/hh
                r = hypot(dx, dy)
                depth = 2.2/(.28+r)
                self.depth.append(int(depth*.82*256))
                self.ang.append(math.floor((atan2(dy,dx)/TAU*4+depth*.075)*256))
                self.fog.append(min(15, int(15 * min(1.0, r * 1.7) ** 0.8)))
        hues = _ambient_palette(((0,0x08172A),(.36,0x25435A),(.68,0x438680),
                                 (.88,0xAC815D),(1,0xDAC09A)),64)
        self.tab = [[shade(h, 12 + 11*l) for h in hues] for l in range(16)]
        self.st = [[rng.uniform(0, TAU), rng.uniform(.05,1.0)]
                   for _ in range(max(18,min(61,int(self.logical_area//240))))]
        radius = min(W,H)*.102
        self.halo = []
        for y in range(max(0,int(self.cy-radius)),min(H,int(self.cy+radius)+1)):
            for x in range(max(0,int(self.cx-1.9*radius)),min(W,int(self.cx+1.9*radius)+1)):
                d = hypot((x-self.cx)/1.9,y-self.cy)/radius
                if d < 1:
                    self.halo.append((y*W+x,int(191*(1-d)**1.7)))

    def frame(self, t, dt):
        W, H, sh = self.W, self.H, self.sh
        tab = self.tab
        sp = int((t*.31+.52*sin(t*.042))*.82*256)
        tw = int(t*.029*256)
        out = []
        ext = out.extend
        ang, dep, fog = self.ang, self.depth, self.fog
        for y in range(sh):
            o = y * W
            row = []
            ap = row.append
            for a, d, f in zip(ang[o:o + W], dep[o:o + W], fog[o:o + W]):
                spiral = SIN256[(a+tw)&255]
                band = SIN256[(d+sp+spiral//5)&255]
                ap(tab[f][(band*(190+spiral//4))>>10])
            ext(row)
            if not self.gfx and 2*y+1<H:
                ext(row)
        cx, cy = self.cx, self.cy
        streak = _gfx_line_add if self.gfx else line_add
        for j,strength in self.halo:
            out[j] = mix(out[j],0xDCCB9E,strength)
        for s in self.st:
            s[1] += dt * (.052 + .36 * s[1])
            if s[1] > 1.4:
                s[1] = 0.08
                s[0] = self.rng.uniform(0, TAU)
            r1 = s[1]
            r0 = r1 * .94
            ca, sa = cos(s[0]), sin(s[0])
            streak(out, W, H, cx + ca * r0 * W * 0.5, cy + sa * r0 * H * 0.5,
                     cx + ca * r1 * W * 0.5, cy + sa * r1 * H * 0.5, shade(0xB4C3D8, int(min(158, 190 * r1))))
        return out


# --------------------------------------------------------------- fireworks
class Fireworks(Scene):
    """Rockets, spherical bursts, glitter and smoke-free sparkle over a reflective bay."""
    fps = 15
    mask = 0xF0F0F0

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        bg = vgrad(W, H, [(0.0, (2, 2, 10)), (0.7, (8, 8, 28)), (1.0, (14, 12, 34))])
        for _ in range(int(self.logical_area // 200)):
            plot(bg, W, H, rng.randrange(W), rng.randrange(int(H * 0.6)), shade(rgb(200, 210, 255), rng.randint(40, 130)))
        self.hy = int(H * 0.82)
        for x in range(W):
            ry = int(self.hy - H * 0.04 * (0.5 + 0.5 * sin(x * 0.11 + 1)) * (1 if (x // 5) % 3 else 0.4) - 1)
            bg[ry * W + x::W] = [rgb(4, 4, 10)] * (H - ry)
        self.bg = bg
        self.rockets = []
        self.parts = []
        self.acc = 0.0
        self.next = 0.3
        self.pals = [((255, 90, 70), (255, 200, 90)), ((90, 170, 255), (200, 240, 255)), ((120, 255, 150), (240, 255, 190)),
                     ((255, 110, 220), (255, 200, 240)), ((255, 210, 80), (255, 250, 200)), ((180, 120, 255), (230, 200, 255))]

    def frame(self, t, dt):
        W, H, rng = self.W, self.H, self.rng
        buf = self.bg[:]
        hy = self.hy
        self.acc += dt
        if self.acc >= self.next and len(self.rockets) < 3 and len(self.parts) < 900:
            self.acc = 0
            self.next = rng.uniform(1.25, 3.6)
            self.rockets.append([rng.uniform(W * .24, W * .76), float(hy), rng.uniform(-3,3)*self.S,
                                 -rng.uniform(H * 0.85, H * 1.15), rng.uniform(H * .27, H * .50), rng.randrange(6)])
        nr = []
        for r in self.rockets:
            r[0] += r[2] * dt
            r[1] += r[3] * dt
            r[3] += 0.0
            if r[1] <= r[4]:
                pal = self.pals[r[5]]
                big = rng.random() < 0.25
                n = int((150 if not big else 240) * min(1.3,W/(100*self.S)+.3))
                v = min(H*.36,W*.27)*rng.uniform(.82,1.10)*(1.17 if big else 1)
                ring = rng.random() < 0.3
                for i in range(n):
                    a = (i+rng.uniform(-.43,.43))*TAU/n if ring else rng.uniform(0,TAU)
                    if ring:
                        s = v*rng.uniform(.85,1.04)
                    else:
                        s = v * sqrt(rng.random()) * 1.0 + v * 0.15
                    col = pal[0] if i % 3 else pal[1]
                    self.parts.append([r[0], r[1], cos(a) * s * 1.7, sin(a) * s, rng.uniform(1.65, 2.8), 0.0, col, rng.random() < 0.18])
                continue
            nr.append(r)
            line_add(buf, W, H, r[0], r[1], r[0] - r[2] * 0.06, r[1]+3*self.S,rgb(255, 230, 180))
            plota(buf, W, H, int(r[0]), int(r[1]), rgb(255, 255, 255))
        self.rockets = nr
        keep = []
        grav = H * 0.35
        drag = 0.5 ** (dt * 2.0)
        for p in self.parts:
            p[5] += dt
            if p[5] >= p[4]:
                continue
            p[2] *= drag
            p[3] = p[3] * drag + grav * dt
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if p[1] >= hy:
                continue
            keep.append(p)
            f = 1.0 - p[5] / p[4]
            tw = .81+.19*sin(p[5]*5+p[4]*4) if p[7] else 1.
            rise = _ambient_smooth(p[5]/.20)
            c = shade(rgb(*p[6]), int(201 * f ** 1.03 * tw * rise))
            x, y = int(p[0]), int(p[1])
            plota(buf, W, H, x, y, c)
            plota(buf, W, H, int(p[0] - p[2] * dt * 1.8), int(p[1] - p[3] * dt * 1.8), shade(c, 110))
            if f>.45 and self.gfx:
                g = shade(c,65)
                for ox,oy in ((1,0),(-1,0),(0,1),(0,-1)):
                    plota(buf,W,H,x+ox,y+oy,g)
                    if self.S>1.6:
                        plota(buf,W,H,x+ox*2,y+oy*2,shade(g,74))
            elif f > .45:
                g = shade(c, 70)
                plota(buf, W, H, x + 1, y, g)
                plota(buf, W, H, x - 1, y, g)
                plota(buf, W, H, x, y + 1, g)
                plota(buf, W, H, x, y - 1, g)
            ry = 2 * hy - y                                      # water reflection
            if ry < H and f > 0.2:
                plota(buf, W, H, x, ry, shade(c, 60))
        self.parts = keep
        return buf


# -------------------------------------------------------------------- boids
class Boids(Scene):
    """Murmuration: a large flock with real separation / alignment / cohesion and swirl, over dusk sky."""
    fps = 15
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W, H, [(0.0, (30, 36, 90)), (0.5, (150, 90, 130)), (0.85, (250, 160, 110)), (1.0, (255, 200, 130))])
        n = max(40, min(110, int(self.logical_area//90)))
        self.b = []
        for i in range(n):
            a = rng.uniform(0, TAU)
            self.b.append([rng.uniform(W * 0.3, W * 0.7), rng.uniform(H * 0.3, H * 0.7), cos(a)*12*self.S,sin(a)*8*self.S])
        self.cell = max(7.*self.S,H*.14)
        self.edge = min(min(W,H)*.20, max(self.px(3), min(W,H)*.068))
        self.turn_x = max(self.edge*2, W*.20)
        self.turn_y = max(self.edge*2, H*.24)
        for x in range(W):
            u = x/W
            for base,amplitude,color in ((.83,.049,0x62475C),(.93,.038,0x372E48)):
                y = int(H*(base-amplitude*(sin(8*u+base)+.46*cos(20*u))))
                self.bg[y*W+x::W] = [color]*(H-y)

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        B = self.b
        cell = self.cell
        grid = {}
        for i, b in enumerate(B):
            grid.setdefault((int(b[0] / cell), int(b[1] / cell)), []).append(i)
        gx = W*(.50+.25*sin(t*.094))
        gy = H*(.46+.15*sin(t*.139+1.0))
        edge, turn_x, turn_y = self.edge, self.turn_x, self.turn_y
        right, bottom = W-1-edge, H-1-edge
        c2 = cell * cell
        for i, b in enumerate(B):
            x, y, vx, vy = b
            cxg, cyg = int(x / cell), int(y / cell)
            sx = sy = ax = ay = cx_ = cy_ = 0.0
            n = 0
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    for j in grid.get((cxg + ox, cyg + oy), ()):
                        if j == i:
                            continue
                        o = B[j]
                        dx = o[0] - x
                        dy = o[1] - y
                        d2 = dx * dx + dy * dy
                        if d2 < c2:
                            n += 1
                            ax += o[2]
                            ay += o[3]
                            cx_ += o[0]
                            cy_ += o[1]
                            if d2 < c2 * 0.12 and d2 > 1e-3:
                                sx -= dx / d2
                                sy -= dy / d2
            fx = fy = 0.0
            if n:
                fx += (ax / n - vx) * 1.6 + (cx_ / n - x) * 0.25 + sx*28*self.S**2
                fy += (ay / n - vy) * 1.6 + (cy_ / n - y) * 0.25 + sy*28*self.S**2
            wall_x = max(0.,turn_x-x)-max(0.,x-W+turn_x)
            wall_y = max(0.,turn_y-y)-max(0.,y-H+turn_y)
            fx += (gx-x)*.12+3.2*wall_x
            fy += (gy-y)*.17+3.2*wall_y
            if wall_x*vx < 0:
                fx -= vx*min(2.4, 5.0*abs(wall_x)/turn_x)
            if wall_y*vy < 0:
                fy -= vy*min(2.4, 5.0*abs(wall_y)/turn_y)
            vx += fx * dt
            vy += fy * dt
            sp = sqrt(vx * vx + vy * vy) + 1e-6
            hi = min(16.*self.S,max(5.*self.S,min(W,H)*.27))
            lo = hi*.42
            if sp > hi:
                vx *= hi / sp
                vy *= hi / sp
            elif sp < lo:
                vx *= lo / sp
                vy *= lo / sp
            x,y = x+vx*dt,y+vy*dt
            if x < edge or x > right:
                x, vx = max(edge, min(right, x)), -.48*vx
            if y < edge or y > bottom:
                y, vy = max(edge, min(bottom, y)), -.48*vy
            b[0], b[1], b[2], b[3] = x, y, vx, vy
        col = rgb(12, 10, 24)
        for b in B:
            x, y = int(b[0]), int(b[1])
            sp = sqrt(b[2] * b[2] + b[3] * b[3]) + 1e-6
            ux, uy = b[2] / sp, b[3] / sp
            plot(buf, W, H, x, y, col)
            plot(buf, W, H, int(b[0] - ux*1.2*self.S), int(b[1] - uy*1.2*self.S), col)
            wing = sin(t*5.2+(x*.23+y*.3)/self.S)*1.35*self.S
            if self.gfx:
                _gfx_line_set(buf,W,H,x-uy*wing,y+ux*wing,x+uy*wing,y-ux*wing,col)
            plot(buf, W, H, int(b[0] - uy * wing), int(b[1] + ux * wing), col)
            plot(buf, W, H, int(b[0] + uy * wing), int(b[1] - ux * wing), col)
        return buf


# --------------------------------------------------------------------- fire
class Fire(Scene):
    """Classic fire effect, softly blurred, with rising embers and a warm glow."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 56000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.left, self.top = round(W*.15), round(H*.12)
        self.width = W - 2*self.left
        self.height = round(H*.89) - self.top
        self.fw = (self.width + 1) // 2
        self.fh = (self.height + 1) // 2 + self.px(6)
        self.pal = _ambient_palette(((0,0x080611),(.17,0x281323),(.39,0x803223),
                                     (.64,0xCA612D),(.84,0xECA04E),(1,0xF4D28E)))
        self.fuel = []
        for x in range(self.fw):
            u = x/max(1,self.fw-1)
            taper = _ambient_smooth(min(u,1-u)/.19)
            hearth = (.54+.46*sin(PI*u)**.8)*taper
            self.fuel.append((u, rng.uniform(-.05,.05), hearth))
        self.f = [0] * (self.fw * self.fh)
        self.embers = []
        self.setup_hearth()

    def setup_hearth(self):
        W, H = self.W, self.H
        left, top, width, height = self.left, self.top, self.width, self.height
        spring = max(1, round(height*.30))
        floor = top+height
        stone_w, stone_h = self.px(15), self.px(6)
        mortar = max(2, self.px(1))
        self.opening = []
        self.bg = [0]*(W*H)
        for y in range(H):
            row = y-top
            inset = 0
            if 0 <= row < spring:
                arc = (spring-row)/(spring+.6)
                inset = min(width//2-1, round(width*.36*(1-sqrt(1-arc*arc))))
            tile_row = y//stone_h
            for x in range(W):
                tx = x+(tile_row % 2)*stone_w//2
                tile = tx//stone_w
                light = exp(-((x/W-.50)/.39)**2-((y/H-.83)/.50)**2)
                distance = min(abs(x-left-inset), abs(x-left-width+inset+1))
                trim = 0 <= row < height and distance < self.px(2)
                seam = not trim and (tx % stone_w < mortar or y % stone_h < mortar)
                gx, gy = x//self.px(2), y//self.px(2)
                grit = ((gx*83 ^ gy*131 ^ gx*gy*7) % 6)-3
                tone = (tile*13 ^ tile_row*19) % 9 if not seam else -6
                if floor <= y < floor+self.px(2):
                    tone -= 5
                core = rgb(10+tone+grit, 10+tone*.7+grit, 14+tone*.55+grit)
                spill = shade(0x733514, int(light*(115 if trim else 54 if seam else 87)))
                self.bg[y*W+x] = addp(core, spill)
            if 0 <= row < height:
                self.opening.append((inset, width-inset))

        # Charred logs cross just above the hearth, with a thin ember-lit upper lip.
        self.logs = []
        for x0, y0, x1, y1, thickness in ((.17,.94,.70,.85,.047), (.34,.86,.85,.97,.057)):
            a, b = x0*width, y0*height
            dx, dy = x1*width-a, y1*height-b
            length = dx*dx+dy*dy
            radius = max(1.1, height*thickness)
            for row in range(max(0, int(min(b,b+dy)-radius)), min(height, round(max(b,b+dy)+radius+1))):
                for col in range(max(0,int(a-radius)), min(width,round(a+dx+radius+1))):
                    u = max(0.,min(1.,((col-a)*dx+(row-b)*dy)/length))
                    off = row-b-u*dy
                    distance = hypot(col-a-u*dx,off)
                    grain = ((row*19 ^ col*31) % 7)
                    if distance <= radius*(.85+grain*.035):
                        color = 0x130B10
                        if off < -radius*.36:
                            color = shade(0x85371F, 97+grain*17)
                        elif grain < 2:
                            color = 0x241119
                        self.logs.append(((top+row)*W+left+col, color))

    def frame(self, t, dt):
        W, H, fw, fh, rng = self.W, self.H, self.fw, self.fh, self.rng
        f = self.f
        rnd = rng.random
        base = (fh - 1) * fw
        flick = .92+.075*sin(t*1.8)*sin(t*.62)
        dcy = 2.4 * 255 / fh
        for x,(u,variation,hearth) in enumerate(self.fuel):
            tongues = .82+.12*sin(u*20+t*1.37)+.05*sin(u*46-t*2.05)
            f[base+x] = clamp8(255*flick*hearth*(tongues+variation+.09*rnd()))
        for y in range(fh - 2, -1, -1):
            r = y * fw
            b = r + fw
            b2 = b + fw if y < fh - 2 else b
            new = []
            for x in range(fw):
                xl = x - 1 if x else 0
                xr = x + 1 if x < fw - 1 else x
                s = (f[b + xl] + 2 * f[b + x] + f[b + xr] + f[b2 + x]) * 0.2
                s -= (.20+.62*rnd()) * dcy
                new.append(255 if s > 255 else int(s) if s > 0 else 0)
            f[r:r + fw] = new
        width, height = self.width, self.height
        visible_rows = (height + 1) // 2
        idx = f[(fh-visible_rows)*fw:]
        flames = up2(idx, fw, visible_rows, width, height, self.pal)
        out = self.bg[:]
        for row, (a, b) in enumerate(self.opening):
            dst = (self.top+row)*W+self.left
            src = row*width
            out[dst+a:dst+b] = flames[src+a:src+b]
        # embers
        if rnd() < (1-.57**(dt*type(self).fps) if self.gfx else .43) and len(self.embers) < 30:
            self.embers.append([self.left+rng.uniform(width*.10,width*.90), self.top+height-2*self.S, rng.uniform(-5,5)*self.S, -rng.uniform(8,22)*self.S, rng.uniform(1.5, 3.5), 0.0])
        keep = []
        for e in self.embers:
            e[5] += dt
            if e[5] > e[4]:
                continue
            e[0] += (e[2] + 6*self.S*sin(e[5]*5+e[0]/self.S)) * dt
            e[1] += e[3] * dt
            keep.append(e)
            lv = 1 - e[5] / e[4]
            x, y = int(e[0])-self.left, int(e[1])-self.top
            if 0 <= y < height:
                a, b = self.opening[y]
                if a <= x < b:
                    plota(out, W, H, x+self.left, y+self.top, shade(0xFFBE3C, int(256 * lv)))
        self.embers = keep
        for i, color in self.logs:
            out[i] = color
        return out
