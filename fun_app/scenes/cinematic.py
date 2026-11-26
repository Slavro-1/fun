"""Scenes that evolve through scripted sequences."""
import math
import os

from .ambient_drawing import _ambient_smooth
from .base import Episode, Scene
from .drawing import (
    TAU,
    _gfx_line_set,
    addp,
    cos,
    exp,
    fill_row,
    hypot,
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
    vgrad,
)


class Lighthouse(Scene):
    """A quiet headland, watched by a single slow amber beacon."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    def setup(self):
        W, H, rng = self.W, self.H, self.rng
        self.horizon = horizon = round(.62*H)
        self.tower_x = x = round(.72*(W-1))
        foot = min(H-1, horizon+max(1,round(.025*H)))
        height = max(2, int(.14*H)) if self.gfx else min(16,foot+1)
        self.tower_height = height
        self.lens_y = top = foot-height+1
        half = max(1, round(.18*height))
        self.bg = vgrad(W,H,((0,(5,8,15)),(.62,(13,26,43)),(.63,(11,23,38)),
                             (1,(5,11,21))))
        self.fog = []
        self.fog_at = [0.]*H
        mist = 0x2A3F55
        for y in range(max(0, top-round(.12*H)), horizon):
            # Two partially separated height profiles scroll at different rates.
            upper = .28*exp(-((y/H-.502)/.051)**2)
            lower = .58*exp(-((y/H-.602)/.027)**2)
            if upper+lower < .012:
                continue
            harmonic = .52+.25*sin(y/H*39)
            shape = [.60+.22*sin(2*TAU*i/W+harmonic)+.12*cos(3*TAU*i/W-9*y/H)
                     for i in range(W)]
            profile = upper+lower
            self.fog_at[y] = profile
            base = self.bg[y*W]
            rows = []
            palette = [mix(base,mist,n) for n in range(115)]
            for level in range(5):
                row = [palette[min(114,round(152*profile*v*(.53+.155*level)))]
                       for v in shape]
                rows.append(row+row)
            self.fog.append((y, .011*W if upper>lower else -.021*W, rows))
        self.headland = []
        for offset in range(-3*half,4*half+1):
            px = x+offset
            if 0<=px<W:
                land_y = foot+round(abs(offset)*.40+sin(offset*.39)*height*.065)
                for y in range(max(horizon,land_y),min(H,land_y+max(2,round(H*.022)))):
                    self.headland.append((y*W+px,0x080E18))
        self.tower = []
        self.glass = []
        for y in range(top,foot+1):
            k = y-top
            if k==0:
                width,ink = max(1,half-1),0x192330
            elif k<=max(1,round(.17*height)):
                width,ink = max(1,half-1),0x758089
            elif k==max(2,round(.18*height)+1):
                width,ink = half+max(1,round(height*.05)),0x151E2B
            else:
                width,ink = max(1,round(half*(.49+.55*k/height))),0x4B5864
            for px in range(max(0,x-width),min(W,x+width+1)):
                color = ink if px<=x else shade(ink,173)
                self.tower.append((y*W+px,color))
            if 0<k<=max(1,round(.17*height)):
                self.glass.append(y*W+x)
        self.lens_y = top+max(1,round(.1*height))
        self.glow = make_sprite(0xFFD08A,max(2,round(.03*H)),5,2.45)
        self.moon = make_sprite(0x657683,max(2,round(.032*H)),5,2.1)
        radius = max(2,round(.016*H))
        self.moon_rim = [(dx,dy) for dy in range(-radius,radius+1)
                         for dx in range(-radius,radius+1)
                         if hypot(dx,dy)<=radius and hypot(dx+radius*.62,dy-radius*.14)>radius*.93]
        self.waves = [(rng.random(), rng.uniform(.01,.95), rng.random()*TAU,
                       rng.uniform(.018,.088)) for _ in range(49)]
        self.beam_colors = [shade(0xFFD08A,l) for l in range(85)]

    def _beam(self, buf, t, density):
        W, H = self.W, self.H
        a = TAU*t/40+.69
        reach = max(2.,W*.62*abs(cos(a)))
        direction = 1 if cos(a)>0 else -1
        x0, y0 = self.tower_x,self.lens_y
        end = min(int(reach),W-1-x0 if direction>0 else x0)
        bend = .12*H*sin(a+.38)/reach
        spread = .081
        start_width = max(1.,.009*H)
        for y, _, _ in self.fog:
            rise = y-y0
            lo,hi = 1.,float(end)
            # Intersect this scanline with the wedge's two angular boundaries.
            for delta, slope in ((rise-start_width,bend+spread),
                                 (-rise-start_width,spread-bend)):
                if slope>0:
                    lo = max(lo,delta/slope)
                elif slope<0:
                    hi = min(hi,delta/slope)
                elif delta>0:
                    hi = 0.
            if hi<lo:
                continue
            strength = min(84.,203*self.fog_at[y]*density)
            base = y*W+x0
            for distance in range(math.ceil(lo),int(hi)+1):
                aperture = start_width+spread*distance
                edge = 1-abs(rise-bend*distance)/aperture
                along = distance/reach
                falloff = (1-along)*(1+.48*along)
                level = int(strength*min(1.,max(0.,edge*2.3))*falloff)
                if level:
                    i = base+direction*distance
                    buf[i] = addp(buf[i],self.beam_colors[level])
        return x0+direction*reach, abs(cos(a))*(.35+.65*max(0.,sin(a+.38)))

    def frame(self,t,dt):
        W,H = self.W,self.H
        horizon = self.horizon
        buf = self.bg[:]
        density = .59+.30*sin(t*TAU/187-.75)+.09*sin(t*TAU/79)
        level = max(0,min(4,round(4*density)))
        for y,speed,rows in self.fog:
            offset = int(t*speed)%W
            buf[y*W:(y+1)*W] = rows[level][offset:offset+W]
        moon = _ambient_smooth((t-420)/104)
        if moon:
            mx,my = round(W*.31),round(H*.23)
            stamp(buf,W,H,mx,my,self.moon[min(4,int(moon*5))])
            ink = shade(0x95A6BB,int(64*moon))
            for dx,dy in self.moon_rim:
                plota(buf,W,H,mx+dx,my+dy,ink)
        tip, light = self._beam(buf,t,density)
        for u,depth,phase,span in self.waves:
            x = round(W*((u+t*.009*(.25+depth))%1))
            y = min(H-1,horizon+round((H-1-horizon)*depth))
            w = max(2,round(W*span*(.31+.78*depth)))
            ripple = .54+.43*sin(t*(.61+.53*depth)+phase)
            sweep = max(0.,1-abs(x-(self.tower_x*.34+tip*.66))/(W*.21))
            gain = 64*light*sweep*(1-depth)**2
            color = shade(0x4C6578,int((36+36*depth)*ripple))
            if gain>2:
                color = addp(color,shade(0xBA9A6B,int(gain*ripple)))
            left,right = max(0,x-w//2),min(W,x+w//2+1)
            if left<right:
                i = y*W+left
                buf[i:i+right-left] = map(addp,buf[i:i+right-left],[color]*(right-left))
        for i,c in self.headland:
            buf[i] = c
        for i,c in self.tower:
            buf[i] = c
        pulse = .82+.15*sin(t*TAU/40+.3)
        stamp(buf,W,H,self.tower_x,self.lens_y,self.glow[min(4,round(4*pulse))])
        for i in self.glass:
            buf[i] = shade(0xFFD08A,int(235*pulse))
        crossing = (t-320)/84
        if 0<crossing<1:
            x = round(W*(.085+.53*crossing))
            y = min(H-1,horizon+max(1,round(H*.035)))
            visibility = _ambient_smooth(crossing/.13)*_ambient_smooth((1-crossing)/.13)
            size = max(2,round(W*.005))
            fill_row(buf,W,y,x,min(W,x+size),shade(0xFFD08A,int(174*visibility)))
        return buf


class Streetlamp(Scene):
    """An old amber streetlamp over fog and rain-dark cobblestones."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.x = lx = round(.35*(W-1))
        self.y = ly = round(.276*H)
        self.floor = floor = round(.73*H)
        self.bg = []
        self.fog = []
        r = max(2,round(H*.115))
        self.glow = make_sprite(0xFFC66E,r,8,2.5)
        self.remote = make_sprite(0xCEAE81,max(2,round(H*.037)),6,2.3)
        cx = lx+H*.018
        for y in range(H):
            v = y/H
            street = max(0.,(y-floor)/max(1,H-floor))
            street_fade = _ambient_smooth(street/.19)
            stones_w = max(3.,W*(.025+.048*street))
            p = 13*math.log1p(4.0*street)
            row = math.floor(p)
            gap_y = p-row
            for x in range(W):
                wx = (x-lx)/H
                fog = exp(-((wx+.05)/.43)**2-((v-.51)/.39)**2)
                c = mix(0x070C15,0x1C2430,int(177*fog))
                light = exp(-((x-cx)/(H*.382))**2-((v-.792)/.158)**2)
                if y>=floor:
                    s = x/stones_w+(.46 if row%2 else 0.)
                    col = math.floor(s)
                    seam = min(s-col,(col+1)-s)<.057 or gap_y<.095
                    tile = ((row*61 ^ col*43) % 15)-7
                    surface = 0x16191F if seam else 0x23272C
                    c = mix(c,surface,int((108+tile*5)*street_fade))
                    glitter = ((x*73^y*137)%113)<11 and .09<gap_y<.31
                    warm = int(light*(99+tile*5+(28 if glitter else 0))*(.27+.73*street_fade))
                    c = addp(c,shade(0x926334,warm))
                    if glitter:
                        c = addp(c,shade(0xF8B966,int(light*39)))
                else:
                    haze = exp(-(wx/.218)**2-((v-.355)/.253)**2)
                    c = addp(c,shade(0xB4773A,int(haze*62)))
                self.bg.append(c)
        pole = lx-max(2,round(H*.033))
        dark, trim = 0x0B1019,0x514331
        end = min(H-1,floor+round(H*.096))
        width = max(1,round(H*.006))
        for y in range(ly+round(H*.052),end+1):
            flare = width+int(width*2*_ambient_smooth((y-end+H*.085)/(H*.085)))
            fill_row(self.bg,W,y,max(0,pole-flare),min(W,pole+flare+1),dark)
            plot(self.bg,W,H,pole+min(1,flare),y,trim)
        line_set(self.bg,W,H,pole,ly+H*.081,pole+H*.018,ly+H*.018,dark)
        line_set(self.bg,W,H,pole+H*.015,ly+H*.022,lx,ly+H*.017,trim)
        self.lantern = []
        height = max(4,round(H*.075))
        r = max(2,round(H*.038))
        for row in range(height):
            y = ly-height//2+row
            q = row/max(1,height-1)
            roof = q < .24
            half = max(1,round(r*(.46+1.9*q if roof else 1.03-.43*q)))
            for dx in range(-half,half+1):
                x = lx+dx
                if 0<=x<W and 0<=y<H:
                    frame = roof or row==height-1 or abs(dx)==half
                    c = (0x6D563B if roof and dx<1 else 0x3A3027) if frame else 0
                    self.lantern.append((y*W+x,c))
        for y in range(round(H*.39),floor):
            # Bounded fog ribbons stay mostly left of the dark side of the street.
            factor = exp(-((y/H-.56)/.11)**2)*(.6+.4*sin(y/H*25)**2)
            if factor>.09:
                self.fog.append((y,factor))
        self.moths = [(rng.uniform(.045,.138),rng.uniform(.025,.095),rng.uniform(.85,1.65),
                       rng.random()*TAU,rng.random()*TAU) for _ in range(11)]

    def frame(self,t,dt):
        W,H = self.W,self.H
        buf = self.bg[:]
        density = .55+.40*sin(t*TAU/156-.45)
        for y,factor in self.fog:
            n = int(58*factor*density*(.72+.28*sin(t*.10+y/H*37)))
            center = W*(.24+.10*sin(t*.024+y/H*8))
            span = min(W*.45,H*(.26+factor*.13))
            for side in range(-3,4):
                left = max(0,round(center+span*(side-.5)*.24))
                right = min(W,round(center+span*(side+.5)*.24))
                if n and left<right:
                    ink = shade(0x1C2430,int(n*(1-(side/3.65)**2)**2))
                    i = y*W+left
                    buf[i:i+right-left] = map(addp,buf[i:i+right-left],[ink]*(right-left))
        reveal = _ambient_smooth((.43-density)/.36)
        if reveal:
            x,y = round(W*.637),round(H*.553)
            stamp(buf,W,H,x,y,self.remote[min(5,int(6*reveal))])
            line_set(buf,W,H,x,y,x,y+max(2,round(H*.074)),shade(0x3B3D42,int(106*reveal)))
            fill_row(buf,W,y,x,min(W,x+max(2,round(H*.011))),shade(0xEAB590,int(145*reveal)))
        age = t%76.8
        flicker = (.15*sin(48*age)**2*exp(-5*age)) if t>=76.8 and age<1.1 else 0.
        stamp(buf,W,H,self.x,self.y,self.glow[min(7,int(7.9*(1-flicker)))])
        core = shade(0xFFC66E,int(256*(1-flicker)))
        for i,color in self.lantern:
            buf[i] = color or core
        for r,s,speed,p,q in self.moths:
            a = t*speed+p
            x = self.x+H*(r*cos(a)+.020*sin(t*2.71+q))
            y = self.y+H*(s*sin(a+.61)+.016*cos(t*2.3+q))
            wing = max(1.,H*.006)*sin(t*28+q)
            moth = shade(0xC5AE89,int(143+70*sin(a)**2))
            ix,iy = round(x),round(y)
            plota(buf,W,H,ix,iy,moth)
            plot(buf,W,H,round(x-wing),iy+1,shade(moth,162))
            sx = round(self.x+(x-self.x)*1.9)
            sy = round(H*.813+(y-self.y)*.34)
            if 0<=sy<H and 0<=sx<W:
                for px in range(sx,min(W,sx+max(2,round(H*.01)))):
                    i = sy*W+px
                    buf[i] = shade(buf[i],194)
        return buf


