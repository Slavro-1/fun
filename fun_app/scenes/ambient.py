"""Ambient, geometric, and landscape scenes."""
import math
from operator import itemgetter

from .ambient_drawing import (
    _FieldGrid,
    _ambient_disc,
    _ambient_expand,
    _ambient_grid,
    _ambient_palette,
    _ambient_scale,
    _ambient_smooth,
    _ambient_stars,
)
from .base import Scene
from .drawing import (
    PI,
    TAU,
    _gfx_line_add,
    _gfx_line_set,
    _gfx_point_rim,
    addp,
    atan2,
    cos,
    cospal,
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
    shade,
    sin,
    sqrt,
    stamp,
    up2,
    vgrad,
)


class Koi(Scene):
    """Patterned koi wind through caustic light and flowering lily pads."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 52000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.scale = max(.26, _ambient_scale(W, H, self.S))
        self.grid = _FieldGrid(W,H,10_000) if self.gfx else None
        self.sw,self.sh = ((self.grid.sw,self.grid.sh) if self.grid
                           else _ambient_grid(W,H,2))
        self.water = _ambient_palette(((0, 0x06222B), (.56, 0x0B3B44), (.83, 0x145059), (1, 0x297270)))
        self.vignette = [[max(0., 139 - 140 * ((x / self.sw - .5)**2 + (y / self.sh - .48)**2))
                          for x in range(self.sw)] for y in range(self.sh)]
        colors = (0xFF6A1A, 0xF4EFE6, 0xFFB000, 0x242732, 0xF4EFE6, 0xDC4B2C, 0xE8AD50)
        self.fish = [(i * TAU / 7 + rng.uniform(-.14, .14), rng.uniform(.17, .29),
                      rng.uniform(.22, .39), self.scale * rng.uniform(.77, 1.13), c)
                     for i, c in enumerate(colors[:max(5, min(7, int(self.logical_area // 2000) + 1))])]
        self.pads = [(int(W * x), int(H * y), max(1, round(self.scale * r)), a, i % 3 != 1)
                     for i, (x, y, r, a) in enumerate(((.13,.21,7,1),(.21,.14,4,3),(.87,.26,7,4),
                                                       (.91,.34,4,2),(.12,.75,7,5),(.20,.80,5,1),
                                                       (.77,.86,6,3),(.86,.89,4,4)))]
        self.petals = [(rng.random()*W, rng.random()*H, rng.random()*TAU) for _ in range(12)]

    def _head(self, t, phase, fx, fy):
        W, H = self.W, self.H
        ax, ay = t * fx + phase, t * fy + phase * 1.38
        x = W * (.5 + .30 * cos(ax) + .055 * sin(2 * ay))
        y = H * (.5 + .29 * sin(ay) + .047 * cos(2 * ax))
        vx = W * (-.30 * fx * sin(ax) + .11 * fy * cos(2 * ay))
        vy = H * (.29 * fy * cos(ay) - .094 * fx * sin(2 * ax))
        angle = atan2(vy, vx)
        return x, y, cos(angle), sin(angle), hypot(vx,vy)

    def frame(self, t, dt):
        W, H = self.W, self.H
        # Rows share two axes of the caustic net; only the oblique leg varies per cell.
        p = t * .35
        field_scale = self.S * 2 / self.grid.step if self.grid else self.S
        ax = [sin(x*.42/field_scale+p) for x in range(self.sw)]
        bx = [sin(x*.26/field_scale-p*.84) for x in range(self.sw)]
        f = []
        for y, base in enumerate(self.vignette):
            a, b = sin(y*.53/field_scale-p*.75), y*.37/field_scale+p*.61
            f.extend(int(v + 91 * (1 - abs((u + a) * w * sin(x*.22/field_scale+b)) / 2)**7)
                     for x, (u, w, v) in enumerate(zip(ax, bx, base)))
        buf = self.grid.expand(f, self.water) if self.grid else up2(f, self.sw, self.sh, W, H, self.water)
        for i, (phase, fx, fy, s, c) in enumerate(self.fish):
            x, y, ux, uy, speed = self._head(t, phase, fx, fy)
            points = [(x,y,max(1,round(2.5*s)))]
            along = t
            px,py = x,y
            for k, width in enumerate((3.2, 3.9, 4.1, 3.8, 3.4, 2.9, 2.4, 1.8, 1.3, 1, .7),1):
                along -= min(.42,1.55*s/max(.2,speed))
                hx,hy,tx,ty,speed = self._head(along, phase, fx, fy)
                dx,dy = hx-px,hy-py
                length = hypot(dx,dy)
                if length < .12:
                    dx,dy,length = -tx,-ty,1.
                px,py = px+dx*1.55*s/length,py+dy*1.55*s/length
                sway = s*(k/11)**1.55*4.3*sin(t*5.8-k*.53+phase)
                points.append((px-sway*ty,py+sway*tx,max(1,round(width*s))))
            for px, py, r in points:
                ix, iy = round(px), round(py)
                if 0 <= ix < W and 0 <= iy < H:
                    _ambient_disc(buf, W, H, px+2*s, py+3*s, r, shade(buf[iy*W+ix], 148))
            for sign in (-1, 1):
                px, py, _ = points[3]
                fxp, fyp = px - ux*4*s - sign*uy*5.4*s, py - uy*4*s + sign*ux*5.4*s
                line_set(buf, W, H, px, py, fxp, fyp, shade(c, 172))
                line_set(buf, W, H, px-ux*s, py-uy*s, fxp, fyp, shade(c, 118))
            px, py, _ = points[-1]
            wx, wy, _ = points[-3]
            a = atan2(py-wy, px-wx)
            for k in range(-3, 4):
                wing = a + k*.22
                line_set(buf, W, H, px, py, px+cos(wing)*5.5*s, py+sin(wing)*5.5*s,
                         shade(c, 152 + (3-abs(k))*21))
            for k in range(11, -1, -1):
                px, py, r = points[k]
                pigment = c
                if i in (1, 4) and k in (1, 2, 5, 6, 9):
                    pigment = 0xDC511B if k != 6 else 0x33303A
                if i == 3 and 3 <= k <= 5:
                    pigment = 0xD8CFC0
                _ambient_disc(buf, W, H, px, py, r, shade(pigment, 147))
                _ambient_disc(buf, W, H, px - uy*.45*s, py - .55*s, max(0, r-1), pigment)
            for sign in (-1, 1):
                plot(buf, W, H, round(x - sign*uy*1.5*s), round(y + sign*ux*1.5*s), 0x1C1720)
        age = t % 8.3
        if age < 2.5:
            phase, fx, fy, _, _ = self.fish[int(t / 8.3) % len(self.fish)]
            x, y, _, _, _ = self._head(t-age, phase, fx, fy)
            r = self.scale * (2 + 10*age)
            c = shade(0x2A6B70, int(192 * sin(PI * age / 2.5)))
            samples = self.px(56)
            for k in range(samples):
                a = k*TAU/samples
                plota(buf, W, H, round(x+cos(a)*r), round(y+sin(a)*r), c)
        for x, y, r, a, flower in self.pads:
            _ambient_disc(buf, W, H, x+1, y+1, r, 0x0B2825)
            _ambient_disc(buf, W, H, x, y, r, 0x37624D)
            _ambient_disc(buf, W, H, x, y-1, max(0, r-1), 0x447958)
            for q in (-.22, 0, .22):
                line_set(buf, W, H, x, y, x+cos(a+q)*r, y+sin(a+q)*r, 0x0E3A40)
            if flower:
                for k in range(7):
                    p = k*TAU/7 + a
                    _ambient_disc(buf, W, H, x+cos(p)*r*.38, y+sin(p)*r*.38, r//3,
                                  0xFF9EC4 if k % 2 else 0xC9689F)
                plot(buf, W, H, x, y, 0xFFD49B)
        for x, y, p in self.petals:
            plot(buf, W, H, int((x + t*.7*self.S) % W), int((y + 2*self.S*sin(t*.31 + p)) % H), 0xC17A96)
        return buf


class Bokeh(Scene):
    """City lights drift across three depths while the lens slowly refocuses."""
    fps = 14
    mask = 0xF8F8F8
    gfx_pixels = 63000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.bg = vgrad(W, H, ((0,(7,9,15)), (.60,(12,15,22)), (1,(12,11,16))))
        for y in range(H):
            vertical = (2*y/max(1,H-1)-1)**2
            for x in range(W):
                horizontal = (2*x/max(1,W-1)-1)**2
                i = y*W+x
                self.bg[i] = shade(self.bg[i], 256-int(47*(horizontal+vertical)))
        self.colors = (0xFFA53D, 0xFFC779, 0xEF3830, 0x43C9B2, 0xE7F1F9)
        s = _ambient_scale(W, H, self.S)
        self.radii = [max(2,round(s*r)) for r in (4,7,11)]
        self.sprites = {}
        largest = max(self.radii)
        self.sprite_radii = sorted(set(self.radii+[1]+[max(1,round(largest*j/7)) for j in range(1,8)]))
        if not self.gfx:
            self.sprite_radii = list(range(1,largest+1))
        for color in self.colors:
            for r in self.sprite_radii:
                shape = []
                for y in range(-r, r+1):
                    for x in range(-r, r+1):
                        d = hypot(x, y)/(r+.2)
                        if d < 1.03:
                            edge = _ambient_smooth((1.03-d)/.24)
                            v = (.36+.34*(1-d*d))*edge
                            shape.append((x, y, v if r > 1 else 1-d*.62))
                self.sprites[color, r] = [[(x,y,pixel) for x,y,v in shape
                                           if (pixel := shade(color, int(v*level*32)))]
                                          for level in range(1,9)]
        self.lights = []
        for layer in range(3):
            n = max(5, min((24, 19, 12)[layer], int(self.logical_area//(465+layer*205))))
            for _ in range(n):
                color = rng.choices(self.colors, (33,23,15,14,15))[0]
                self.lights.append((layer, rng.uniform(-.08*W,1.08*W), rng.uniform(-.08*H,1.08*H),
                                    rng.uniform(-2,2)*self.S, rng.uniform(-1,1)*self.S, rng.random()*TAU, color))

    def frame(self, t, dt):
        W, H = self.W, self.H
        buf = self.bg[:]
        focus = min(1., _ambient_smooth((t%25-17)/2.5), _ambient_smooth((25-t%25)/2.5))
        for layer,x,y,vx,vy,p,color in self.lights:
            r = max(1,round(self.radii[layer]*(1-.94*focus)))
            if self.gfx:
                r = min(self.sprite_radii,key=lambda radius:abs(radius-r))
            u = .5+.5*sin(t*.38+p)
            lv = min(7, int(1+layer+u*3+focus*2))
            margin = self.radii[layer]
            x = int((x+t*vx*(layer+1)*.58+3*self.S*cos(t*.35+p)+margin)%(W+2*margin)-margin)
            y = int((y+t*vy*(layer+1)*.42+2*self.S*sin(t*.42+p)+margin)%(H+2*margin)-margin)
            stamp(buf,W,H,x,y,self.sprites[color,r][lv])
        return buf


class _ReflectionColors(dict):
    """Per-level lookup for repeated colors in a lantern reflection."""

    def __init__(self, colors, level):
        super().__init__((color, shade(color, level)) for color in colors)
        self.level = level
        self.limit = len(self) + 640

    def __missing__(self, color):
        dimmed = shade(color, self.level)
        if len(self) < self.limit:
            self[color] = dimmed
        return dimmed


class Lanterns(Scene):
    """Warm sky lanterns ascend over a dark lake that mirrors their glow."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 64000
    gfx_fps = 20

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.shore = int(H*.66)
        self.bg = vgrad(W,H,((0,(4,6,26)),(.43,(26,16,64)),(.66,(64,32,74)),(1,(6,10,26))))
        if self.gfx_reference:
            rw,rh = self.gfx_reference
            stars = [0]*(rw*rh)
            _ambient_stars(stars,rw,rh,rng,max(18,int(self.logical_area//170)),max(1,int(rh*.55)))
            for i,c in enumerate(stars):
                if c:
                    y,x = divmod(i,rw)
                    plota(self.bg,W,H,x*W//rw,y*H//rh,c)
        else:
            _ambient_stars(self.bg,W,H,rng,max(18,int(self.logical_area//170)),max(1,int(H*.55)))
        for x in range(W):
            for depth,c in enumerate((0x251A38,0x130F28,0x090D20)):
                y = int(self.shore-H*(.047-depth*.012)
                        -H*(.038-depth*.009)*(sin(x/W*10+depth*2)+.45*sin(x/W*24+depth)))
                y = max(0,min(self.shore,y))
                self.bg[y*W+x:self.shore*W+x:W] = [c]*(self.shore-y)
        s = max(.25, _ambient_scale(W,H,self.S))
        self.lanterns = [(rng.uniform(.05,.95)*W, rng.uniform(3,9)*s,
                          rng.randrange(3), rng.random()*TAU, rng.random()*(self.shore+12*self.S))
                         for _ in range(max(24,min(54,int(self.logical_area//335))))]
        self.reflection = None
        if self.gfx:
            colors = set(self.bg)
            self.reflection = [_ReflectionColors(colors, level) for level in range(84,115)]
        self.forms = []
        for depth in range(3):
            r = max(1,round(s*(2+depth)))
            h = max(2,round(s*(5+depth*2)))
            halo = make_sprite(0x9C4328, max(2,r*3), 6, 2.1)
            rows = [max(0,round(r*(.69+.30*sin(PI*(j+.5)/h)) - j/h*.65)) for j in range(h)]
            fills = [(shade(0xEF7D39,lv),shade(0xFFF2B0,lv),shade(0xFFAB4E,lv))
                     for lv in (85,115,146,175,210,244)]
            self.forms.append((h,rows,halo,fills))

    def frame(self,t,dt):
        W,H,L = self.W,self.H,self.shore
        buf = self.bg[:]
        for x,speed,depth,p,start in self.lanterns:
            h,rows,halo,fills = self.forms[depth]
            y = int(L-(t*speed+start)%(L+12*self.S))
            xi = int(x+self.S*((2+depth)*sin(t*.56+p)+1.5*sin(t*.19+p)))
            fade = min(1, max(0,(y+h)/max(1,H*.12)), max(0,(L-y)/(5*self.S)))
            if fade <= 0:
                continue
            lv = min(5,int((3.6+depth*.85+.46*sin(t*2.2+p))*fade))
            stamp(buf,W,H,xi,y,halo[lv])
            edge,core,base = fills[lv]
            for j,half in enumerate(rows):
                yy = y+j-h//2
                if 0 <= yy < L:
                    fill_row(buf,W,yy,max(0,xi-half),min(W,xi+half+1),edge if j < h-1 else base)
                    if j and half:
                        plot(buf,W,H,xi,yy,core)
            if depth and lv >= 3:
                plota(buf,W,H,xi+int(3*sin(t+p)),y+h//2+int((t*3+p)%6),0x663719)
        # Each lake row samples the composite sky so moving lanterns and hills reflect together.
        for y in range(L,H):
            sy = max(0,L-1-int((y-L)*1.22))
            shift = round(self.S*(2.1*sin(y*.64/self.S-t*1.15)+1.5*sin(y*.23/self.S+t*.71)))
            row = buf[sy*W:(sy+1)*W]
            row = row[shift:]+row[:shift]
            level = 99 + int(15*sin(y*.74/self.S+t*.64))
            if self.reflection:
                reflection = list(map(self.reflection[level-84].__getitem__, row))
            else:
                reflection = [shade(c,level) for c in row]
            buf[y*W:(y+1)*W] = reflection
        return buf


class Nebula(Scene):
    """Warped clouds and diffraction stars drift through a stellar nursery."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 57000
    gfx_fps = 20

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.grid = _FieldGrid(W,H,13_000) if self.gfx else None
        self.sw,self.sh = ((self.grid.sw,self.grid.sh) if self.grid
                           else _ambient_grid(W,H,2))
        self.pal = _ambient_palette(((0,0x030311),(.28,0x100A2F),(.46,0x211748),
                                    (.60,0x126E70),(.70,0x337E89),(.80,0x8F2683),
                                    (.92,0xE94C85),(1,0xFFC971)))
        self.field = []
        for y in range(self.sh):
            v = y/self.sh-.5
            for x in range(self.sw):
                u = x/self.sw-.5
                a = u*12.8+v*6.6 + 1.42*sin(v*10-u*4)
                b = v*14.4-u*7.9 + 1.90*cos(u*10+v*5)
                self.field.append((a,b,a*2.1+b*.43,max(0,1-1.25*u*u-2.18*v*v)))
        self.stars = [(self.detail_coord(W),self.detail_coord(H, True),rng.random()*TAU,
                       rng.choice((0xFFDAAA,0x9DBEFF,0xCCD9FF)),rng.randrange(38,160))
                      for _ in range(max(38,min(245,int(self.logical_area//53))))]
        self.glow = make_sprite(0xEA5685,max(3,round(12*_ambient_scale(W,H,self.S))),8,2.2)

    def frame(self,t,dt):
        W,H = self.W,self.H
        p = t*.055
        idx = [int(max(0,min(255, 39 + g*(74+58*sin(a+p+.64*sin(b-p*.67))
                                          +37*cos(b+p*.53)+31*sin(c-p*.79)))))
               for a,b,c,g in self.field]
        buf = self.grid.expand(idx, self.pal) if self.grid else up2(idx,self.sw,self.sh,W,H,self.pal)
        drift = int(t*.125*self.S)%W
        rim = min(105, round(100*max(0., self.detail_scale-1.)))
        for i,(x,y,a,c,v) in enumerate(self.stars):
            xi = (x+drift)%W
            lv = int(v*(.75+.24*sin(t*.92+a)))
            light = shade(c,lv)
            plota(buf,W,H,xi,y,light)
            if rim:
                _gfx_point_rim(buf,W,H,xi,y,shade(light,rim))
            if i%19 == 0:
                for d in (-2,-1,1,2):
                    glint = shade(c,lv//(2+abs(d)))
                    plota(buf,W,H,xi+round(d*self.S),y,glint)
                    plota(buf,W,H,xi,y+round(d*self.S),glint)
        for x,y,a in ((.40,.39,0),(.68,.59,2.7),(.52,.67,1.4)):
            xi,yi = int(W*x+W*.024*sin(p+a)),int(H*y+H*.022*cos(p+a))
            stamp(buf,W,H,xi,yi,self.glow[4+int(2+1.9*sin(p*4+a))])
            plota(buf,W,H,xi,yi,0xF2AE89)
        return buf


class Prism(Scene):
    """A rotating glass prism bends a white beam into a soft spectrum."""
    fps = 14
    mask = 0xF8F8F8
    gfx_pixels = 64000

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [0x060712]*(W*H)
        self.grains = [(rng.random(),rng.uniform(-2,2)*self.S,rng.random()*TAU) for _ in range(21)]
        self.spectrum = [(c,shade(c,106),shade(c,46),shade(c,20))
                         for c in (0xFF2A2A,0xFF8A1F,0xFFE11F,0x3BFF5A,0x1FD5FF,0x3A52FF,0xA83BFF)]
        self.glint = make_sprite(0xACC9E1,max(2,round(min(W,H)*.074)),8,2)

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        s = min(W,H)
        cx,cy = W*.47,H*.49
        spin = .435*sin(t*.31)
        corners = [(cx+s*.24*cos(a+spin),cy+s*.24*sin(a+spin))
                   for a in (-PI/2,PI/6,5*PI/6)]
        beam = cy+s*.025*sin(t*.48+.7)
        edges = list(zip(corners,corners[1:]+corners[:1]))
        entry = min(ax+(bx-ax)*(beam-ay)/(by-ay)
                    for ((ax,ay),(bx,by)) in edges if min(ay,by) <= beam < max(ay,by))
        (ax,ay),(bx,by) = corners[:2]
        out_y = beam+s*(.047+.06*sin(spin))
        out_x = ax+(bx-ax)*(out_y-ay)/(by-ay)
        # Fill the triangle and shade the glass toward its upper facet.
        for y in range(max(0,math.ceil(min(p[1] for p in corners))),
                       min(H,math.ceil(max(p[1] for p in corners)))):
            hits = [a+(c-a)*(y-b)/(d-b) for (a,b),(c,d) in edges if min(b,d) <= y < max(b,d)]
            if len(hits) == 2:
                fill_row(buf,W,y,max(0,math.ceil(min(hits))),min(W,math.ceil(max(hits))),
                         mix(0x173043,0x0B1022,int(256*(y-min(p[1] for p in corners))/(s*.48))))
        for j,colors in enumerate(self.spectrum):
            pulse = int(171+28*sin(t*.61+j*.13))
            colors = tuple(shade(c,pulse) for c in colors)
            for x in range(max(0,math.ceil(out_x)),W):
                d = x-out_x
                center = int(out_y+d*(.20+spin*.53+(j-3)*.087))
                width = self.px(1)+int(d*.029)
                for k in range(-width-2,width+3):
                    band = max(0,abs(k)-width+1)
                    plota(buf,W,H,x,center+k,colors[min(3,band)])
        stroke = _gfx_line_set if self.gfx else line_add
        for (x0,y0),(x1,y1) in edges:
            line_add(buf,W,H,x0,y0+1,x1,y1+1,0x1C3D52)
            stroke(buf,W,H,x0,y0,x1,y1,0x4F8398)
        for k,c in ((-2,0x0B1020),(-1,0x2D3B4C),(1,0x293242),(2,0x0B1020),(0,0xB5BDC6)):
            line_add(buf,W,H,0,beam+k*self.S,entry,beam+k*self.S,c)
        stroke(buf,W,H,entry,beam,out_x,out_y,0x667585)
        line_add(buf,W,H,entry,beam-1,out_x,out_y-1,0x25394A)
        stamp(buf,W,H,round(entry),round(beam),self.glint[6])
        line_add(buf,W,H,entry,beam-s*.055,entry,beam+s*.055,0x344B61)
        for i,(x,y,p) in enumerate(self.grains):
            plot(buf,W,H,int(((x+t*.06)%1)*entry),round(beam+y),
                 shade(0xE8EDFF,int(139+95*sin(t*.76+p))))
        return buf


class Flyover(Scene):
    """A banked golden-hour flight over interpolated volcanic ridges."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 55000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W,H = self.W,self.H
        self.bg = vgrad(W,H,((0,(27,42,90)),(.21,(83,72,117)),(.42,(216,122,105)),
                             (.57,(255,155,112)),(1,(233,160,124))))
        r = max(2,round(min(W,H)*.048))
        x,y = round(W*.74),round(H*.30)
        stamp(self.bg,W,H,x,y,make_sprite(0xBB752B,r*5,3,2.2)[-1])
        stamp(self.bg,W,H,x,y,make_sprite(0xFFE0A0,r*2,1,2.)[0])
        _ambient_disc(self.bg,W,H,x,y,r,0xFFE1A2)
        axis = [i*TAU/256 for i in range(256)]
        self.height = [22+13*sin(2*x+y)+9*cos(3*y-x)
                       +11*abs(sin(4*x-3*y))**1.7+3*sin(13*x+8*y)+2*cos(21*y-11*x)
                       for y in axis for x in axis]
        earth = _ambient_palette(((0,0x122520),(.33,0x315344),(.52,0x557055),
                                   (.66,0x6D5C56),(.80,0xC09272),(.88,0xD9BAAA),(1,0xFFF0DB)),64)
        self.terrain = []
        for y in range(256):
            for x in range(256):
                i = y*256+x
                a = self.height[i]
                dx = self.height[y*256+((x+1)&255)]-self.height[y*256+((x-1)&255)]
                dy = self.height[((y+1)&255)*256+x]-self.height[((y-1)&255)*256+x]
                ink = shade(earth[max(0,min(63,round(a)))],int(205-11*dx+8*dy))
                self.terrain.append(ink)
        self.layers = []
        z = 2.6
        while z < 194:
            distance_fog = 1-exp(-z/116)
            glare = .20*exp(-z/15)
            self.layers.append((z,H*.83/z,int(248*(distance_fog+glare))))
            z += .37+z*.16 if z<17 else .72+z*.20

    def _height(self,x,y):
        ix,iy = math.floor(x),math.floor(y)
        u,v = x-ix,y-iy
        ht = self.height
        a,b = (iy&255)*256,((iy+1)&255)*256
        c,d = ix&255,(ix+1)&255
        h0,h1 = ht[a+c],ht[b+c]
        return h0+(ht[a+d]-h0)*u+(h1-h0)*v+((ht[b+d]-h1)-(ht[a+d]-h0))*u*v

    @staticmethod
    def _terrain_ink(terrain, ix, iy, u, v, fog):
        row,next_row = (iy&255)*256,((iy+1)&255)*256
        left,right = ix&255,(ix+1)&255
        horizontal = int(256*u)
        a = mix(terrain[row+left],terrain[row+right],horizontal)
        b = mix(terrain[next_row+left],terrain[next_row+right],horizontal)
        return mix(mix(a,b,int(256*v)),0xE9A07C,fog)

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        cx,cy = 120+44*sin(t*.085),t*12
        a = .48*cos(t*.085)
        fx,fy = sin(a),cos(a)
        altitude = 21+.74*self._height(cx,cy)+.26*self._height(cx+fx*16,cy+fy*16)+1.15*sin(t*.62)
        shear = .057*sin(t*.085)
        horizon = H*.43-W*.5*shear
        top = [H]*W
        ht,terrain = self.height,self.terrain
        floor,ceil = math.floor,math.ceil
        stride = 3 if W*H<=75_000 else 4
        fractions = [i/stride for i in range(stride)]
        weights = [round(256*f) for f in fractions]
        for z,zoom,fade in self.layers:
            x0,y0 = cx+z*(fx-fy*.67),cy+z*(fy+fx*.67)
            dx,dy = z*fy*1.34/W,-z*fx*1.34/W
            last_y = horizon+(altitude-self._height(x0,y0))*zoom
            previous = (floor(x0),floor(y0),x0%1,y0%1)
            for start in range(0,W,stride):
                end = start+stride
                x,y = x0+end*dx,y0+end*dy
                ix,iy = floor(x),floor(y)
                u,v = x-ix,y-iy
                left,right = ix&255,(ix+1)&255
                row,next_row = (iy&255)*256,((iy+1)&255)*256
                a,b = ht[row+left],ht[next_row+left]
                terrain_y = a+(ht[row+right]-a)*u
                terrain_y += (b+(ht[next_row+right]-b)*u-terrain_y)*v
                next_y = horizon+end*shear+(altitude-terrain_y)*zoom
                delta = next_y-last_y
                start_color = end_color = None
                for offset in range(min(stride,W-start)):
                    x = start+offset
                    edge = last_y+delta*fractions[offset]
                    top_y = max(0,ceil(edge))
                    old_top = top[x]
                    if top_y >= old_top:
                        continue
                    if start_color is None:
                        start_color = self._terrain_ink(terrain,*previous,fade)
                        end_color = self._terrain_ink(terrain,ix,iy,u,v,fade)
                    ink = mix(start_color,end_color,weights[offset]) if offset else start_color
                    buf[top_y*W+x:old_top*W+x:W] = [ink]*(old_top-top_y)
                    if top_y and top_y-edge>.04:
                        i = (top_y-1)*W+x
                        buf[i] = mix(buf[i],ink,int(256*(top_y-edge)))
                    top[x] = top_y
                last_y = next_y
                previous = ix,iy,u,v
        return buf


class Attractor(Scene):
    """Three luminous trajectories reveal four strange attractors in perspective."""
    fps = 13
    mask = 0xF0F0F0

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [shade(0x10132D, int(28+53*max(0,1-3*((x/W-.5)**2+(y/H-.5)**2))))
                   for y in range(H) for x in range(W)]
        _ambient_stars(self.bg,W,H,rng,max(16,int(self.logical_area//280)),H)
        self.ramps = [_ambient_palette(((0,0x030617),(.37,a),(.79,b),(1,0xFFF1E7)),64)
                      for a,b in ((0x243C9F,0x55E6FF),(0x8B2F80,0xFFB358),(0x155C59,0x81FFCD))]
        self.head_glow = make_sprite(0xA788C2,max(2,self.px(2)),1,2.)[0]
        self.length = 1280
        stride = 7 if self.gfx else 9
        tail = 360
        self.ages = (*range(self.length-1,tail,-stride),
                     *range(tail,-1,-(3 if self.gfx else 4)))
        self.trail_colors = []
        for ramp in self.ramps:
            colors = []
            for age in self.ages:
                p = 1-age/self.length
                colors.append(shade(ramp[int(63*p)],int(23+118*p*p)))
            self.trail_colors.append(colors)
        self.mode = None
        self.bundle = None
        self.advance_remainder = 0.
        self.steps = (.008,.018,.073,.015)
        self.normalize = ((0,0,24,.080),(0,0,.75,.84),(0,0,0,.46),(0,0,0,.19))
        self.seeds = ((1.,1.,18.),(.18,.19,.09),(.13,1.,-.31),(-4.,-.8,2.))

    @staticmethod
    def _flow(mode,x,y,z):
        if mode == 0:
            return 10*(y-x),x*(28-z)-y,x*y-(8/3)*z
        if mode == 1:
            return (z-.7)*x-3.5*y,3.5*x+(z-.7)*y,.6+.95*z-z*z*z/3-(x*x+y*y)*(1+.25*z)+.1*z*x*x*x
        if mode == 2:
            return sin(y)-.208186*x,sin(z)-.208186*y,sin(x)-.208186*z
        return -1.89*x-4*y-4*z-y*y,-1.89*y-4*z-4*x-z*z,-1.89*z-4*x-4*y-x*x

    def _advance(self, mode, bundle, steps):
        h = self.steps[mode]
        for trail in bundle:
            points,head = trail
            x,y,z = points[head]
            for _ in range(steps):
                dx,dy,dz = self._flow(mode,x,y,z)
                dx,dy,dz = self._flow(mode,x+.5*h*dx,y+.5*h*dy,z+.5*h*dz)
                x,y,z = x+h*dx,y+h*dy,z+h*dz
                head = (head+1)%len(points)
                points[head] = (x,y,z)
            trail[1] = head

    def _bundle(self,mode):
        x,y,z = self.seeds[mode]
        bundle = []
        for i in range(3):
            trail = [[(x+i*.0017,y-i*.001,z)]*self.length,0]
            self._advance(mode,[trail],self.length+340+i*146)
            bundle.append(trail)
        return bundle

    @staticmethod
    def _trail_segment(buf,width,x0,y0,x1,y1,color):
        # Projection already fits the complete polyline inside the framebuffer.
        dx,dy = abs(x1-x0),-abs(y1-y0)
        step_x = 1 if x1>x0 else -1
        step_y = width if y1>y0 else -width
        offset = y0*width+x0
        error = dx+dy
        for _ in range(max(dx,-dy)):
            previous = buf[offset]
            total = previous+color
            overflow = (total^previous^color)&0x1010100
            if overflow:
                total = (total|(overflow-(overflow>>8)))&0xFFFFFF
            buf[offset] = total
            e2 = error+error
            if e2>=dy:
                error += dy
                offset += step_x
            if e2<=dx:
                error += dx
                offset += step_y

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        section = t/70
        cycle = int(section)
        mode = cycle%4
        if self.mode != cycle:
            self.mode = cycle
            self.bundle = self._bundle(mode)
        phase = section%1
        fade = _ambient_smooth(min(phase,1-phase)/.033) if cycle or phase>.5 else 1.
        a = (t*.093)%TAU
        ca,sa = cos(a),sin(a)
        pitch = .29+.17*sin(t*.071)
        cp,sp = cos(pitch),sin(pitch)
        zoom = min(W,H)*(1.07+.11*sin(t*.027))
        steps = 4
        if self.gfx:
            self.advance_remainder += dt*type(self).fps*4
            steps = int(self.advance_remainder)
            self.advance_remainder -= steps
        length = self.length
        self._advance(mode,self.bundle,steps)
        ox,oy,oz,s = self.normalize[mode]
        projected = []
        extent = 1.
        for points,head in self.bundle:
            trace = []
            for age in self.ages:
                x,y,z = points[(head-age)%length]
                x,y,z = (x-ox)*s,(y-oy)*s,(z-oz)*s
                u,w = x*ca-z*sa,x*sa+z*ca
                v = y*cp-w*sp
                z = 4.1+y*sp+w*cp
                k = zoom/max(.65,z)
                px,py = u*k,v*k
                extent = max(extent,abs(px)/(W*.43),abs(py)/(H*.42))
                trace.append((px,py))
            projected.append(trace)
        fit = 1/extent
        fade_level = int(256*fade)
        for trace,colors in zip(projected,self.trail_colors):
            old_x = old_y = None
            for (x,y),age,color in zip(trace,self.ages,colors):
                px,py = W*.5+x*fit,H*.5-y*fit
                ix,iy = round(px),round(py)
                if fade_level<256:
                    color = shade(color,fade_level)
                if old_x is not None and color:
                    if self.gfx and age<102:
                        _gfx_line_add(buf,W,H,prev_x,prev_y,px,py,color)
                    elif ix!=old_x or iy!=old_y:
                        self._trail_segment(buf,W,old_x,old_y,ix,iy,color)
                old_x,old_y = ix,iy
                prev_x,prev_y = px,py
            if old_x is not None and fade:
                x,y = old_x,old_y
                stamp(buf,W,H,x,y,self.head_glow)
                plota(buf,W,H,x,y,shade(0xFFF0C3,int(239*fade)))
        return buf


class Jellyfish(Scene):
    """Pulsing translucent bells tow bioluminescent tentacles through falling marine snow."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 64000
    gfx_fps = 20

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = vgrad(W,H,((0,(3,20,39)),(.5,(4,15,33)),(1,(0,4,13))))
        self.snow = [(self.detail_coord(W),self.detail_coord(H,True),rng.uniform(.5,2.8),rng.random()*TAU)
                     for _ in range(max(24,min(180,int(self.logical_area//95))))]
        self.jellies = []
        colors = (0x738DEE,0x5BCAF3,0xA98BFF,0xFF6BD6,0x8FF7FF,0xED9BD7,0x8FF7FF)
        for i,c in enumerate(colors[:max(5,min(7,int(self.logical_area//4800)+4))]):
            phase = rng.random()*TAU
            size = max(2,min(16*self.S,min(W,H)*(.058+i*.014)))
            x = W*(.10+(.79*i/6))
            y = H*(.22 + (.23 if i%2 else 0)+.13*sin(phase))
            chains = []
            for j in range(6):
                anchor = (j-2.5)/3.0
                nodes = [[x+size*anchor,y+k*size*.28,x+size*anchor,y+k*size*.28] for k in range(12)]
                chains.append((anchor,nodes))
            bell = []
            inner_color = mix(c, 0xECF7FF, 96)
            for width in range(1,round(size)+2):
                height = max(2,round(width*.65))
                shape = []
                for yy in range(-height,self.px(2)):
                    for xx in range(-width,width+1):
                        q = xx*xx/(width+.5)**2 + yy*yy/(height+.5)**2
                        if q <= 1:
                            edge = q>.71 or yy==self.px(2)-1
                            rib = yy < 0 and (xx % max(2,width//3) == 0)
                            level = (95 if edge else 29)+(55 if rib else 0)+int(34*(1-q))
                            color = shade(c,level)
                            if self.gfx and yy < 0:
                                core = ((xx/(width+.5))**2
                                        + ((yy+height*.37)/(height+.5))**2)
                                glow = int(121*max(0., 1.-2.35*core)*(1-q))
                                color = addp(color, shade(inner_color, glow))
                            shape.append((xx,yy,color))
                bell.append(shape)
            self.jellies.append([x,y,size,phase,c,chains,bell,0.,None,None])

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        rays = ((.12,.21),(.39,.16),(.71,.12),(.91,-.2))
        filament = min(1.55, self.detail_scale) if self.detail_scale >= 1.24 else 1.
        for j,(x,v) in enumerate(rays):
            bend = .026*sin(t*.17+j)
            for k in range(-2,3):
                line_add(buf,W,H,W*x+k*self.S,0,W*(x+v+bend)+k*2*self.S,H*.62,0x010306)
        for x,y,v,p in self.snow:
            plota(buf,W,H,int((x+2*self.S*sin(t*.27+p))%W),int((y+t*v*self.S)%H),
                  shade(0x6E96AB,int(26+23*v+12*sin(t*.65+p))))
        for i,jelly in enumerate(self.jellies):
            ox,oy,size,phase,c,chains,bell,drift,previous,last_x = jelly
            p = (t+phase)%2.9
            contract = _ambient_smooth(p/.35)*(1-_ambient_smooth((p-.35)/1.9))
            if previous is not None and p < previous:
                drift -= size*.70
            jelly[7] = drift*exp(-dt*2.0)
            jelly[8] = p
            x = ox+min(W*.075,size*1.35)*sin(t*.29+phase)
            y = oy+H*.13*sin(t*.21+phase)+size*.38*cos(t*.36+phase)+drift
            if size > min(W,H)*.112:
                y += H*.17*sin(t*.092+phase*.44)
            if i >= 5:
                # The outer lane is wide enough for the complete bell and chains to leave view.
                x = (x + t*W*.013 + 2.5*size)%(W+5*size) - 2.5*size
                if last_x is None or abs(x-last_x)>W*.55:
                    for anchor,nodes in chains:
                        for k,node in enumerate(nodes):
                            nx,ny = x+anchor*size,y+k*size*.31
                            node[:] = [nx,ny,nx,ny]
            jelly[9] = x
            r = max(1,round(size*(1-.29*contract)))
            gap = max(.7,size*.38)
            for j,(anchor,nodes) in enumerate(chains):
                nodes[0][:] = [x+anchor*r,y+self.S,x+anchor*r,y+self.S]
                force = .13*self.S*sin(t*1.85+phase+j*.72)
                for node in nodes[1:]:
                    nx,ny,px,py = node
                    node[:] = [nx+(nx-px)*.81+force,ny+(ny-py)*.81+.20*self.S,nx,ny]
                for _ in range(2):
                    for k in range(1,len(nodes)):
                        nx,ny,px,py = nodes[k]
                        dx,dy = nx-nodes[k-1][0],max(gap*.26,ny-nodes[k-1][1])
                        pull = gap/max(.05,hypot(dx,dy))
                        nodes[k][0] = nodes[k-1][0]+dx*pull
                        nodes[k][1] = nodes[k-1][1]+dy*pull
                for k in range(1,len(nodes)):
                    a,b = nodes[k-1],nodes[k]
                    cc = shade(c,max(15,(121 if j in (2,3) else 94)-8*k))
                    line_add(buf,W,H,a[0],a[1],b[0],b[1],cc)
                    if self.gfx:
                        offset = self.S*.52
                        _gfx_line_add(buf,W,H,a[0]+offset,a[1],b[0]+offset,b[1],shade(cc,108),filament)
                    elif j in (2,3) and k < 6:
                        line_add(buf,W,H,a[0]+self.S,a[1],b[0]+self.S,b[1],shade(cc,115))
                a = nodes[int((t*2.4+j+phase)%len(nodes))]
                plota(buf,W,H,round(a[0]),round(a[1]),shade(c,116))
            stamp(buf,W,H,round(x),round(y),bell[r-1])
            plota(buf,W,H,round(x),round(y-1),shade(0xFFB86B,int(52+86*contract)))
        return buf


class Dunes(Scene):
    """Five drifting desert dunes glow under a low moon and streaming sand."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 68000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = vgrad(W,H,((0,(13,27,74)),(.33,(65,52,111)),(.49,(138,79,160)),
                             (.57,(242,160,123)),(1,(99,53,87))))
        _ambient_stars(self.bg,W,H,rng,max(14,int(self.logical_area//241)),max(1,int(H*.40)))
        r = max(1,round(min(W,H)*.053))
        x,y = round(W*.68),round(H*.33)
        stamp(self.bg,W,H,x,y,make_sprite(0x9D6549,r*6,4,2.1)[-1])
        _ambient_disc(self.bg,W,H,x,y,r,0xFFE9B0)
        self.layers = []
        for i,(front,back,crest) in enumerate(((0x62405F,0x875876,0xA983A1),(0x583455,0xA66B73,0xC58689),
                                                (0x49273C,0xBD795B,0xD49269),(0x33213A,0x895044,0xBC7260),
                                                (0x201628,0x532E39,0x966052))):
            self.layers.append((front,back,crest,rng.random()*TAU))
        self.grains = [(rng.randrange(5),rng.random(),rng.uniform(3,13),rng.random()*TAU)
                       for _ in range(max(28,min(136,int(self.logical_area//105))))]

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        for y in range(int(H*.49),int(H*.58)):
            row = buf[y*W:(y+1)*W]
            shift = round(1.2*self.S*sin(y*1.43/self.S+t*.96))
            if shift:
                row = row[shift:]+row[:shift]
            tint = shade(0x302333,int(23*(1+sin(t*.85+y*1.2/self.S))))
            buf[y*W:(y+1)*W] = [addp(c,tint) for c in row]
        crests = []
        for i,(shadow,light,edge,p) in enumerate(self.layers):
            positions = []
            for x in range(W):
                a = (x+t*.15*self.S*(i+1))/W*(7.9+i*1.1)+p
                b = sin(a)+.44*sin(2*a+.78)+.23*sin(3*a-1)+.18*cos(a*.54-i)
                y = max(0,min(H-1,int(H*(.545+i*.084)-H*(.045+i*.005)*b)))
                positions.append(y)
                slope = cos(a)+.88*cos(2*a+.78)+.69*cos(3*a-1)
                cover = (.5+.5*sin(a+.20))**1.2
                face = mix(shadow,light,int(183*cover+32*max(0,cos(slope))))
                buf[y*W+x::W] = [face]*(H-y)
                buf[y*W+x] = shade(edge,int(130+85*cover))
                if y+1 < H:
                    buf[(y+1)*W+x] = mix(edge,face,149)
            crests.append(positions)
        for i,x,v,p in self.grains:
            xi = int((x*W+t*v*self.S)%W)
            fade = sin(t*.88+p)
            y = crests[i][xi]-int(1+(1+fade)*max(1,H*.026))
            if any(y >= crests[k][xi] for k in range(i+1,len(crests))):
                continue
            plota(buf,W,H,xi,y,shade(0xF8B07A,int(27+29*max(0,fade))))
            if fade > .3:
                plota(buf,W,H,xi-1,y,0x21141C)
        age = (t+10)%153
        if 13 < age < 41:
            for j in range(5):
                x = int(W*(1.12-(age-13)/24))+j*max(4,W//26)
                if 0 <= x < W:
                    y = crests[2][x]
                    if y < crests[3][x] and y < crests[4][x]:
                        for dx,dy in ((0,-2),(1,-2),(2,-3),(0,-1),(2,-1),(1,-3)):
                            plot(buf,W,H,x+round(dx*self.S),y+round(dy*self.S),0x262035)
        return buf


class Orrery(Scene):
    """Brass zodiac ticks frame an antique orrery with seven illuminated worlds."""
    fps = 13

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [shade(0x101B35,int(30+54*max(0,1-2*((x/W-.5)**2+(y/H-.5)**2))))
                   for y in range(H) for x in range(W)]
        _ambient_stars(self.bg,W,H,rng,max(17,int(self.logical_area//180)),H)
        self.scale = min(W,H)
        self.radius = self.scale*.45
        tick_gap = 2*max(1.,self.detail_scale)
        width = max(1., min(1.65, self.detail_scale))
        for k in range(120):
            a = k*TAU/120
            length = (.107 if k%10==0 else .043 if k%5==0 else .017)
            x,y = W/2+self.radius*cos(a),H/2+self.radius*.82*sin(a)
            x1 = W/2+self.radius*(1-length)*cos(a)
            y1 = H/2+self.radius*(1-length)*.82*sin(a)
            color = shade(0xB08D57,180 if k%10==0 else 86)
            if self.gfx:
                _gfx_line_set(self.bg,W,H,x,y,x1,y1,color,width)
            else:
                line_set(self.bg,W,H,x,y,x1,y1,color)
            if k%2:
                plot(self.bg,W,H,round(W/2+(self.radius+tick_gap)*cos(a)),
                     round(H/2+(self.radius+tick_gap)*.82*sin(a)),0x55402B)
        self.sun = make_sprite(0xFF8727,max(3,round(self.scale*.174)),8,2.25)
        self.orbits = [(r,e,w,rng.random()*TAU,rng.random()*TAU,c,k)
                       for r,e,w,c,k in ((.16,.10,1.02,0xB6A898,.58),(.26,.12,.67,0xF3CA83,.92),
                                         (.37,.14,.46,0x59A8CE,.91),(.48,.16,.33,0xD7754A,.70),
                                         (.65,.11,.205,0xE0AB78,1.44),(.79,.13,.155,0xD2AF81,1.15),
                                         (.91,.08,.105,0x83C7D7,.92))]
        self.asteroids = [(rng.uniform(.53,.59),rng.random()*TAU,rng.uniform(.24,.30),
                           rng.randrange(37,131)) for _ in range(max(32,min(120,int(self.logical_area//84))))]

    def frame(self,t,dt):
        W,H = self.W,self.H
        cx,cy = W*.5,H*.5
        buf = self.bg[:]
        a = t*TAU/240
        ca,sa = cos(a),sin(a)
        radius = self.radius
        bodies = []
        sunr = max(1,round(self.scale*.054))
        stamp(buf,W,H,round(cx),round(cy),self.sun[5+int(1.9+1.08*sin(t*2.5))//2])
        for i,(r,e,w,start,tilt,c,size) in enumerate(self.orbits):
            u,v = cos(tilt),sin(tilt)
            def project(q):
                x = radius*r*(cos(q)-e)
                y = radius*r*sin(q)*sqrt(1-e*e)
                X,Y = x*(u*ca-v*sa)-y*(v*ca+u*sa), x*(v*ca+u*sa)+y*(u*ca-v*sa)
                depth = Y*.57
                factor = 1+depth/(3*radius)
                return cx+X*factor,cy+Y*.82*factor,depth
            count = 24+i*10
            for k in range(count):
                x,y,z = project(k*TAU/count)
                plota(buf,W,H,round(x),round(y),0x362B20 if z>0 else 0x211C19)
            phase = t*w+start
            phase += e*sin(phase)
            x,y,z = project(phase)
            for k in range(1,15):
                X,Y,_ = project(phase-k*.068)
                plota(buf,W,H,round(X),round(Y),shade(c,(15-k)*7))
            rbody = max(1,round(size*self.scale*.029*(1+z/(3*radius))))
            bodies.append((z,i,x,y,rbody,c))
            for m in range(1 if i==2 else 2 if i==4 else 0):
                q = t*(1.7-m*.47)+m*2.3+i
                distance = rbody+(2.1+m*2)*self.S
                bodies.append((z+distance*sin(q)*.7,-2,x+distance*cos(q),
                               y+distance*sin(q)*.65,0,0xAFA7A1))
        for r,p,v,l in self.asteroids:
            q = p+t*v+a
            x,y = radius*r*cos(q),radius*r*sin(q)
            z = y*.57
            fac = 1+z/(3*radius)
            plota(buf,W,H,round(cx+x*fac),round(cy+y*fac*.82),shade(0xBC926A,l))
        bodies.append((0,-1,cx,cy,sunr,0xFFBD55))
        for z,i,x,y,r,c in sorted(bodies):
            if i == -2:
                plot(buf,W,H,round(x),round(y),c)
                continue
            if i == 5:
                for k in range(self.px(25),self.px(48)):
                    q = k*TAU/self.px(48)
                    self._ring(buf,x,y,r,q)
            _ambient_disc(buf,W,H,x,y,r,shade(c,142))
            if i == -1:
                _ambient_disc(buf,W,H,x-.4,y-.45,max(1,r-1),0xFFBA56)
                _ambient_disc(buf,W,H,x-1,y-1,max(0,r-2),0xFFF2A8)
            else:
                direction = atan2(cy-y,cx-x)
                _ambient_disc(buf,W,H,x+cos(direction)*.65,y+sin(direction)*.65,max(0,r-1),c)
                if i == 2:
                    plot(buf,W,H,round(x+.5*sin(t)),round(y-.6),0x72B07A)
                if i == 4:
                    line_set(buf,W,H,x-r*.7,y,x+r*.6,y-.2,0x906D58)
            if i == 5:
                for k in range(self.px(25)):
                    self._ring(buf,x,y,r,k*TAU/self.px(48))
        return buf

    def _ring(self,buf,x,y,r,a):
        u,v = (r+3.6*self.S)*cos(a),(r*.51+self.S)*sin(a)
        X,Y = round(x+.90*u+.43*v),round(y-.43*u+.90*v)
        plot(buf,self.W,self.H,X,Y,0xA38362 if sin(a)>0 else 0x664D3E)


class Thunder(Scene):
    """Slate clouds roll over an ink-dark shore with distant lightning."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 68000
    gfx_fps = 20
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.grid = _FieldGrid(W,H,11_000) if self.gfx else None
        self.sw,self.sh = ((self.grid.sw,self.grid.sh) if self.grid
                           else _ambient_grid(W,H,2))
        self.idx = []
        self.tick = 0
        self.cloud = [(x/self.sw*16+y/self.sh*3, y/self.sh*26-x/self.sw*6,
                       x/self.sw*32+y/self.sh*13,exp(-((y/self.sh-.35)*2.12)**2))
                      for y in range(self.sh) for x in range(self.sw)]
        self.sky = _ambient_palette(((0,0x080B17),(.25,0x0B0F1C),(.63,0x222A42),(.83,0x3E4D6C),(1,0x7A8EA7)))
        self.sheet = _ambient_palette(((0,0x090B18),(.25,0x131329),(.63,0x373050),(.83,0x655578),(1,0x9886B9)))
        self.pals = [[mix(a,b,lv*29) for a,b in zip(self.sky,self.sheet)] for lv in range(9)]
        self.land = [int(H*(.776+.021*sin(7*x/W)+.009*cos(19*x/W))) for x in range(W)]
        self.events = [0.]
        for _ in range(37):
            self.events.append(self.events[-1]+rng.uniform(2.1,6.9))
        self.bolts = []
        self.event = None
        self.bloom = make_sprite(0x415C9C,max(3,round(H*.20)),7,1.65)

    def _split(self,rng,a,b,rough,depth):
        if not depth:
            return [a]
        x = (a[0]+b[0])*.5+rng.uniform(-rough,rough)
        y = (a[1]+b[1])*.5+rng.uniform(-rough*.23,rough*.23)
        c = x,y
        return self._split(rng,a,c,rough*.55,depth-1)+self._split(rng,c,b,rough*.55,depth-1)

    def _bolt(self):
        W,H = self.W,self.H
        x = W*(.20+.60*self.rng.random())
        a,b = (x,H*.14),(x+self.rng.uniform(-.22,.22)*W,H*.75)
        main = self._split(self.rng,a,b,H*.15,5)+[b]
        lines = [main]
        for k in (5,11,17,23):
            a = main[k]
            b = (a[0]+self.rng.choice((-1,1))*W*self.rng.uniform(.10,.22),
                 a[1]+self.rng.uniform(.12,.22)*H)
            lines.append(self._split(self.rng,a,b,H*.068,3)+[b])
        self.bolts = lines

    def frame(self,t,dt):
        W,H = self.W,self.H
        if self.tick%2 == 0 or not self.idx:
            p = t*.32
            self.idx = [int(20+v*(100+40*sin(a-p+.75*sin(b-p*.69))
                                   +28*cos(b-p*.74)+22*sin(c+p*.61)))
                        for a,b,c,v in self.cloud]
        self.tick ^= 1
        span = self.events[-1]
        phase = (t+2.0)%span
        k = next((i for i in range(len(self.events)-2,-1,-1) if self.events[i] <= phase),0)
        age = phase-self.events[k]
        event = int((t+2)/span)*(len(self.events)-1)+k
        sheet = event%3==2
        flash = (0.42 if sheet else .86)*_ambient_smooth(age/.092)*exp(-max(0.,age-.15)*6.8)
        peak = min(8,round(flash*10))
        pal = self.pals[peak] if sheet else self.sky
        idx = self.idx
        if peak:
            offset = (4 if sheet else 8)*peak
            idx = [min(255,z+offset) for z in idx]
        buf = self.grid.expand(idx, pal) if self.grid else up2(idx,self.sw,self.sh,W,H,pal)
        if not sheet and age < .71:
            if event != self.event:
                self._bolt()
                self.event = event
            pulse = .21*exp(-((age-.60)/.048)**2)
            power = max(6,round(233*max(flash,pulse)))
            x,y = self.bolts[0][8]
            if peak:
                stamp(buf,W,H,round(x),round(y),self.bloom[peak-1 if peak<8 else 6])
            leader = _ambient_smooth(age/.10)
            for j,branch in enumerate(self.bolts):
                color = shade(0xCFE3FF,power if j == 0 else power//2)
                glow = shade(0x708BC3,power//3)
                end = max(2,round(len(branch)*leader))
                for (x0,y0),(x1,y1) in zip(branch[:end-1],branch[1:end]):
                    if peak:
                        line_add(buf,W,H,x0+self.S,y0,x1+self.S,y1,glow)
                        if j == 0:
                            line_add(buf,W,H,x0-2*self.S,y0,x1-2*self.S,y1,shade(glow,105))
                    if self.gfx:
                        _gfx_line_set(buf,W,H,x0,y0,x1,y1,addp(0x202938,color))
                    else:
                        line_add(buf,W,H,x0,y0,x1,y1,color)
        rim = mix(0x131927,0x4A5673,int(190*flash))
        for x,y in enumerate(self.land):
            buf[y*W+x::W] = [0x070C17]*(H-y)
            buf[y*W+x] = rim
        x = int(W*.19)
        y = self.land[x]
        h = max(3,H*.17)
        ink = mix(0x070913,0x2D3148,int(180*flash))
        line_set(buf,W,H,x,y,x+.08*h,y-h,ink)
        for s in (-1,1):
            line_set(buf,W,H,x,y-h*.35,x+s*h*.36,y-h*.70,ink)
            line_set(buf,W,H,x+s*h*.26,y-h*.62,x+s*h*.28,y-h*.9,ink)
            line_set(buf,W,H,x+.02*h,y-h*.69,x+s*h*.20,y-h*.96,ink)
        x = int(W*.83)
        y = self.land[x]
        height = H*.14
        line_set(buf,W,H,x,y,x,y-height,ink)
        for n in range(3):
            a = t*.53+n*TAU/3
            line_set(buf,W,H,x,y-height,x+cos(a)*height*.52,y-height+sin(a)*height*.52,ink)
        return buf


class Kaleido(Scene):
    """Mirrored neon petals dissolve between six, eight and twelve wedges."""
    fps = 12
    mask = 0xF8F8F8

    def setup(self):
        W,H = self.W,self.H
        self.bg = [shade(0x1A0F39,int(44+151*exp(-6*((x/W-.5)**2+(y/H-.5)**2))))
                   for y in range(H) for x in range(W)]
        self.pal = cospal(128,(.55,.49,.56),(.37,.42,.35),(1,1,1),(.08,.35,.71))
        self.symmetry = (6,8,12)
        self.rotations = [[(cos(k*TAU/n),sin(k*TAU/n)) for k in range(n)] for n in self.symmetry]

    def frame(self,t,dt):
        W,H = self.W,self.H
        cx,cy,radius = W*.5,H*.5,min(W,H)*.475
        buf = self.bg[:]
        q = (t/45)%3
        phase = int(q)
        blend = _ambient_smooth((q%1-.87)/.13)
        layers = [(phase,1-blend)]
        if blend:
            layers.append(((phase+1)%3,blend))
        stroke = _gfx_line_add if self.gfx else line_add
        for mode,amount in layers:
            n = self.symmetry[mode]
            wedge = PI/n
            rings = []
            for j in range(3):
                pts = []
                for k in range(13):
                    p = k/12
                    a = wedge*(.04+.90*p)
                    r = radius*(.17+.245*j+.18*sin(p*PI)*(1+.28*sin(t*.61+j))
                                +.045*cos(t*.81+j+p*TAU))
                    pts.append((r*cos(a),r*sin(a)))
                rings.append(pts)
            for ca,sa in self.rotations[mode]:
                for sign in (-1,1):
                    for j,pts in enumerate(rings):
                        col = self.pal[(int(t*5)+33*j+mode*7)%128]
                        ink = shade(col,int(amount*(144-15*j)))
                        glow = shade(col,int(amount*44))
                        old = None
                        for k,(x,y) in enumerate(pts):
                            y *= sign
                            X,Y = cx+x*ca-y*sa,cy+x*sa+y*ca
                            if old is not None:
                                stroke(buf,W,H,*old,X,Y,ink)
                            old = X,Y
                            if k%3 == 1:
                                x0,y0 = round(X),round(Y)
                                plota(buf,W,H,x0,y0,ink)
                                for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                                    plota(buf,W,H,x0+round(dx*self.S),y0+round(dy*self.S),glow)
                        a = wedge*(.43+.36*sin(t*.76+j))
                        r = radius*(.28+.25*j+.07*sin(t*.36+j*1.8))
                        u,v = r*cos(a),sign*r*sin(a)
                        x,y = round(cx+u*ca-v*sa),round(cy+u*sa+v*ca)
                        plota(buf,W,H,x,y,shade(0xFFF0BF,int(amount*159)))
        return buf


class Fractal(Scene):
    """Smooth escape-time vistas paint in and slowly cycle through luminous palettes."""
    fps = 8
    mask = 0xF8F8F8
    gfx_pixels = 68500
    gfx_fps = 20

    def setup(self):
        W,H = self.W,self.H
        max_width,max_height = (280,225) if self.gfx else (140,100)
        self.step = max(1,math.ceil(W/max_width),math.ceil(H/max_height))
        self.sw,self.sh = _ambient_grid(W,H,self.step)
        self.views = ((-.743643887,.1318259042,.0095),(.005,0.,2.48),(-1.756,-.032,.078))
        hues = (((0,0x080B1E),(.22,0x173878),(.43,0x24A2AB),(.61,0xF6C377),(.81,0x953F7D),(1,0x080B1E)),
                ((0,0x130820),(.22,0x5D287A),(.43,0xB6599C),(.62,0xF7AC8C),(.80,0x453B99),(1,0x130820)),
                ((0,0x071218),(.22,0x275275),(.42,0x559877),(.64,0xD4AE5F),(.81,0x70485A),(1,0x071218)))
        self.palettes = []
        for hue in hues:
            pal = _ambient_palette(hue,128)
            self.palettes.append([pal[k:]+pal[:k]+[0x03040B] for k in range(128)])
        self.mode = None
        self.indices = [128]*(self.sw*self.sh)
        self.previews = []
        sample = 4
        for mode in range(len(self.views)):
            coarse = [[self._sample(mode,min(self.sw-1,x+sample//2),
                                          min(self.sh-1,y+sample//2))[0]
                       for x in range(0,self.sw,sample)] for y in range(0,self.sh,sample)]
            self.previews.append([coarse[y//sample][x//sample]
                                  for y in range(self.sh) for x in range(self.sw)])

    def _sample(self, mode, col, row):
        cx,cy,span = self.views[mode]
        step = span/self.sh
        a,b = cx+(col-self.sw*.5)*step,cy+(row-self.sh*.5)*step
        if mode == 1:
            x,y,a,b = a,b,-.8,.156
        else:
            x=y=0.
        n = 0
        xx,yy = x*x,y*y
        while n < 160 and xx+yy < 64:
            cross = x*y
            y = 2*(abs(cross) if mode == 2 else cross)+b
            x = xx-yy+a
            xx,yy = x*x,y*y
            n += 1
        if n == 160:
            return 128,n
        smooth = n+1-math.log2(math.log(sqrt(xx+yy)))
        return int(smooth*6.5)&127,n

    def _paint(self,mode):
        # Cap work on dense regions while filling in the coarse preview.
        budget = 9200
        for i in range(self.cursor,len(self.indices)):
            value,cost = self._sample(mode,i%self.sw,i//self.sw)
            self.indices[i] = value
            budget -= cost+4
            if budget <= 0:
                self.cursor = i+1
                return
        self.cursor = len(self.indices)

    def frame(self,t,dt):
        W,H = self.W,self.H
        cycle = int(t/207)
        local = t%207
        mode = cycle%len(self.views)
        if cycle != self.mode:
            self.mode = cycle
            self.cursor = 0
            self.indices[:] = self.previews[mode]
        if self.cursor < len(self.indices):
            self._paint(mode)
        pal = self.palettes[mode][int(t*2.4)%128]
        fade = min(_ambient_smooth(local/.8),_ambient_smooth((207-local)/5))
        if fade < 1:
            pal = [shade(c,int(fade*256)) for c in pal]
        if self.step == 1:
            return list(map(pal.__getitem__,self.indices))
        return _ambient_expand(self.indices,W,H,self.sw,self.step,pal)


class Cyclic(Scene):
    """A cyclic cellular automaton grows rotating colonies of colored wavefronts."""
    fps = 12
    mask = 0xF0F0F0
    gfx_fps = 12

    def setup(self):
        W,H = self.W,self.H
        self.step = self.px(2 if self.logical_area <= 16000 else 3)
        self.sw,self.sh = _ambient_grid(W,H,self.step)
        self.grid_x = self.grid_y = None
        if self.gfx_reference:
            rw,rh = self.gfx_reference
            nominal = 2 if self.logical_area <= 16000 else 3
            step = max(1, round(nominal*self.S/self.detail_scale))
            self.sw,self.sh = _ambient_grid(rw,rh,step)
            self.grid_x = itemgetter(*(x*self.sw//W for x in range(W)))
            self.grid_y = [y*self.sh//H for y in range(H)]
        self.ramps = {}
        for k in range(12,15):
            pal = _ambient_palette(((0,0x1C173D),(.19,0x334D79),(.40,0x27847E),(.59,0x86934F),
                                    (.74,0xCB9454),(.88,0xA65870),(1,0x593366)),k)
            self.ramps[k] = [[shade(c,32+i*28) for c in pal] for i in range(9)]
        self.epoch = None
        self.next_seed = None
        self.noise = None
        self._seed(0)

    def _seed(self,t):
        rng = self.rng
        self.states = rng.randrange(12,15)
        self.successor = list(range(1,self.states))+[0]
        sw,sh,K = self.sw,self.sh,self.states
        centers = [(sw*rng.uniform(a-.035,a+.035),sh*rng.uniform(b-.07,b+.07),rng.choice((-1,1)),rng.randrange(K))
                   for a,b in ((.16,.28),(.43,.68),(.70,.26),(.88,.72))]
        self.cells = []
        self.cores = []
        self.tick = 0
        radius = max(2.2,min(4.3,min(sw,sh)*.083))
        for y in range(sh):
            for x in range(sw):
                px,py,hand,phase = min(centers,key=lambda c:(x-c[0])**2+(y-c[1])**2)
                dx,dy = x-px,y-py
                distance = hypot(dx,dy)
                wave = math.floor(-.43*distance+hand*K/TAU*atan2(dy,dx)+phase)
                if distance < radius:
                    self.cores.append((y*sw+x,wave%K))
                if rng.random()<.045:
                    wave = rng.randrange(K)
                self.cells.append(wave%K)
        self.noise = int(t/8)

    def frame(self,t,dt):
        W,H,sw,sh = self.W,self.H,self.sw,self.sh
        if self.epoch is None:
            self.epoch = t-4
            self.next_seed = t+116
        if self.next_seed <= t:
            self._seed(t)
            self.epoch = t
            self.next_seed = t+120
        interval = int(t/8)
        field = self.cells
        if interval != self.noise:
            self.noise = interval
            cx,cy = self.rng.randrange(sw),self.rng.randrange(sh)
            r = max(1,min(3,sw//17))
            for y in range(-r,r+1):
                for x in range(-r,r+1):
                    if x*x+y*y <= r*r:
                        field[((cy+y)%sh)*sw+(cx+x)%sw] = self.rng.randrange(self.states)
        rows = [field[i:i+sw] for i in range(0,len(field),sw)]
        left = [row[-1:]+row[:-1] for row in rows]
        right = [row[1:]+row[:1] for row in rows]
        out = []
        get = self.successor.__getitem__
        for y,row in enumerate(rows):
            a,b = y-1,(y+1)%sh
            neigh = zip(row,map(get,row),left[a],rows[a],right[a],left[y],right[y],left[b],rows[b],right[b])
            out.extend(n if ((n==a)+(n==b)+(n==c)+(n==d)+(n==e)+(n==f)+(n==g)+(n==h))>=2 else s
                       for s,n,a,b,c,d,e,f,g,h in neigh)
        if self.tick%48 == 0 and t-self.epoch > 20:
            activity = sum(a!=b for a,b in zip(out,field))
            if activity < max(2,len(field)//160):
                self.next_seed = min(self.next_seed,t+1.5)
        # Small rotating nucleation cores keep wavefronts circulating between reseeds.
        phase = self.tick//3
        for i,state in self.cores:
            out[i] = (state+phase)%self.states
        self.tick += 1
        self.cells = out
        fade = min(_ambient_smooth((t-self.epoch)/1.5),_ambient_smooth((self.next_seed-t)/1.5))
        palette = self.ramps[self.states][round(fade*8)]
        if self.grid_x:
            rows = [self.grid_x(list(map(palette.__getitem__, out[i:i+sw])))
                    for i in range(0,len(out),sw)]
            expanded = []
            for y in self.grid_y:
                expanded.extend(rows[y])
            return expanded
        return _ambient_expand(out,W,H,sw,self.step,palette)


class StainedGlass(Scene):
    """Sunlight crosses jewel-toned panes set into a pointed cathedral window."""
    fps = 10
    mask = 0xF8F8F8
    gfx_pixels = 68500

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        cx = (W-1)*.5
        half = min(W*.39,H*.43)
        spring = H*.39
        height = H*.325
        bottom = H*.91
        colors = (0xB3123A,0x1B3FA8,0x0F8A4F,0xE6A21A,0x6A2BB0,0x0F8F9F,0xD6457A)
        nx,ny = 8,9
        seeds = [[(i+.5+rng.uniform(-.31,.31),j+.5+rng.uniform(-.31,.31),
                   rng.choice(colors),rng.random()*TAU) for i in range(nx)] for j in range(ny)]
        self.seeds = []
        for row in seeds:
            for a,b,c,p in row:
                c = mix(c,0xFFF0C0,18)
                self.seeds.append(((a/nx-.5)*2,b/ny,p,
                                   [shade(c,int(30+j*9.6)) for j in range(26)]))
        plate = [0]*(W*H)
        ids = [-1]*(W*H)
        columns = []
        if self.gfx:
            for x in range(W):
                u = abs(x-cx)/half
                arch = spring-height*sqrt(max(0,1-((u+.56)/1.56)**2))/.932
                fx = (x-cx+half)/(2*half)*nx
                # Jitter is bounded to .31 around each cell center. A seed two
                # cells away cannot beat the seed in the current cell.
                ix = int(fx)
                candidates = [tuple(((fx-row[i][0])**2,row[i][1],j*nx+i)
                                    for i in range(max(0,ix-1),min(nx,ix+2)))
                              for j,row in enumerate(seeds)]
                columns.append(((1-u)*half,arch,fx,candidates))
        for y in range(H):
            for x in range(W):
                if columns:
                    wall,arch,fx,candidates = columns[x]
                    d = min(wall,y-arch,bottom-y)
                else:
                    u = abs(x-cx)/half
                    arch = spring-height*sqrt(max(0,1-((u+.56)/1.56)**2))/.932
                    d = min((1-u)*half,y-arch,bottom-y)
                k = y*W+x
                grain = rng.randrange(8)
                if d < 1:
                    stone = 0x14121A if (y//max(3,H//11))%2 else 0x17141D
                    if -.065*H < d < 1:
                        stone = 0x43364B if d > -.026*H else 0x262231
                    elif x in (0,W-1) or y%max(4,H//11)==0:
                        stone = 0x0F0D16
                    plate[k] = addp(stone,shade(0x181218,grain*5))
                    continue
                fx = (x-cx+half)/(2*half)*nx
                fy = (y-(spring-height))/(bottom-(spring-height))*ny
                best,jid = 10.,0
                if columns and 0 <= fx < nx and 0 <= fy < ny:
                    for j in range(max(0,int(fy)-1),min(ny,int(fy)+2)):
                        for dx2,b,index in candidates[j]:
                            score = dx2+(fy-b)**2
                            if score < best:
                                best,jid = score,index
                else:
                    for j in range(max(0,int(fy)-2),min(ny,int(fy)+3)):
                        for i in range(max(0,int(fx)-2),min(nx,int(fx)+3)):
                            a,b,_,_ = seeds[j][i]
                            score = (fx-a)**2+(fy-b)**2
                            if score < best:
                                best,jid = score,j*nx+i
                ids[k] = jid
        self.bg = plate
        self.glass = []
        lead_width = self.px(1)
        for i,j in enumerate(ids):
            if j < 0:
                continue
            y,x = divmod(i,W)
            # Mullion, rose medallion and a highlighted leading edge share the lead treatment.
            ring = hypot((x-cx),(y-H*.31)*1.06)
            rose = abs(ring-H*.095)<.74*self.S or abs(ring-H*.047)<.51*self.S
            lead = abs(x-cx)<max(.6,H*.010) or rose
            if not lead and (j != ids[i-lead_width] or j != ids[i-lead_width*W]):
                plate[i] = 0x0A0A10
            elif lead:
                plate[i] = 0x17131E if x<cx else 0x0A0A10
            else:
                raw = int(1.3*sin((x*1.52+y*.32)/self.S)+1.1*cos((y*1.82-x*.21)/self.S))+rng.randrange(-1,2)
                etch = -2 if j != ids[i+1] or j != ids[i+W] else 0
                self.glass.append((i,j,max(-3,min(3,raw-etch))))

    def frame(self,t,dt):
        a = t*TAU/60
        dx,dy = cos(a*.27+.68),sin(a*.27+.68)
        ray = 1.09*sin(a*.5+.44)
        cols = []
        for x,y,p,ramp in self.seeds:
            v = x*dx+(y-.51)*1.32*dy-ray
            light = exp(-(v/.39)**2)
            lv = int(6+14*light+1.8*sin(t*.71+p))
            cols.append(ramp[lv-3:lv+4])
        buf = self.bg[:]
        for i,j,texture in self.glass:
            buf[i] = cols[j][texture+3]
        return buf


class Circuit(Scene):
    """Data pulses thread quiet PCB traces and trigger activity at chip pins."""
    fps = 15
    mask = 0xF8F8F8

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        board = [0x050B15]*(W*H)
        for y in range(self.px(2),H,self.px(4)):
            for x in range(self.px(2),W,self.px(4)):
                board[y*W+x] = 0x0B1624
        for _ in range(int(self.logical_area//100)):
            board[rng.randrange(W*H)] = 0x101C2B
        hw,hh = max(2,min(self.px(12),W//11)),max(2,min(self.px(8),H//10))
        centers = [(round(W*a),round(H*b)) for a,b in ((.27,.26),(.72,.26),(.27,.69),(.72,.69))]
        blocked = set()
        self.chips = []
        for x,y in centers:
            left,right,top,bottom = x-hw,x+hw,y-hh,y+hh
            edge = []
            for yy in range(top,bottom+1):
                for xx in range(left,right+1):
                    i = yy*W+xx
                    blocked.add(i)
                    board[i] = 0x0C1424
                    if xx in (left,right) or yy in (top,bottom):
                        edge.append(i)
                        board[i] = 0x263B55
            _ambient_disc(board,W,H,left+self.px(2),top+self.px(2),self.px(1),0x445266)
            for k in range(-hw+1,hw,self.px(2)):
                plot(board,W,H,x+k,top-1,0x454655)
                plot(board,W,H,x+k,bottom+1,0x454655)
            for k in range(-hh+1,hh,self.px(2)):
                plot(board,W,H,left-1,y+k,0x454655)
                plot(board,W,H,right+1,y+k,0x454655)
            self.chips.append((edge,[]))
        self.routes = []
        self.heads = []
        self.flashes = [0.]*len(centers)
        self.bg = board
        occupied = set(blocked)

        def add_route(points,a,b):
            pixels = []
            for (x,y),(X,Y) in zip(points,points[1:]):
                span = max(abs(X-x),abs(Y-y))
                for k in range(span):
                    xx,yy = round(x+(X-x)*k/span),round(y+(Y-y)*k/span)
                    if not (0 <= xx < W and 0 <= yy < H):
                        return False
                    pixels.append(yy*W+xx)
            x,y = points[-1]
            if not (0 <= x < W and 0 <= y < H):
                return False
            pixels.append(y*W+x)
            if len(pixels) < 4 or any(i in occupied for i in pixels):
                return False
            occupied.update(pixels)
            k = len(self.routes)
            c = rng.choices((0x7DFCFF,0xFF4FD8,0xFFD04A),(8,2,2))[0]
            ramp = [shade(c,int(218*exp(-d/(4.6*self.S)))) for d in range(self.px(14))]
            self.routes.append((pixels,a,b,ramp))
            for chip in (a,b):
                if chip >= 0:
                    self.chips[chip][1].append(k)
            for i in pixels:
                board[i] = 0x0E3B4A
            for i in (pixels[0],pixels[-1]):
                board[i] = 0x407177
            return True

        pins_y = range(-min(self.px(5),hh-1),min(self.px(6),hh),self.px(2))
        pins_x = range(-min(self.px(7),hw-1),min(self.px(8),hw),self.px(2))
        for a,b in ((0,1),(2,3)):
            x,y = centers[a]
            X,Y = centers[b]
            for k in pins_y:
                sign = 1 if k >= 0 else -1
                bend = min(abs(k)//2+1,max(1,(X-x-2*hw)//5))
                x0,x1 = x+hw+1,X-hw-1
                if x1-x0 >= 2*bend+1:
                    add_route(((x0,y+k),(x0+bend,y+k+sign*bend),
                               (x1-bend,Y+k+sign*bend),(x1,Y+k)),a,b)
        for a,b in ((0,2),(1,3)):
            x,y = centers[a]
            X,Y = centers[b]
            for k in pins_x:
                sign = 1 if k>=0 else -1
                bend = min(abs(k)//2+1,max(1,(Y-y-2*hh)//5))
                y0,y1 = y+hh+1,Y-hh-1
                if y1-y0 >= 2*bend+1:
                    add_route(((x+k,y0),(x+k+sign*bend,y0+bend),
                               (X+k+sign*bend,y1-bend),(X+k,y1)),a,b)
        outward = []
        for i,(x,y) in enumerate(centers):
            nx = -1 if i%2==0 else 1
            ny = -1 if i<2 else 1
            outward.extend((i,x+nx*(hw+1),y+k,0 if nx>0 else 4) for k in pins_y)
            outward.extend((i,x+k,y+ny*(hh+1),2 if ny>0 else 6) for k in pins_x)
        rng.shuffle(outward)
        compass = ((1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1))
        target = min(55,max(26,int(self.logical_area//230)))
        for chip,x,y,d in outward:
            if len(self.routes) >= target:
                break
            for _ in range(5):
                points = [(x,y)]
                X,Y = x,y
                direction = d
                for k in range(rng.randint(2,7)):
                    dx,dy = compass[direction]
                    X,Y = X+dx*self.px(3),Y+dy*self.px(3)
                    if not (1 <= X < W-1 and 1 <= Y < H-1):
                        break
                    points.append((X,Y))
                    if rng.random() < .28:
                        direction = (direction+rng.choice((-2,-1,1,2)))%8
                if len(points)>1 and add_route(points,chip,-1):
                    break
        self.scan = sorted((i%W+i//W,i) for pixels,_,_,_ in self.routes for i in pixels)
        self.next_pulse = None
        for k,route in enumerate(self.routes):
            if k%3==0:
                self.heads.append([k,rng.uniform(0,len(route[0])-1),rng.uniform(22,54)*self.S])

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        rng = self.rng
        if self.routes and (self.next_pulse is None or t>=self.next_pulse):
            k = rng.randrange(len(self.routes))
            self.heads.append([k,0.,rng.uniform(21,57)*self.S])
            self.next_pulse = t+rng.uniform(.08,.27)
        age = (t+9)%40
        if age < 2.5:
            x = (W+H+22)*age/2.5-10
            for diag,i in self.scan:
                if abs(diag-x)<9:
                    buf[i] = addp(buf[i],shade(0x185268,int(91*(1-abs(diag-x)/9))))
        heads = []
        arrivals = []
        for k,s,v in self.heads:
            pixels,a,b,ramp = self.routes[k]
            s += dt*v
            j = int(s)
            if s < 0 or j>=len(pixels):
                chip = b if v > 0 else a
                if chip >= 0:
                    arrivals.append((k,chip))
                continue
            heads.append([k,s,v])
            direction = 1 if v > 0 else -1
            tail = j+1 if v > 0 else len(pixels)-j
            for d,c in enumerate(ramp[:tail]):
                i = pixels[j-d*direction]
                buf[i] = addp(buf[i],c)
        for k,b in arrivals:
            self.flashes[b] = 1.
            choices = self.chips[b][1]
            if len(choices)>1 and len(heads)<76 and rng.random()<.62:
                q = rng.choice(choices)
                if q != k:
                    pixels,a,_b,_ = self.routes[q]
                    direction = 1 if a==b else -1
                    heads.append([q,0. if direction>0 else len(pixels)-1.,direction*rng.uniform(20,55)*self.S])
        self.heads = heads
        for j,lv in enumerate(self.flashes):
            if lv > .015:
                self.flashes[j] = lv*exp(-dt*4)
                c = shade(0x4CB8C8,int(lv*170))
                for i in self.chips[j][0]:
                    buf[i] = addp(buf[i],c)
        return buf


class Silk(Scene):
    """Long-lived strands of champagne, rose and teal flow into cool luminous silk."""
    fps = 9
    mask = 0xF8F8F8
    gfx_pixels = 65000
    gfx_fps = 22

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.ramps = []
        dark = 0x0A0710
        for colors in ((0xC88A3C,0xDB4E81,0x299E93),(0x7367D7,0x3979D9,0x94BCD1)):
            bank = []
            for ink in colors:
                pal = _ambient_palette(((0,dark),(.18,mix(dark,ink,46)),(.68,ink),
                                        (.85,mix(ink,0xFFE7CC,81)),(1,0xFFEAD9)),16)
                bank.extend(pal[k//4] for k in range(64))
            self.ramps.append(bank+[dark]*64)
        self.decays = bytes((i&192)|max(0,(i&63)-3) for i in range(256))
        self.state = bytearray(W*H)
        self.tick = 0
        n = max(100,min(760,int(self.logical_area//15)))
        if self.gfx:
            n = min(1150,int(n*sqrt(self.S)))
        self.particles = [self._new(rng.uniform(0,7)) for _ in range(n)]
        self.speed = 25*max(.4,_ambient_scale(W,H,self.S))

    def _new(self,age):
        rng = self.rng
        x,y = rng.random(),rng.random()
        ink = (min(2,int(x*3)) if rng.random()<.8 else rng.randrange(3))*64
        return [x*self.W,y*self.H,age,ink,rng.uniform(.78,1.22)]

    def frame(self,t,dt):
        W,H = self.W,self.H
        cadence = 5 if self.gfx else 2
        if self.tick == 0:
            self.state = self.state.translate(self.decays)
        self.tick = (self.tick+1)%cadence
        buf = self.state
        a,b,c = (t*.11)%TAU,(-t*.07)%TAU,(t*.05)%TAU
        step = self.speed*dt
        scale = self.S
        head, tail = (16,9) if self.gfx else (23,14)
        for j,pt in enumerate(self.particles):
            x,y,age,ink,speed = pt
            theta = 2.3*sin(.035*x/scale+a)+2.1*sin(.05*y/scale+b)+.86*sin(.02*(x+y)/scale+c)
            nx,ny = x+step*speed*cos(theta),y+step*speed*sin(theta)
            if age <= 0 or not (0 <= nx < W and 0 <= ny < H):
                self.particles[j] = self._new(self.rng.uniform(3,8))
                continue
            pt[0],pt[1],pt[2] = nx,ny,age-dt
            i = int(ny)*W+int(nx)
            level = buf[i]&63
            buf[i] = ink|min(63,level+head)
            mid = int((y+ny)*.5)*W+int((x+nx)*.5)
            if mid!=i:
                buf[mid] = ink|min(63,(buf[mid]&63)+tail)
        shift = (t/90)%2
        src,dst = self.ramps[int(shift)],self.ramps[1-int(shift)]
        blend = _ambient_smooth((shift%1-.86)/.14)
        pal = src if blend == 0 else [mix(x,y,int(256*blend)) for x,y in zip(src,dst)]
        return list(map(pal.__getitem__,buf))


class Filings(Scene):
    """Iron filings follow an evolving magnetic field and its close-orbiting dipole."""
    fps = 12
    mask = 0xF8F8F8
    gfx_pixels = 62500

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.bg = [shade(0x242738,rng.randrange(41,80)) for _ in range(W*H)]
        self.spacing = max(3,math.ceil(sqrt(W*H/800)),round(5*_ambient_scale(W,H,self.S)))
        gap = self.spacing
        self.lattice = [(x+(gap//2 if j%2 else 0),y)
                        for j,y in enumerate(range(1,H,gap)) for x in range(1,W-gap//2,gap)]
        self.angles = [0.]*len(self.lattice)
        self.ready = False
        self.pal = _ambient_palette(((0,0x202B46),(.34,0x506785),(.72,0x9FB4D6),(1,0xE0F6F5)),64)
        self.halos = [make_sprite(c,max(3,round(min(W,H)*.12)),6,2.1) for c in (0xFF8A3D,0x3D8BFF)]

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        angle = t*.24
        age = (t%60)
        close = _ambient_smooth((age-43)/4)*(1-_ambient_smooth((age-55)/5))
        poles = []
        for j in range(4):
            x = W*(.5+( .23 if j<2 else .33)*cos(t*(.13+.018*j)+j*1.87))
            y = H*(.5+(.23 if j<2 else .33)*sin(t*(.15+.021*j)+j*1.79))
            if j<2:
                a = angle+j*PI
                x = x*(1-close)+(W*.50+min(W,H)*.115*cos(a))*close
                y = y*(1-close)+(H*.48+min(W,H)*.115*sin(a))*close
            poles.append((x,y,1 if j%2==0 else -1))
        inertia = min(1,8*dt) if self.ready else 1
        self.ready = True
        length = self.spacing*.39
        normal = min(W,H)**2
        eps = (min(W,H)*.048)**2
        stroke = _gfx_line_set if self.gfx else line_set
        for i,(x,y) in enumerate(self.lattice):
            u=v=0.
            for px,py,q in poles:
                dx,dy = x-px,y-py
                d = dx*dx+dy*dy+eps
                force = q/(d*sqrt(d))
                u += dx*force
                v += dy*force
            aim = atan2(v,u)
            old = self.angles[i]
            # Filings have no arrowhead, so the shortest rotation is periodic over pi.
            a = old+((aim-old+PI/2)%PI-PI/2)*inertia
            self.angles[i] = a%PI
            power = min(1,math.log1p(normal*hypot(u,v)*.32)/4.1)
            r = length*(.47+.58*power)
            dx,dy = r*cos(a),r*sin(a)
            stroke(buf,W,H,x-dx,y-dy,x+dx,y+dy,self.pal[int(63*power)])
        for j,(x,y,q) in enumerate(poles):
            xi,yi = round(x),round(y)
            stamp(buf,W,H,xi,yi,self.halos[j%2][3])
            plota(buf,W,H,xi,yi,0xFFA36A if q>0 else 0x7EB7FF)
        return buf


class StarTrails(Scene):
    """A turning sky builds long exposures over pine silhouettes until dawn."""
    fps = 12
    mask = 0xF8F8F8
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.cx,self.cy = W*.31,H*.29
        self.night = _ambient_palette(((0,0x070C22),(.49,0x101738),(1,0x29334F)),H)
        self.dawn = _ambient_palette(((0,0x163557),(.40,0x276779),(.70,0x887987),(1,0xF9A57E)),H)
        self.bg = [c for c in self.night for _ in range(W)]
        self.ridge = [int(H*(.794+.049*sin(x/W*8)+.027*cos(16*x/W)+.032*sin(x/W*23))) for x in range(W)]
        for x in range(W):
            h = max(2,round(H*rng.uniform(.021,.088)))
            if x%self.px(2)==0 and rng.random()<.70:
                y = self.ridge[x]+1
                for dx in range(-h//3,h//3+1):
                    X = x+dx
                    if 0 <= X < W:
                        self.ridge[X] = min(self.ridge[X],y-h+abs(dx)*3)
        for x,y in enumerate(self.ridge):
            self.bg[y*W+x::W] = [0x05070D]*(H-y)
        x = int(W*.80)
        y = min(H-3,max(self.ridge[max(0,x-2):x+4])+1)
        line_set(self.bg,W,H,x-2,y+1,x,y-1,0x10111A)
        line_set(self.bg,W,H,x,y-1,x+3,y+1,0x10111A)
        plot(self.bg,W,H,x,y+1,0xD29657)
        self.cabin = (x,y+1)
        self.sky = [(x,y) for y in range(H) for x in range(W) if y<self.ridge[x]]
        self.stars = []
        for i in range(max(105,min(775 if self.gfx else 670,int(self.logical_area//17*sqrt(self.S))))):
            x = rng.uniform(-.32,1.25)*W-self.cx
            y = rng.uniform(-.59,1.09)*H-self.cy
            color = rng.choice((0xFFD9B0,0xB8D0FF,0xB8D0FF,0xEED2BB,0xD49987))
            bright = rng.randrange(22,130) if i%8 else rng.randrange(132,218)
            self.stars.append((x,y,shade(color,bright),i%19==0))
        self.dust = [(rng.uniform(-.64,.95)*W,rng.gauss(0,.068)*H, rng.randrange(20,78))
                     for _ in range(max(70,min(440,int(self.logical_area//25))))]
        self.pole = make_sprite(0xB8D0FF,max(2,round(H*.043)),6,2.2)[-1]
        self.cycle = None
        self.last = []
        self.canvas = self.bg[:]
        self.exposure = [0]*(W*H)
        self.meteors = [12.7]
        for _ in range(13):
            self.meteors.append(self.meteors[-1]+rng.uniform(15,39))

    def _record(self,x,y,c):
        if 0 <= x < self.W and 0 <= y < self.ridge[x]:
            i = y*self.W+x
            old = self.exposure[i]
            if old < c:
                self.exposure[i] = c
                self.canvas[i] = addp(self.bg[i],c)

    def frame(self,t,dt):
        W,H = self.W,self.H
        local,cycle = t%360,int(t/360)
        if cycle != self.cycle:
            self.cycle = cycle
            self.last = []
            self.canvas[:] = self.bg
            self.exposure[:] = [0]*(W*H)
        phase = local*TAU/300
        ca,sa = cos(phase),sin(phase)
        cx,cy = self.cx,self.cy
        if local<244:
            last = self.last
            now = []
            for j,(x,y,c,bright) in enumerate(self.stars):
                X,Y = round(cx+x*ca-y*sa),round(cy+x*sa+y*ca)
                now.append((X,Y))
                if last and (X,Y)==last[j]:
                    continue
                self._record(X,Y,c)
                if bright:
                    self._record(X+self.px(1),Y,shade(c,53))
                if last:
                    a,b = last[j]
                    d = max(abs(a-X),abs(b-Y))
                    if 1 < d <= 4:
                        for k in range(1,d):
                            self._record(round(a+(X-a)*k/d),round(b+(Y-b)*k/d),c)
            self.last = now
        day = _ambient_smooth((local-244)/41)*(1-_ambient_smooth((local-308)/32))
        if local >= 244:
            buf = self.bg[:]
            trails = int(256*(1-_ambient_smooth((local-244)/42)))
            rows = [mix(n,d,int(256*day)) for n,d in zip(self.night,self.dawn)]
            # Skip the foreground so both the tree line and cabin stay sharp through dawn.
            for x,y in self.sky:
                i = y*W+x
                c = self.exposure[i]
                buf[i] = addp(rows[y],shade(c,trails)) if c and trails else rows[y]
        else:
            buf = self.canvas[:]
        if day<.9 and local<306:
            a = phase+.60
            ca,sa = cos(a),sin(a)
            for x,y,l in self.dust:
                X,Y = round(cx+x*ca-y*sa),round(cy+x*sa+y*ca)
                if 0 <= X < W and 0 <= Y < self.ridge[X]:
                    plota(buf,W,H,X,Y,shade(0x4F6186,int(l*(1-day))))
            stamp(buf,W,H,round(cx),round(cy),self.pole)
            meteor = next((i for i,v in enumerate(self.meteors) if 0<=local-v<.95),None)
            if meteor is not None:
                a = local-self.meteors[meteor]
                x,y = W*(.78-.51*a),H*(.11+.31*a+(meteor%4)*.058)
                for k in range(9):
                    X,Y = round(x+k*1.12*self.S),round(y-k*.51*self.S)
                    if 0 <= X < W and 0 <= Y < self.ridge[X]:
                        plota(buf,W,H,X,Y,shade(0xD7FFDD,(9-k)*25))
            satellite = (local+15)%121
            if satellite<32:
                x = int(W*satellite/32)
                y = int(H*(.38+.19*satellite/32))
                if y<self.ridge[x]:
                    plota(buf,W,H,x,y,0x82988F)
        return buf
