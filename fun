#!/usr/bin/env bash
export FUN_GFX="${FUN_GFX:-1}"
# fun - cycles terminal screensavers, switching every FUN_MINUTES (default 10).
#
# Usage: fun                 cycle all screensavers in random order
#        FUN_MINUTES=30 fun  change the interval
#        fun --scene NAME    run one of the active python scenes (q / Ctrl-C quits)
#        fun --list          list the python scene names
#        fun --selftest      headless test of every scene (no terminal needed)
#        fun --test [SECS]   run every python scene SECS (default 6) in THIS terminal
#
# Graphics: FUN_RES=low|med|high|ultra (default ultra), FUN_GFX=0 for half-block
# Environment: FUN_MINUTES (10)  FUN_SECONDS (overrides minutes, for testing)
#              FUN_JITTER=1 (+-5 min randomness, off by default)
#              FUN_ONLY=regex (only run savers whose command matches)
#              Desktop locking and power settings always stay under desktop control.
export PATH="$PATH:/usr/games:/usr/local/games"
export CACA_DRIVER=ncurses      # keep libcaca inside the terminal, not its own window
SELF="$(readlink -f "$0")"
EXTRAS=/usr/local/lib/fun/extras.py
if [[ -f "${SELF%/*}/extras.py" ]]; then
  EXTRAS="${SELF%/*}/extras.py"
fi
SETTINGS="${EXTRAS%/*}/fun_settings.py"
if [[ -f "$SETTINGS" ]]; then eval "$(python3 "$SETTINGS" shell launcher)"; fi
export FUN_RES="${FUN_RES:-ultra}"
while [[ "$1" == --minutes || "$1" == --quality || "$1" == --order || "$1" == --scenes ]]; do
  opt=$1; val=${2-}; [[ -n "$val" ]] || { echo "fun: $opt needs a value" >&2; exit 2; }
  case "$opt" in
    --minutes) [[ "$val" =~ ^[0-9]+$ ]] && (( 10#$val >= 1 && 10#$val <= 1440 )) || { echo 'fun: invalid minutes' >&2; exit 2; }; FUN_MINUTES=$((10#$val)) ;;
    --quality) case "$val" in auto|ultra) FUN_RES=ultra;; medium|med) FUN_RES=med;; low|high) FUN_RES=$val;; *) echo 'fun: invalid quality' >&2; exit 2;; esac ;;
    --order) [[ "$val" == random || "$val" == sequential ]] || { echo 'fun: invalid order' >&2; exit 2; }; FUN_ORDER=$val ;;
    --scenes) FUN_SCENES=$val ;;
  esac
  shift 2
done
export FUN_RES
MINUTES="${FUN_MINUTES:-10}"
LOGDIR="${XDG_CACHE_HOME:-$HOME/.cache}/fun"
LOG="$LOGDIR/launcher.log"
mkdir -p "$LOGDIR" 2>/dev/null
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG" 2>/dev/null; }

# ---------- built-in savers ----------
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

# Put the terminal back in a sane state (cursor, autowrap, alt screen, colours, echo).
reset_term() { printf '\e[0m\e[?2026l\e[?7h\e[?25h\e[?1049l'; stty sane 2>/dev/null; }

case "$1" in
  --dvd)    dvd; exit ;;
  --cow)    cow; exit ;;
  --sl)     slrun "${2:-600}"; exit ;;
  --plasma) plasma; exit ;;
  --stars)  stars; exit ;;
  --life)   life; exit ;;
  --list)   python3 "$EXTRAS" --list; exit ;;
  --selftest) python3 "$EXTRAS" --selftest; exit ;;
  --scene)
    [ -n "$2" ] || { echo "usage: fun --scene NAME   (fun --list shows names)"; exit 1; }
    trap 'reset_term' EXIT
    python3 "$EXTRAS" "$2" <&0 &
    scene_pid=$!
    trap 'kill -TERM "$scene_pid" 2>/dev/null; wait "$scene_pid"; exit 130' INT TERM HUP
    wait "$scene_pid"; rc=$?
    exit "$rc" ;;
  --test)
    secs="${2:-6}"; pass=0; bad=0; badlist=""
    trap 'reset_term; exit 130' INT TERM HUP
    mapfile -t scenes < <(python3 "$EXTRAS" --list)
    for s in "${scenes[@]}"; do
      clear
      err=$(timeout --foreground -k 3 "$secs" python3 "$EXTRAS" "$s" 2>&1 >/dev/tty); rc=$?
      reset_term
      if [ "$rc" = 124 ] || [ "$rc" = 0 ]; then pass=$((pass+1)); printf 'PASS  %s\n' "$s"
      else bad=$((bad+1)); badlist="$badlist $s"; printf 'FAIL  %-14s rc=%s %s\n' "$s" "$rc" "$err"; fi
    done
    echo "---- $pass passed, $bad failed${badlist:+:$badlist}"
    [ "$bad" = 0 ]; exit $? ;;
esac

