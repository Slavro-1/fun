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
LIB="${SELF%/*}"
if [[ -f "$LIB/extras.py" ]]; then
  SETTINGS="$LIB/fun_app/settings.py"
else
  LIB="${LIB%/*}/lib/fun"
  if [[ ! -f "$LIB/extras.py" ]]; then LIB=/usr/local/lib/fun; fi
  SETTINGS="$LIB/fun_settings.py"
fi
EXTRAS="$LIB/extras.py"
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

# Put the terminal back in a sane state (cursor, autowrap, alt screen, colours, echo).
reset_term() {
  # A clean renderer has finished its synchronized update. Recover partial
  # output from a failed child or a legacy external program.
  if [[ ${1:-1} != 0 ]]; then printf '\e[?2026l'; fi
  printf '\e[0m\e[?7h\e[?25h\e[?1049l'
  stty sane 2>/dev/null
}

load_active_scenes() {
  local names
  if ! names=$(python3 "$EXTRAS" --list) || [[ -z "$names" ]]; then
    echo "fun: cannot load scene inventory from $EXTRAS" >&2
    return 1
  fi
  mapfile -t active <<< "$names"
}

source "$LIB/fun_app/legacy_savers.sh" || exit 1

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
    trap 'reset_term "$?"' EXIT
    python3 "$EXTRAS" "$2" <&0 &
    scene_pid=$!
    trap 'kill -TERM "$scene_pid" 2>/dev/null; wait "$scene_pid"; exit 130' INT TERM HUP
    wait "$scene_pid"; rc=$?
    exit "$rc" ;;
  --test)
    secs="${2:-6}"; pass=0; bad=0; badlist=""
    trap 'reset_term; exit 130' INT TERM HUP
    load_active_scenes || exit 1
    for s in "${active[@]}"; do
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

load_active_scenes || exit 1
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