class Mistwood(Scene):
    """A green dawn woodland with drifting shafts and an occasional deer."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.ground = round(H*.79)
        base = []
        for y in range(H):
            v = y/H
            meadow = _ambient_smooth((v-.65)/.35)
            for x in range(W):
                u = x/W
                haze = exp(-((u-.57)/.45)**2-((v-.48)/.39)**2)
                c = mix(0x6F8F7A,0xD5E0D8,int(56+191*haze))
                grass = .67+.23*sin(9*u+19*v)+.10*sin(23*u-13*v)
                soil = mix(0x334D3B,0x778556,int(256*grass))
                base.append(mix(c,soil,int(meadow*222)))
        for layer,(count,ground,ink,thickness) in enumerate(
                ((38,.72,0x7C9C89,.0038),(24,.80,0x537360,.007),
                 (12,.89,0x364F3F,.012),(5,.98,0x1E2B27,.020))):
            plane = base if layer<3 else [-1]*(W*H)
            for i in range(count):
                u = (i+rng.uniform(.13,.85))/count
                if layer>=2:
                    # Leave a clearing through the middle even at narrow viewport sizes.
                    u = .64+.40*u if i>=count//2 else .68*u
                x = u*W
                foot = min(H-1,round(H*(ground+rng.uniform(-.031,.041))))
                length = H*rng.uniform(.39+.12*layer,.71+.11*layer)
                width = max(1,round(H*thickness*rng.uniform(.63,1.25)))
                lean = rng.uniform(-.095,.095)*H
                tint = mix(ink,0x9BB091,rng.randrange(0,40 if layer<2 else 21))
                self._tree(plane,x,foot,length,width,lean,tint,layer)
        # Low ferns soften the bottom of the close silhouette.
        for _ in range(40):
            x = rng.uniform(0,W)
            if abs(x/W-.55)<.16:
                continue
            y = rng.uniform(.935,1.01)*H
            r = H*rng.uniform(.014,.043)
            c = rng.choice((0x213A2C,0x2C4432,0x35513A))
            for i in range(5):
                dx = (i-2)*r*.68
                ex,ey = x+dx,y-r*(1.2-.21*abs(i-2))
                line_set(plane,W,H,x,y,ex,ey,c)
                self._oval(plane,ex,ey,max(1,round(r*.18)),max(1,round(r*.25)),c)
        self.near = self._spans(plane,W,H)
        self.backgrounds = []
        colors = set(base)
        for level in range(13):
            temperature = level/12
            tones = {}
            for c in colors:
                # Warm the lit mist much more than the shaded trunks.
                n = (c>>8)&255
                target = addp(c,rgb(42,23,0))
                tones[c] = mix(c,target,int(227*temperature*n/255))
            self.backgrounds.append([tones[c] for c in base])
        self.motes = [(rng.random(),rng.random(),rng.uniform(.20,.68),rng.random()*TAU)
                      for _ in range(24)]
        self.shafts = []
        for origin, width, power in ((.33,.049,54),(.56,.044,67),(.80,.032,48)):
            profile = []
            for y in range(round(H*.10),round(H*.87)):
                v = y/H
                radius = max(1,round(W*width*(.36+.79*v)))
                along = _ambient_smooth((v-.08)/.19)*_ambient_smooth((.89-v)/.27)
                weights = bytes(round(255*along*(1-(x/radius)**2)**2)
                                for x in range(-radius,radius+1))
                profile.append((y,radius,weights))
            self.shafts.append((origin,width,power,profile))

    def _spans(self,plane,width,height):
        spans=[]
        for y in range(height):
            row=y*width
            start=None
            for x in range(width):
                if plane[row+x]>=0:
                    if start is None:
                        start=x
                elif start is not None:
                    spans.append((row+start,plane[row+start:row+x]))
                    start=None
            if start is not None:
                spans.append((row+start,plane[row+start:row+width]))
        return spans

    def _tree(self,buf,x,foot,height,width,lean,color,layer):
        W,H = self.W,self.H
        top = foot-height
        for y in range(max(0,round(top)),foot+1):
            p = (foot-y)/height
            cx = round(x+lean*p*p)
            half = max(0,round(width*(1-.82*p)))
            fill_row(buf,W,y,max(0,cx-half),min(W,cx+half+1),color)
            if layer>=2 and half>=2:
                plot(buf,W,H,cx-half+1,y,mix(color,0x7B8760,34))
        for i in range(4):
            p = .44+i*.137
            sy = foot-height*p
            if sy<0:
                continue
            sx = x+lean*p*p
            sign = -1 if i%2 else 1
            length = height*(.11+.031*i)
            ex = sx+sign*length
            ey = sy-length*(.72+.16*i)
            line_set(buf,W,H,sx,sy,ex,ey,color)
            if layer>=2:
                line_set(buf,W,H,sx,sy-1,ex,ey-1,color)
            line_set(buf,W,H,(sx+ex)*.5,(sy+ey)*.5,ex-sign*length*.11,ey-length*.39,color)
            for j in range(3):
                fx = sx+sign*length*(.86+.19*j)
                fy = ey+length*(.11-.21*j)
                rx=max(1,round(length*(.31+.04*j)))
                ry=max(1,round(length*.18))
                self._oval(buf,fx,fy,rx,ry,color)

    def _oval(self,buf,x,y,rx,ry,c):
        W,H = self.W,self.H
        cx,cy = round(x),round(y)
        for dy in range(max(-ry,-cy),min(ry,H-1-cy)+1):
            half = round(rx*sqrt(max(0.,1-(dy/ry)**2)))
            fill_row(buf,W,cy+dy,max(0,cx-half),min(W,cx+half+1),c)

    def _shaft(self,buf,origin,angle,power,profile):
        W = self.W
        palette = [shade(0xFFE2A0,round(power*x/255)) for x in range(256)]
        get = palette.__getitem__
        for y,radius,weights in profile:
            left = round(origin+angle*y)-radius
            x0,x1 = max(0,left),min(W,left+len(weights))
            if x0<x1:
                row = y*W
                buf[row+x0:row+x1] = map(addp,buf[row+x0:row+x1],
                                         map(get,weights[x0-left:x1-left]))

    def _deer(self,buf,t):
        W,H = self.W,self.H
        crossing = (t-68)%187
        if crossing>=15:
            return
        x = W*(-.07+1.14*crossing/15)
        y = self.ground+H*(.044+.012*sin(crossing*.3))
        size = max(2.1,H*.021)
        c = 0x25352A
        self._oval(buf,x,y-size*1.72,max(2,round(size*1.22)),max(1,round(size*.50)),c)
        self._oval(buf,x+size*.73,y-size*2.26,max(1,round(size*.38)),max(1,round(size*.69)),c)
        self._oval(buf,x+size*1.21,y-size*2.95,max(1,round(size*.47)),max(1,round(size*.28)),c)
        line_set(buf,W,H,x+size*.97,y-size*3.08,x+size*.64,y-size*3.63,c)
        line_set(buf,W,H,x+size*1.13,y-size*3.16,x+size*1.15,y-size*3.74,c)
        line_set(buf,W,H,x+size*1.14,y-size*3.54,x+size*1.48,y-size*3.83,c)
        for i,offset in enumerate((-.71,-.39,.49,.73)):
            stride = .67*sin(crossing*8+i*2.4)
            a,b = x+size*offset,y-size*1.57
            knee,foot = a+size*stride*.46,a+size*stride
            lift = max(0.,size*.31*cos(crossing*8+i*2.4))
            for dx in (0,max(1,round(size*.18))):
                line_set(buf,W,H,a+dx,b,knee+dx,y-size*.69,c)
                line_set(buf,W,H,knee+dx,y-size*.69,foot+dx,y-lift,c)

    def frame(self,t,dt):
        W,H = self.W,self.H
        warmth = _ambient_smooth(t/600)
        buf = self.backgrounds[round(warmth*12)][:]
        beams = []
        for i,(origin,width,power,profile) in enumerate(self.shafts):
            x = W*(origin+.043*sin(t*.029+i*1.86))
            spread = W*width
            angle = -.38+.076*sin(t*.032+i*1.3)
            power *= (.71+.46*warmth)*(.85+.15*sin(t*.073+i))
            beams.append((x,angle,spread))
            self._shaft(buf,x,angle,power,profile)
        for x,y,speed,phase in self.motes:
            j = min(H-1,round(H*(.21+.62*((y-t*speed*.008)%1))))
            i = round(W*((x+t*.0032+.011*sin(t*.27+phase))%1))
            light = max((max(0.,1-abs(i-origin-angle*j)/span)
                         for origin,angle,span in beams),default=0.)
            if light:
                plota(buf,W,H,i,j,shade(0xFFE2A0,int(123*light)))
        self._deer(buf,t)
        for start,colors in self.near:
            buf[start:start+len(colors)] = colors
        return buf


class Metropolis(Scene):
    """Amber streets and a river seen from above as late-night traffic fades."""
    fps = 15
    gfx_fps = 22
    gfx_dither = True

    @staticmethod
    def _river(v):
        return .56+.22*(v-.5)+.127*sin(v*TAU+.49)

    @classmethod
    def _land(cls,u,v):
        river = abs(u-cls._river(v))<.058+.016*sin(v*9+.5)**2
        park = ((u-.22)/.12)**2+((v-.68)/.156)**2<1
        return not (river or park)

    def setup(self):
        W,H,rng = self.W,self.H,self.rng
        self.pad_x,self.pad_y = round(W*.041)+2,round(H*.043)+2
        self.map_w,self.map_h = MW,MH = W+2*self.pad_x,H+2*self.pad_y
        board = []
        for y in range(MH):
            v = (y-self.pad_y)/H
            for x in range(MW):
                u = (x-self.pad_x)/W
                if self._land(u,v):
                    bx = int((u+.08*sin(v*7))*66)
                    by = int((v+.06*sin(u*7))*57)
                    hash_ = (bx*71 ^ by*119 ^ bx*by*13)%23
                    brightness = 81+hash_*4
                    light = 22*exp(-((u-.48)/.32)**2-((v-.48)/.44)**2)
                    c = shade(0x392A24,int(brightness+light))
                    if hash_%7==0 and (x*11 ^ y*7)%37<3:
                        c = addp(c,0x271D16)
                elif abs(u-self._river(v))<.074:
                    glint = int(7*exp(-((u-self._river(v)-.022)/.013)**2))
                    c = addp(0x070F1A,rgb(glint//2,glint,glint))
                else:
                    c = shade(0x17241F,106+(x*23 ^ y*31)%31)
                board.append(c)
        self.cars = []
        for vertical in (False,True):
            for i in range(1,15 if vertical else 13):
                p = i/(15 if vertical else 13)+rng.uniform(-.017,.017)
                arterial = i%4==0
                ink = 0xAF804D if arterial else 0x5E4933 if i%2 else 0x7B5D39
                width = max(2,round(H*.006)) if arterial else 1
                road=[]
                for j in range(65):
                    v = j/64
                    block = min(2,int(p*3))
                    curve = p+.032*sin(v*5+block*.82)+.008*cos(v*12+i*.29)
                    if vertical:
                        u,y = curve+.10*(v-.5),v
                    else:
                        u,y = v,curve+.11*(v-.5)+.026*sin(v*7.5)
                    if self._land(u,y):
                        road.append(self._point(u,y))
                    elif len(road)>1:
                        self._road(board,road,ink,width,2 if arterial else 1)
                        road=[]
                    else:
                        road=[]
                if len(road)>1:
                    self._road(board,road,ink,width,2 if arterial else 1)
        for y in (.31,.741):
            pts=[self._point(.26+.59*i/27,y+.026*sin(i/27*TAU+i*.008))
                 for i in range(28)]
            self._road(board,pts,0xB17A44,max(1,round(H*.005)),2)
        highway=[]
        for i in range(53):
            t=i/52
            u = .105+.75*t+.127*sin((t-.08)*TAU)
            v = .023+.934*t
            highway.append(self._point(u,v))
        self._road(board,highway,0x563821,max(3,round(H*.02)),0)
        self._road(board,highway,0xDB9A57,max(2,round(H*.009)),10)
        self.roadmap=board
        self.clouds = ((.30,.24,.22),(.66,.52,.26),(.43,.79,.36))

    def _point(self,x,y):
        return self.pad_x+x*self.W,self.pad_y+y*self.H

    def _road(self,buf,points,ink,width,cars):
        MW,MH = self.map_w,self.map_h
        stroke = _gfx_line_set if self.gfx else line_set
        for x in range(-(width//2),width-width//2):
            for (ax,ay),(bx,by) in zip(points,points[1:]):
                stroke(buf,MW,MH,ax+x,ay,bx+x,by,ink)
        if not cars:
            return
        # Equal-distance waypoints keep traffic moving at a steady speed on curves.
        distance=0.
        spacing=max(1.5,self.H*.011)
        track=[points[0]]
        for (ax,ay),(bx,by) in zip(points,points[1:]):
            d=hypot(bx-ax,by-ay)
            while d and distance+spacing<=d:
                distance += spacing
                u=distance/d
                track.append((ax+(bx-ax)*u,ay+(by-ay)*u))
            distance-=d
        if len(track)<5:
            return
        rng=self.rng
        for i in range(cars):
            direction=1 if rng.random()>.46 else -1
            self.cars.append((track,rng.random(),direction*rng.uniform(.047,.082),
                              rng.random(),0xFFE8C9 if direction>0 else 0xDB4F42))

    def frame(self,t,dt):
        W,H,MW = self.W,self.H,self.map_w
        dx = self.pad_x+round(W*.028*sin(t*.008))
        dy = self.pad_y+round(H*.028*sin(t*.006+.9))
        buf=[]
        for y in range(dy,dy+H):
            start=y*MW+dx
            buf.extend(self.roadmap[start:start+W])
        activity = 1-.70*_ambient_smooth(t/600)
        for track,start,speed,threshold,color in self.cars:
            fade = _ambient_smooth((activity-threshold+.11)/.15)
            if not fade:
                continue
            p = ((start+t*speed)%1)*(len(track)-1)
            k = min(int(p),len(track)-2)
            u = p-k
            a,b = track[k],track[k+1]
            x = round(a[0]+(b[0]-a[0])*u)-dx
            y = round(a[1]+(b[1]-a[1])*u)-dy
            plota(buf,W,H,x,y,shade(color,int(189*fade)))
            plota(buf,W,H,x+1,y,shade(color,int(52*fade)))
        for j,(u,v,width) in enumerate(self.clouds):
            x = W*(u+.24*sin(t*.007+j*2))
            cy = H*(v+.063*sin(t*.012+j))
            span = W*width
            high = H*(.064+.013*j)
            for y in range(max(0,round(cy-high)),min(H,round(cy+high))):
                d = (y-cy)/high
                n = 46*max(0.,1-d*d)**2
                center = x+.37*(y-cy)+W*.032*sin(y/H*21+t*.018+j)
                for band in range(-4,5):
                    ink = shade(0x454959,int(n*(1-(band/4.75)**2)**2))
                    left = max(0,round(center+span*(band-.5)/4.5))
                    right = min(W,round(center+span*(band+.5)/4.5))
                    if ink and left<right:
                        i = y*W+left
                        buf[i:i+right-left] = map(addp,buf[i:i+right-left],[ink]*(right-left))
        return buf

class Sandcastle(Scene):
    """One afternoon on a beach, drawn from individually growing sand forms."""

    gfx_fps = 22
    mask = 0xF8FCF8
    STAGES = (('arrival', 0, 40), ('foundation', 40, 80),
              ('towers', 120, 120), ('details', 240, 90),
              ('moat', 330, 60), ('tide', 390, 120),
              ('epilogue', 510, 30))

    @staticmethod
    def ease(x):
        x = max(0., min(1., x))
        return x*x*(3-2*x)

    @staticmethod
    def growth(t, start, duration):
        return Sandcastle.ease((t-start)/duration)

    def setup(self):
        self.episode = Episode(self.rng, self.STAGES)
        self.number = -1
        self._new_episode(0)

    def _new_episode(self, number):
        self.number = number
        r = self.episode.rng(number)
        self.layout = r.randrange(3)
        self.tower_count = 3 + r.randrange(3)
        self.failed_tower = r.randrange(self.tower_count)
        self.outcome = r.randrange(1, 4)
        forced = os.environ.get('FUN_OUTCOME')
        if forced in ('1', '2', '3'):
            self.outcome = int(forced)
        self.hat = r.choice((0xDC9476, 0x78A7A0, 0xE2C280, 0xA58AB0))
        self.suit = r.choice((0xD97566, 0x527B9B, 0x8C9364, 0xB66E87))
        self.bucket = r.choice((0xDC805B, 0x5C9EA2, 0xD2B45F))
        self.offset = r.uniform(-.025, .025)
        self.shells = [(r.uniform(.39,.71),r.uniform(.76,.88),r.choice((0xF7E6CD,0xCB9D8A,0xEDE1BB))) for _ in range(11)]
        self.specks = [(r.randrange(self.W),r.randrange(int(self.H*.58),self.H),r.randrange(-16,17)) for _ in range(min(1800,self.W*self.H//85))]
        self.tower_x = [(-.105 + i*.065) for i in range(self.tower_count)]
        if self.layout == 1:
            self.tower_x = [-.10,-.045,.045,.105][:self.tower_count] + ([.15] if self.tower_count == 5 else [])
        elif self.layout == 2:
            self.tower_x = [-.13,-.065,0,.065,.13][:self.tower_count]
        self.child_poses = self._make_child_poses()

    def _rect(self, b, x0, y0, x1, y1, c):
        W,H = self.W,self.H
        x0=max(0,int(x0)); x1=min(W,int(x1)); y0=max(0,int(y0)); y1=min(H,int(y1))
        if x1>x0:
            row=[c]*(x1-x0)
            for y in range(y0,y1): b[y*W+x0:y*W+x1]=row

    def _oval(self,b,cx,cy,rx,ry,c):
        W,H=self.W,self.H
        if rx<=0 or ry<=0:return
        for y in range(max(0,int(cy-ry)),min(H,int(cy+ry)+1)):
            q=1-((y-cy)/ry)**2
            if q>0:
                reach=rx*sqrt(q)
                self._rect(b,cx-reach,y,cx+reach+1,y+1,c)

    def _line(self,b,x0,y0,x1,y1,c,thick=1):
        for d in range(max(1,int(thick))):
            line_set(b,self.W,self.H,x0,y0+d,x1,y1+d,c)

    def _background(self,t):
        W,H=self.W,self.H
        dusk=self.ease((t-300)/220)
        sky_top=mix(0xBFE0EE,0xE7A0A0,int(dusk*210))
        sky_bottom=mix(0xE5EDF0,0xFFD79A,int(dusk*235))
        horizon=int(H*.395)
        sandline=int(H*.585)
        b=[0]*(W*H)
        for y in range(H):
            if y<horizon:
                c=mix(sky_top,sky_bottom,int(y/max(1,horizon)*255))
            elif y<sandline:
                d=(y-horizon)/max(1,sandline-horizon)
                c=mix(0x70B4B4,0x2E8C93,int(d*215))
                c=mix(c,0xE9C8A2,int(dusk*45))
            else:
                d=(y-sandline)/max(1,H-sandline)
                c=mix(0xE8D2A6,0xD2B581,int(d*90))
            b[y*W:(y+1)*W]=[c]*W
        # A shallow beach slope and bounded grain sit beneath all moving forms.
        for x,y,v in self.specks:
            if y >= sandline+H*.018*sin(x/W*7):
                i=y*W+x; b[i]=mix(b[i],0x897959,32+max(0,v))
        sun_x=int(W*(.81-.22*t/540)); sun_y=int(H*(.13+.20*t/540))
        self._oval(b,sun_x,sun_y,max(2,W*.021),max(2,H*.027),mix(0xFFF7D2,0xFCD084,int(dusk*170)))
        # Layered distant surf has independent slow phases, not a repeated story.
        for k in range(4):
            yy=H*(.43+k*.038)
            for x in range(0,W,max(1,W//150)):
                dx=x/W
                wave=H*.004*sin(dx*16+k*2+t*(.085+.009*k))
                self._line(b,x,yy+wave,x+max(1,W//150),yy+wave,0xB4D5D1)
        return b

    def _sand_and_water(self,b,t):
        W,H=self.W,self.H
        # The wet boundary advances continuously, then a single broad surge arrives.
        advance=self.ease((t-390)/120)
        surge=self.ease((t-482)/17)*(1-self.ease((t-505)/8))
        boundary=H*(.673+.060*advance+.053*surge)
        coast=int(H*.585)
        low=max(coast,int(boundary-H*.010))
        high=min(H,int(boundary+H*.010))
        # Fill whole rows first; only the narrow scalloped edge needs per-column work.
        for y in range(coast,low):
            depth=(y-coast)/max(1,boundary-coast)
            c=mix(0x6FAEB0,0x90B5A4,int(depth*160))
            b[y*W:(y+1)*W]=[c]*W
        for y in range(high,min(H,high+int(H*.049))):
            d=(y-high)/max(1,H*.049)
            c=mix(0xB79A6A,0xD4BA8C,int(d*190))
            b[y*W:(y+1)*W]=[c]*W
        for x in range(W):
            edge=boundary+H*.006*sin(x/W*14+t*.17)+H*.003*sin(x/W*33-t*.13)
            top=max(0,min(H,int(edge)))
            for y in range(low,top):
                b[y*W+x]=mix(0x81B4B0,0xA7B6A0,int((y-coast)/max(1,boundary-coast)*100))
            for y in range(top,high):
                b[y*W+x]=0xB79A6A
            foam_y=min(H-1,top-1)
            b[foam_y*W+x]=0xF5E9D7
            if foam_y+1<H:b[(foam_y+1)*W+x]=0xF5E9D7
        for j in range(3):
            yy=coast+(boundary-coast)*(.22+j*.24)
            for x in range(0,W,max(1,W//120)):
                y=yy+H*.0025*sin(x/W*19+t*.13+j*2)
                self._line(b,x,y,x+max(1,W//120),y,0xC0D9CE)
        return boundary

    def _footprints(self,b,t):
        W,H=self.W,self.H
        # Time-addressed footprints persist without accumulating frame history.
        steps=[]
        for i in range(13):
            when=6+i*3.2
            if t>=when:steps.append((.02+i*.031,.76+(.008 if i%2 else 0)))
        for trip in range(2):
            for i in range(9):
                when=52+trip*32+i*2.5
                if t>=when:steps.append((.48-i*.024,.75+(.009 if i%2 else 0)))
        if t>=512:
            for i in range(min(12,int((t-512)*.75))):steps.append((.41-i*.029,.77+(.008 if i%2 else 0)))
        for x,y in steps[:48]:
            self._oval(b,W*x,H*y,max(1,W*.004),max(1,H*.003),0xB59A72)

    def _tower(self,b,x,ground,w,h,g,shade_left=True):
        if g<=0:return
        W,H=self.W,self.H
        width=max(1,W*w*(.55+.45*g)); height=max(1,H*h*g)
        x=W*x; y=H*ground
        self._oval(b,x,y,max(2,width*.72),max(1,H*.01),0xB69669)
        self._rect(b,x-width*.50,y-height,x+width*.50,y,0xCCAF7D)
        self._rect(b,x-width*.50,y-height,x-width*.18,y,0xB89A6C)
        self._rect(b,x+width*.29,y-height,x+width*.50,y,0xE4C99A)
        self._oval(b,x,y-height,width*.50,max(1,H*.012),0xEAD3A8)
        if g>.75:
            for j in range(4):
                xx=x-width*.49+j*width*.27
                self._rect(b,xx,y-height-H*.011*g,xx+width*.16,y-height,0xD8BC8B)
            self._rect(b,x-width*.065,y-height*.77,x+width*.05,y-height*.62,0x8E7656)

    def _castle(self,b,t):
        W,H=self.W,self.H
        cx=.555+self.offset; ground=.765
        if 19<t<53:
            outline=self.growth(t,19,19)
            left=W*(cx-.125); right=W*(cx+.125)
            top=H*(ground-.025); bottom=H*(ground+.012)
            self._line(b,left,top,left+(right-left)*outline,top,0xAA8F69)
            self._line(b,left,top,left,bottom*outline+top*(1-outline),0xAA8F69)
            self._line(b,right,top,right,bottom*outline+top*(1-outline),0xAA8F69)
            self._line(b,left,bottom,right*outline+left*(1-outline),bottom,0xAA8F69)
        foundation=self.growth(t,43,72)
        if not foundation:return
        # Sand platform rises with patting; every architectural element grows separately.
        self._oval(b,W*cx,H*ground,W*.145*foundation,H*.022*foundation,0xBA9A6D)
        self._rect(b,W*(cx-.13)*foundation+W*cx*(1-foundation),H*(ground-.018*foundation),
                   W*(cx+.13)*foundation+W*cx*(1-foundation),H*ground,0xD7B783)
        keep=self.growth(t,185,30)
        self._tower(b,cx,ground,.055,.105,keep)
        for i,dx in enumerate(self.tower_x):
            start=125+i*21
            grow=self.growth(t,start,18)
            if i==self.failed_tower:
                collapse=self.growth(t,start+19,8)*(1-self.growth(t,start+43,18))
                grow*=1-collapse*.88
            if t>=488 and self.outcome>=2:
                if self.outcome==3:grow*=1-self.growth(t,488,18)
                elif i==self.failed_tower:grow*=1-self.growth(t,488,18)
            self._tower(b,cx+dx,ground,.038,.065+(i%2)*.022,grow)
            if t>=start+14 and t<start+24:
                self._oval(b,W*(cx+dx),H*(ground-.08),W*.015,H*.01*(1-self.growth(t,start+14,10)),0xE8D2A6)
        wall=self.growth(t,244,47)
        if t>=488:
            wall*=1-self.growth(t,488,20) if self.outcome==3 else 1-self.growth(t,488,20)*.65 if self.outcome==2 else 1
        if wall>0:
            top=ground-.050*wall
            self._rect(b,W*(cx-.10),H*top,W*(cx+.10),H*(ground-.012),0xC9A978)
            self._rect(b,W*(cx-.10),H*top,W*(cx-.085),H*(ground-.012),0xA98B63)
            for i in range(14):
                if t>=258+i*3:
                    x=W*(cx-.095+i*.014)
                    self._rect(b,x,H*(top-.009),x+W*.008,H*top,0xE2C495)
            # Arch opening and individually appearing windows.
            if t>=283:
                self._oval(b,W*cx,H*(ground-.036),W*.014,H*.018,0x806A4B)
                self._rect(b,W*(cx-.014),H*(ground-.036),W*(cx+.014),H*ground,0x806A4B)
            for i in range(4):
                if t>=295+i*6:
                    x=W*(cx-.067+i*.044)
                    self._rect(b,x,H*(ground-.041),x+W*.006,H*(ground-.035),0x907758)
        for i in range(7):
            if t>=303+i*4:
                xx=W*(cx-.13+i*.043)
                self._tower(b,xx/W,ground,.009,.023,self.growth(t,303+i*4,8))
        if t>=314:
            flag=self.growth(t,314,12)
            fx=W*(cx+.026); fy=H*(ground-.105)
            self._line(b,fx,fy,fx,fy-H*.065*flag,0x67583F,max(1,W*.002))
            self._oval(b,fx+W*.011,fy-H*.056*flag,W*.013*flag,H*.007,0x7B9C66)
        for x,y,c in self.shells:
            if t>300+(x-.39)*100:self._oval(b,W*x,H*y,max(1,W*.004),max(1,H*.004),c)
        if t>=333:
            m=self.growth(t,333,40)
            self._oval(b,W*cx,H*(ground+.023),W*.16*m,H*.028*m,0xA9895D)
            self._oval(b,W*cx,H*(ground+.023),W*.13*m,H*.018*m,0xD3B581)
            if t>=395:
                fill=self.growth(t,395,99)
                self._oval(b,W*cx,H*(ground+.023),W*.15*m,H*.021*m, mix(0xA9895D,0x65A7A4,int(fill*230)))
            channel=self.growth(t,352,35)
            self._line(b,W*(cx+.135),H*(ground+.035),W*(cx+.25*channel),H*.685,0xA9895D,max(1,H*.009))
            if t>=415:
                self._line(b,W*(cx+.135),H*(ground+.035),W*(cx+.25),H*.685,0x72AAA7,max(1,H*.006))
        if t>=488 and self.outcome==3:
            self._oval(b,W*cx,H*ground,W*.115*self.growth(t,488,18),H*.013,0xB79A6A)

    def _make_child_poses(self):
        """Six opaque-on-transparent poses, rasterized once per episode and size."""
        size=max(14,self.H*.145)
        sw=max(18,round(size*1.35)); sh=max(19,round(size*1.19))
        artist=Sandcastle.__new__(Sandcastle)
        artist.W,artist.H=sw,sh
        cx=sw*.48; feet=sh-1; skin=0xB88362
        poses=[]
        # Walking A/B, digging, patting, bucket flip, admiring/waving.
        for pose in range(6):
            b=[-1]*(sw*sh)
            kick=(.13 if pose==0 else -.13 if pose==1 else 0)*size
            artist._line(b,cx-size*.07,feet-size*.31,cx-size*.10+kick,feet,skin,max(1,size*.065))
            artist._line(b,cx+size*.07,feet-size*.31,cx+size*.10-kick,feet,skin,max(1,size*.065))
            artist._oval(b,cx,feet-size*.43,size*.17,size*.23,self.suit)
            left_y=feet-size*(.48 if pose in (0,1) else .24 if pose==2 else .33 if pose==3 else .82 if pose==4 else .72)
            right_y=feet-size*(.35 if pose in (0,1,2,3) else .78 if pose==4 else .68)
            artist._line(b,cx-size*.12,feet-size*.55,cx-size*.24,left_y,skin,max(1,size*.06))
            artist._line(b,cx+size*.12,feet-size*.55,cx+size*.23,right_y,skin,max(1,size*.06))
            artist._oval(b,cx,feet-size*.79,size*.17,size*.19,skin)
            artist._oval(b,cx,feet-size*.94,size*.25,size*.08,self.hat)
            artist._rect(b,cx-size*.15,feet-size*1.01,cx+size*.15,feet-size*.94,self.hat)
            artist._oval(b,cx+size*.075,feet-size*.80,max(1,size*.013),max(1,size*.013),0x4B3E36)
            bx=cx-size*.24; by=left_y+size*.11
            if pose==4:by=feet-size*.85
            artist._rect(b,bx-size*.10,by-size*.13,bx+size*.10,by+size*.12,self.bucket)
            rim=by+size*.12 if pose==4 else by-size*.13
            artist._line(b,bx-size*.09,rim,bx+size*.09,rim,0xF1D8AD)
            if pose in (0,1,2,3):
                artist._line(b,cx+size*.23,right_y,cx+size*.32,feet-size*.08,0x775B43,max(1,size*.027))
                artist._oval(b,cx+size*.32,feet-size*.08,size*.055,size*.05,0xA1A3A1)
            poses.append(b)
        return sw,sh,poses

    def _child(self,b,t):
        W,H=self.W,self.H
        if t<3 or t>537:return
        if t<39:x=.02+.40*self.ease((t-3)/33)
        elif t<120:
            phase=(t-40)%32
            x=.44-.22*self.ease(phase/13) if phase<16 else .22+.22*self.ease((phase-16)/14)
        elif t<330:x=.405+.018*sin(t*.10)
        elif t<387:x=.40+.06*self.ease((t-330)/44)
        elif t<510:x=.39+(.009*sin(t*1.4) if self.outcome==1 and t>490 else 0)
        else:x=.39-.43*self.ease((t-510)/27)
        walking=(t<40 or 40<=t<120 or t>=510)
        if walking:pose=int(t*1.8)%2
        elif t<120:pose=2
        elif t<240:
            collapse_time=125+self.failed_tower*21+24
            pose=5 if collapse_time<=t<collapse_time+8 else 4 if ((t-120)%21)<9 else 2
        elif t<330:pose=3 if int(t*.55)%2 else 2
        elif t<390:pose=2 if int(t*.7)%2 else 3
        elif t>490 and t<510:pose=5 if int(t*1.4)%2 else 4
        else:pose=5
        sw,sh,poses=self.child_poses
        feet=int(H*(.773+.005*sin(t*.22) if walking else .773))
        cx=int(W*x)
        shadow=sh*(.30+.45*t/540)
        self._oval(b,cx+shadow*.35,feet+H*.004,shadow,max(1,sh*.045),0xBBA274)
        left=cx-sw//2; top=feet-sh+1
        sprite=poses[pose]
        for yy in range(sh):
            y=top+yy
            if not 0<=y<H:continue
            src=yy*sw
            dst=y*W+left
            for xx in range(sw):
                if 0<=left+xx<W and sprite[src+xx]>=0:
                    b[dst+xx]=sprite[src+xx]

    def _wildlife(self,b,t):
        W,H=self.W,self.H
        for j in range(2):
            x=W*((.12+j*.4+t*(.00036+j*.00012))%1.)
            y=H*(.20+j*.075+.012*sin(t*.14+j))
            wing=H*.011*sin(t*.55+j)
            self._line(b,x-W*.014,y+wing,x,y,0x58676B)
            self._line(b,x,y,x+W*.014,y-wing,0x58676B)
        if t>345 and t<525:
            x=W*(.78-.00038*(t-345)+.008*sin(t*.19)); y=H*.792
            self._oval(b,x,y,W*.008,H*.006,0xB76F58)
            for d in (-1,1):
                for k in range(2):self._line(b,x+d*W*.006,y,x+d*W*(.011+k*.004),y+H*.007,0x9B6452)
        if 363<t<435:
            x=W*(.83-.001*(t-363)); y=H*.70
            self._oval(b,x,y,W*.011,H*.007,0xD8D2BE)
            self._line(b,x,y,x-W*.008,y+H*.018,0x716C62)

    def frame(self,t,dt):
        number,local,opacity=self.episode.clock(t)
        if number!=self.number:self._new_episode(number)
        b=self._background(local)
        self._sand_and_water(b,local)
        self._footprints(b,local)
        self._castle(b,local)
        self._child(b,local)
        self._wildlife(b,local)
        if opacity<1:
            level=int(opacity*256)
            palette={c:shade(c,level) for c in set(b)}
            b=list(map(palette.__getitem__,b))
        return b