# Each entry owns an argv array. Shuffle the integer indexes, never shell text.
SAVERS=()
add_saver() {
  local need=$1 index=${#SAVERS[@]}
  shift
  command -v "$need" >/dev/null 2>&1 || return 0
  [[ -z "$FUN_ONLY" || "$*" =~ $FUN_ONLY ]] || return 0
  declare -ga "saver_$index"
  local -n argv="saver_$index"
  argv=("$@")
  SAVERS+=("$index")
}

scene_names=$(python3 "$EXTRAS" --list) || { echo "fun: cannot load scenes from $EXTRAS" >&2; exit 1; }
[[ -n "$scene_names" ]] || { echo "fun: no active scenes in $EXTRAS" >&2; exit 1; }
mapfile -t active <<< "$scene_names"
requested=()
contains_scene() {
  local wanted=$1 name
  shift
  for name in "$@"; do
    [[ $name == "$wanted" ]] && return 0
  done
  return 1
}

if [[ -z "${FUN_SCENES:-}" ]]; then
  add_saver cmatrix cmatrix -ab -u 2 -r
  add_saver cmatrix cmatrix -ab -u 3 -C green
  add_saver asciiquarium asciiquarium
  add_saver cbonsai cbonsai -l -i -t 0.06 -w 8
  add_saver pipes.sh pipes.sh -p 5 -f 60 -r 3000 -R
  add_saver nyancat nyancat
  add_saver cacafire cacafire
  add_saver cacademo cacademo
  add_saver aafire aafire -driver curses
  add_saver tty-clock tty-clock -s -c -C 5 -B
  add_saver cowsay "$SELF" --cow
  add_saver sl "$SELF" --sl
  for classic in plasma stars life dvd; do
    add_saver bash "$SELF" "--$classic"
  done
else
  if [[ "$FUN_SCENES" == *, || "$FUN_SCENES" == ,* || "$FUN_SCENES" == *,,* || "$FUN_SCENES" == *$'\n'* ]]; then
    echo 'fun: expected a comma-separated list of active scene names' >&2; exit 2
  fi
  IFS=, read -ra requested <<< "$FUN_SCENES"
  for scene in "${requested[@]}"; do
    if ! contains_scene "$scene" "${active[@]}"; then
      echo "fun: inactive or unknown scene '$scene' (see fun --list)" >&2; exit 2
    fi
  done
fi
for scene in "${active[@]}"; do
  if (( ! ${#requested[@]} )) || contains_scene "$scene" "${requested[@]}"; then
    add_saver python3 python3 "$EXTRAS" "$scene"
  fi
done
if (( ! ${#SAVERS[@]} )); then
  echo "fun: no enabled scenes match FUN_ONLY='$FUN_ONLY'" >&2; exit 1
fi

child=""
cleanup() { reset_term; clear; }
on_signal() {
  if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null; wait "$child" 2>/dev/null; fi
  cleanup; exit 0
}
trap on_signal INT TERM HUP
# TOML accepts fractional minutes; convert once before integer jitter arithmetic.
base_seconds=$(python3 -c 'import sys; print(round(float(sys.argv[1]) * 60))' "$MINUTES") || exit 2
log "start minutes=$MINUTES pid=$$"
echo "fun: starting, switching every ~${MINUTES} min. Ctrl-C to stop."; sleep 2
fails=0

while :; do
  if [[ "${FUN_ORDER:-random}" == sequential ]]; then order=("${SAVERS[@]}")
  else mapfile -t order < <(printf '%s\n' "${SAVERS[@]}" | shuf); fi
  for entry in "${order[@]}"; do
    declare -n argv="saver_$entry"
    cmd=("${argv[@]}")
    if [ -n "$FUN_SECONDS" ]; then secs=$FUN_SECONDS
    else
      jit=0; [ "${FUN_JITTER:-0}" = 1 ] && (( base_seconds >= 600 )) && jit=$((RANDOM%601-300))
      secs=$(( base_seconds + jit ))
    fi
    (( secs < 5 )) && secs=5
    if [[ ${cmd[0]} == "$SELF" && ${cmd[1]} == --sl ]]; then cmd+=("$secs"); fi

    clear; printf '\e[?25l'
    start=$SECONDS
    # background + wait so signals are handled at once; <&0 keeps the terminal as stdin
    timeout --foreground -k 3 "$secs" nice -n 10 "${cmd[@]}" <&0 &
    child=$!
    wait "$child"; rc=$?
    child=""
    cleanup

    # 0 = quit normally, 124 = ran its full time, 130/143 = interrupted; anything else is a failure
    case "$rc" in 0|124|130|143) ;; *) log "saver failed rc=$rc: ${cmd[*]}" ;; esac
    if (( SECONDS-start < 5 )); then fails=$((fails+1)); sleep 1; else fails=0; fi
    if (( fails >= ${#SAVERS[@]} )); then
      echo "fun: nothing seems to be running - check the packages are installed. See $LOG"
      exit 1
    fi
  done
done
