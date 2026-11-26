# Legacy savers used by the launcher alongside the Python scene catalog.

dvd() {  # bouncing hostname that changes colour on every wall hit
  local t=" ~ $(hostname) ~ " w x=3 y=3 dx=2 dy=1 c=1 n=0 R C
  w=${#t}
  read -r R C < <(stty size </dev/tty)
  while :; do
    printf '\e[%d;%dH%*s' "$y" "$x" "$w" ''
    x=$((x+dx)); y=$((y+dy))
    if (( x<=1 ));     then x=1;       dx=2;  c=$((c%6+1)); fi
    if (( x+w>C ));    then x=$((C-w)); dx=-2; c=$((c%6+1)); fi
    if (( y<=1 ));     then y=1;       dy=1;  c=$((c%6+1)); fi
    if (( y>=R ));     then y=$R;      dy=-1; c=$((c%6+1)); fi
    printf '\e[1;3%dm\e[%d;%dH%s\e[0m' "$c" "$y" "$x" "$t"
    sleep 0.05
    (( ++n % 100 == 0 )) && read -r R C < <(stty size </dev/tty)
  done
}

cow() {  # rotating fortune + cow, rainbow coloured
  local cows=(tux cow dragon stegosaurus bunny koala elephant moose sheep turtle vader kitty ghostbusters small)
  colour() { if command -v lolcat >/dev/null; then lolcat -f; else cat; fi; }
  while :; do
    clear; echo; echo
    f=$(shuf -n1 -e "${cows[@]}")
    { fortune -s 2>/dev/null || echo "Hello from your little machine!"; } \
      | { cowsay -f "$f" 2>/dev/null || cowsay; } | colour
    sleep 45
  done
}

slrun() {  # sl trains now and then; $1 = seconds budget
  local end=$((SECONDS+$1-20)) i
  while (( SECONDS < end )); do
    sl -e; clear
    for ((i=0; i<RANDOM%60+30 && SECONDS<end; i++)); do sleep 1; done
  done
}

plasma() {  # truecolor half-block plasma
exec python3 - <<'PYEOF'
import math, shutil, sys, time
out = sys.stdout
N = 32
def mk(i):
    a = i / N * 2 * math.pi
    return (int(127 + 127*math.sin(a)), int(127 + 127*math.sin(a + 2.1)), int(127 + 127*math.sin(a + 4.2)))
P = [mk(i) for i in range(N)]
FG = ["\x1b[38;2;%d;%d;%dm" % c for c in P]
BG = ["\x1b[48;2;%d;%d;%dm" % c for c in P]
sin = math.sin
t = 0.0
size = None
try:
    out.write("\x1b[?25l\x1b[2J")
    while True:
        t0 = time.time()
        cols, rows = shutil.get_terminal_size()
        H = rows * 2
        if (cols, rows) != size:
            size = (cols, rows)
            cx, cy = cols / 2.0, H / 2.0
            D = [[math.hypot(x - cx, y - cy) * 0.09 for x in range(cols)] for y in range(H)]
            out.write("\x1b[2J")
        Ax = [sin(x * 0.045 + t) for x in range(cols)]
        By = [sin(y * 0.06 - t * 1.3) for y in range(H)]
        Cs = [sin(s * 0.035 + t * 0.7) for s in range(cols + H)]
        t11 = t * 1.1
        lines = []
        for y in range(0, H - 1, 2):
            b0 = By[y]; b1 = By[y + 1]; d0 = D[y]; d1 = D[y + 1]
            prev = None
            line = []
            for x in range(cols):
                a = Ax[x]
                i0 = int((a + b0 + Cs[x + y] + sin(d0[x] - t11) + 4) * 4) % N
                i1 = int((a + b1 + Cs[x + y + 1] + sin(d1[x] - t11) + 4) * 4) % N
                k = (i0, i1)
                if k != prev:
                    line.append(FG[i0] + BG[i1]); prev = k
                line.append("▀")
            lines.append("".join(line))
        out.write("\x1b[H" + "\x1b[0m\r\n".join(lines) + "\x1b[0m")
        out.flush()
        t += 0.06
        time.sleep(max(0.01, 1 / 10.0 - (time.time() - t0)))
except KeyboardInterrupt:
    pass
PYEOF
}

stars() {  # warp-speed starfield
exec python3 - <<'PYEOF'
import random, shutil, sys, time
out = sys.stdout
def mk():
    return [random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.1, 1.0)]
stars = []; size = None; prev = []
try:
    out.write("\x1b[?25l\x1b[2J")
    while True:
        t0 = time.time()
        cols, rows = shutil.get_terminal_size()
        if (cols, rows) != size:
            size = (cols, rows)
            stars = [mk() for _ in range(max(60, cols * rows // 7))]
            prev = []
            out.write("\x1b[2J")
        buf = ["\x1b[0m"]
        for (px, py) in prev:
            buf.append("\x1b[%d;%dH " % (py, px))
        prev = []
        for s in stars:
            s[2] -= 0.012
            if s[2] <= 0.03:
                s[:] = mk(); s[2] = 1.0
            z = s[2]
            px = int(cols / 2 + s[0] / z * cols / 2)
            py = int(rows / 2 + s[1] / z * rows / 2)
            if 1 <= px <= cols and 1 <= py <= rows:
                ch = "." if z > 0.6 else "+" if z > 0.3 else "*" if z > 0.12 else "#"
                g = 232 + int((1 - z) * 23)
                buf.append("\x1b[%d;%dH\x1b[38;5;%dm%s" % (py, px, g, ch))
                prev.append((px, py))
        out.write("".join(buf)); out.flush()
        time.sleep(max(0.005, 1 / 30.0 - (time.time() - t0)))
except KeyboardInterrupt:
    pass
PYEOF
}

life() {  # Conway's Game of Life with age colouring, auto-reseeds
exec python3 - <<'PYEOF'
import random, shutil, sys, time
out = sys.stdout
def col(a):
    f = min(a, 39) / 39.0
    return (int(120 + 135 * f), int(255 - 175 * f), int(230 - 70 * f))
COL = {-1: (10, 10, 18)}
for a in range(1, 40): COL[a] = col(a)
FG = {k: "\x1b[38;2;%d;%d;%dm" % v for k, v in COL.items()}
BG = {k: "\x1b[48;2;%d;%d;%dm" % v for k, v in COL.items()}
def seed(W, H):
    return {(x, y): 1 for x in range(W) for y in range(H) if random.random() < 0.28}
def step(live, W, H):
    cnt = {}
    for (x, y) in live:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    k = ((x + dx) % W, (y + dy) % H)
                    cnt[k] = cnt.get(k, 0) + 1
    new = {}
    for k, n in cnt.items():
        if n == 3 or (n == 2 and k in live):
            new[k] = min(live.get(k, 0) + 1, 99)
    return new
def render(live, W, H):
    lines = []
    for y in range(0, H - 1, 2):
        line = []; prev = None
        for x in range(W):
            a = live.get((x, y)); b = live.get((x, y + 1))
            ka = -1 if a is None else min(a, 39)
            kb = -1 if b is None else min(b, 39)
            if (ka, kb) != prev:
                line.append(FG[ka] + BG[kb]); prev = (ka, kb)
            line.append("▀")
        lines.append("".join(line))
    return "\x1b[H" + "\x1b[0m\r\n".join(lines) + "\x1b[0m"
size = None; live = {}; hist = []; gen = 0
try:
    out.write("\x1b[?25l\x1b[2J")
    while True:
        t0 = time.time()
        cols, rows = shutil.get_terminal_size()
        W, H = cols, rows * 2
        if (cols, rows) != size:
            size = (cols, rows); live = seed(W, H); hist = []; gen = 0
            out.write("\x1b[2J")
        out.write(render(live, W, H)); out.flush()
        live = step(live, W, H); gen += 1
        hist.append(len(live)); hist = hist[-14:]
        if len(live) < 20 or gen > 1000 or (len(hist) == 14 and len(set(hist)) <= 3):
            live = seed(W, H); hist = []; gen = 0
        time.sleep(max(0.01, 1 / 9.0 - (time.time() - t0)))
except KeyboardInterrupt:
    pass
PYEOF
}
