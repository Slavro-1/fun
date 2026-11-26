"""Color and drawing primitives shared by the scene implementations."""
import math


sin = math.sin
cos = math.cos
sqrt = math.sqrt
atan2 = math.atan2
exp = math.exp
hypot = math.hypot
TAU = math.tau
PI = math.pi


# ====================================================================== colour
def clamp8(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def rgb(r, g, b):
    return (clamp8(r) << 16) | (clamp8(g) << 8) | clamp8(b)


def shade(c, f):
    """Scale brightness of packed colour c by f/256 (f: int, clamped to 0..256)."""
    if f <= 0:
        return 0
    if f > 256:
        f = 256
    return ((((c & 0xFF00FF) * f) >> 8) & 0xFF00FF) | ((((c & 0x00FF00) * f) >> 8) & 0x00FF00)


def mix(c1, c2, f):
    """Linear blend c1 -> c2, f is int 0..256."""
    return shade(c1, 256 - f) + shade(c2, f)


def addp(a, b):
    """Saturating per-channel add of two packed colours."""
    s = a + b
    m = (s ^ a ^ b) & 0x1010100
    if m:
        s = (s | (m - (m >> 8))) & 0xFFFFFF
    return s


def gradient(stops, n):
    """stops: [(pos 0..1, (r,g,b)), ...] -> list of n packed colours."""
    out = []
    last = len(stops) - 1
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        k = 0
        while k < last - 1 and t > stops[k + 1][0]:
            k += 1
        p0, c0 = stops[k]
        p1, c1 = stops[k + 1]
        u = 0.0 if p1 <= p0 else min(1.0, max(0.0, (t - p0) / (p1 - p0)))
        out.append(rgb(c0[0] + (c1[0] - c0[0]) * u, c0[1] + (c1[1] - c0[1]) * u,
                       c0[2] + (c1[2] - c0[2]) * u))
    return out


def cospal(n, a, b, c, d):
    """Inigo-Quilez cosine palette; a,b,c,d are (r,g,b) triples in 0..1 units."""
    out = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        out.append(rgb(*[255 * (a[k] + b[k] * cos(TAU * (c[k] * t + d[k]))) for k in range(3)]))
    return out


def vgrad(W, H, stops):
    buf = []
    for c in gradient(stops, H):
        buf += [c] * W
    return buf


# ================================================================== primitives
def plot(buf, W, H, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        buf[y * W + x] = c


def plota(buf, W, H, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        i = y * W + x
        a = buf[i]
        s = a + c
        m = (s ^ a ^ c) & 0x1010100
        if m:
            s = (s | (m - (m >> 8))) & 0xFFFFFF
        buf[i] = s


def _line_steps(W, H, x0, y0, x1, y1):
    dx = x1 - x0
    dy = y1 - y0
    if dx != dx or dy != dy or abs(dx) > 1e5 or abs(dy) > 1e5:
        return 0
    if (x0 < 0 and x1 < 0) or (y0 < 0 and y1 < 0) or (x0 >= W and x1 >= W) or (y0 >= H and y1 >= H):
        return 0
    return int(max(abs(dx), abs(dy))) + 1


def line_add(buf, W, H, x0, y0, x1, y1, c):
    n = _line_steps(W, H, x0, y0, x1, y1)
    if not n:
        return
    sx = (x1 - x0) / n
    sy = (y1 - y0) / n
    x = x0 + 0.5
    y = y0 + 0.5
    for _ in range(n + 1):
        if 0 <= x < W and 0 <= y < H:
            i = int(y) * W + int(x)
            a = buf[i]
            s = a + c
            m = (s ^ a ^ c) & 0x1010100
            if m:
                s = (s | (m - (m >> 8))) & 0xFFFFFF
            buf[i] = s
        x += sx
        y += sy


def line_set(buf, W, H, x0, y0, x1, y1, c):
    n = _line_steps(W, H, x0, y0, x1, y1)
    if not n:
        return
    sx = (x1 - x0) / n
    sy = (y1 - y0) / n
    x = x0 + 0.5
    y = y0 + 0.5
    for _ in range(n + 1):
        if 0 <= x < W and 0 <= y < H:
            buf[int(y) * W + int(x)] = c
        x += sx
        y += sy


def _gfx_line_set(buf, W, H, x0, y0, x1, y1, c, width=1.):
    _gfx_line(buf,W,H,x0,y0,x1,y1,c,False,width)


def _gfx_line_add(buf, W, H, x0, y0, x1, y1, c, width=1.):
    _gfx_line(buf,W,H,x0,y0,x1,y1,c,True,width)


def _gfx_line(buf, W, H, x0, y0, x1, y1, c, additive, width):
    """Blend a thin stroke over the two nearest samples of its minor axis."""
    if not _line_steps(W,H,x0,y0,x1,y1):
        return
    steep = abs(y1-y0) > abs(x1-x0)
    if steep:
        x0,y0,x1,y1 = y0,x0,y1,x1
    if x0 > x1:
        x0,x1,y0,y1 = x1,x0,y1,y0
    span = x1-x0
    slope = (y1-y0)/span if span else 0.
    major,minor = (H,W) if steep else (W,H)
    fringe = min(128, max(0,round(128*(width-1.))))
    for x in range(max(0,round(x0)),min(major,round(x1)+1)):
        y = y0+(x-x0)*slope
        base = math.floor(y)
        alpha = int((y-base)*256)
        samples = ((base,256-alpha),(base+1,alpha))
        if fringe:
            samples += ((base-1,(fringe*(256-alpha))>>8),(base+2,(fringe*alpha)>>8))
        for yy,weight in samples:
            if weight and 0 <= yy < minor:
                i = x*W+yy if steep else yy*W+x
                buf[i] = addp(buf[i],shade(c,weight)) if additive else mix(buf[i],c,weight)


def _gfx_point_rim(buf,W,H,x,y,color):
    plota(buf,W,H,x-1,y,color)
    plota(buf,W,H,x+1,y,color)
    plota(buf,W,H,x,y-1,color)
    plota(buf,W,H,x,y+1,color)


def make_sprite(color, r, levels=8, power=2.0):
    """Soft glow sprites: list (per brightness level) of (dx, dy, colour)."""
    out = []
    for lv in range(levels):
        k = (lv + 1) / levels
        pts = []
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                d = sqrt(dx * dx + dy * dy) / (r + 0.35)
                if d < 1.0:
                    c = shade(color, int((1 - d) ** power * k * 256))
                    if c:
                        pts.append((dx, dy, c))
        out.append(pts)
    return out


def stamp(buf, W, H, x, y, pts):
    for dx, dy, c in pts:
        xx = x + dx
        yy = y + dy
        if 0 <= xx < W and 0 <= yy < H:
            i = yy * W + xx
            a = buf[i]
            s = a + c
            m = (s ^ a ^ c) & 0x1010100
            if m:
                s = (s | (m - (m >> 8))) & 0xFFFFFF
            buf[i] = s


def fill_row(buf, W, y, x0, x1, c):
    if x1 > x0:
        buf[y * W + x0:y * W + x1] = [c] * (x1 - x0)


def up2(f, sw, sh, W, H, pal):
    """Upscale an int field (sw x sh, values index `pal`) 2x with linear
    interpolation in index space -> flat list of W*H packed colours."""
    out = []
    ext = out.extend
    get = pal.__getitem__
    rows = []
    for y in range(sh):
        r = f[y * sw:(y + 1) * sw]
        h = [0] * (2 * sw)
        h[0::2] = r
        h[1::2] = [(a + b) >> 1 for a, b in zip(r, r[1:] + r[-1:])]
        rows.append(h)
    rows.append(rows[-1])
    n = 0
    for y in range(sh):
        a = rows[y][:W]
        ext(map(get, a))
        n += 1
        if n >= H:
            break
        b = rows[y + 1][:W]
        ext(map(get, [(p + q) >> 1 for p, q in zip(a, b)]))
        n += 1
        if n >= H:
            break
    return out


SIN256 = [int(127.5 + 127.5 * sin(i * TAU / 256)) for i in range(256)]
