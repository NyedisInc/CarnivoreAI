
from __future__ import annotations

SHIM_TEMPLATE = r"""#!/bin/sh
# Written by the Carnivore server. Do not edit. Refuses broad kills (issue #2974); use `kill <pid>` for a known process.
TOOL=@TOOL@
REAL_TOOL=@REAL_TOOL@
REAL_PGREP=@REAL_PGREP@
REAL_PS=@REAL_PS@

refuse() {
  echo "$TOOL refused by Carnivore: $1. Look up the pid and run: kill <pid>" >&2
  exit 2
}

# A signal option: -9, -TERM, -KILL (digits, or two or more characters with no lowercase letter).
is_signal() {
  case "${1#-}" in [0-9]*) return 0 ;; esac
  case "${1#-}" in
    ??*) case "${1#-}" in *[a-z]*) return 1 ;; *) return 0 ;; esac ;;
  esac
  return 1
}

# Pass 1: validate the argument shape. BSD $TOOL stops parsing options at the first pattern, so a later -u/-f/--newer
# is silently taken as ANOTHER PATTERN (the incident); a refusal here is the whole point.
pattern=""; npat=0; skip=0; endopts=0; mflag=0
for a in "$@"; do
  if [ "$skip" = 1 ]; then skip=0; continue; fi
  if [ "$endopts" = 1 ]; then npat=$((npat + 1)); pattern=$a; continue; fi
  case "$a" in
    --) endopts=1 ;;
    -?*)
      [ "$npat" -ge 1 ] && refuse "option '$a' comes after the pattern, where BSD $TOOL reads it as another pattern"
      case "$a" in
        -[FcjL]*) refuse "option '$a' is not supported behind the guard" ;;
        *) if is_signal "$a"; then :
           else case "$a" in
             -[uUGgPt]) skip=1 ;;
             -[uUGgPt]?*) ;;
             *) if [ "$TOOL" = pkill ]; then
                  case "$a" in *v*) refuse "option '$a' (invert match) would match everything else" ;; esac
                fi
                case "$a" in *m*) mflag=1 ;; esac ;;
           esac
           fi ;;
      esac ;;
    *) npat=$((npat + 1)); pattern=$a ;;
  esac
done
[ "$skip" = 1 ] && refuse "an option is missing its value"
[ "$npat" -eq 0 ] && refuse "no pattern given (a user or parent filter alone matches every process it owns)"
[ "$npat" -gt 1 ] && refuse "$npat patterns given; give exactly one (a stray option word counts as a pattern)"

# The pattern itself: too short, digits only, a bare shell or runtime, or anything that would match a protected name.
[ "${#pattern}" -lt @MIN_PATTERN_LEN@ ] && refuse "pattern '$pattern' is shorter than @MIN_PATTERN_LEN@ characters"
case "$pattern" in *[!0-9]*) ;; *) refuse "pattern '$pattern' is all digits" ;; esac
lower=$(printf '%s' "$pattern" | tr 'A-Z' 'a-z')
case "$lower" in
  node|python|python3|bash|zsh|sh|ruby|java) refuse "pattern '$pattern' alone is too broad" ;;
esac
for name in @PROTECTED_NAMES@; do
  if printf '%s' "$name" | grep -Eiq -- "$pattern" 2>/dev/null; then
    refuse "pattern '$pattern' would match '$name'"
  fi
done

# Pass 2: the same selection through pgrep, which only lists. Signals and kill-only flags are dropped; killall
# matches whole names unless -m, so the dry run adds -x for it.
dry_run() {
  n=$#; skip=0; end=0
  [ "$TOOL" = killall ] && [ "$mflag" = 0 ] && set -- -x "$@" && n=$((n + 1))
  while [ "$n" -gt 0 ]; do
    a=$1; shift; n=$((n - 1))
    if [ "$skip" = 1 ]; then skip=0; set -- "$@" "$a"; continue; fi
    if [ "$end" = 1 ]; then set -- "$@" "$a"; continue; fi
    if is_signal "$a"; then continue; fi
    case "$a" in
      --) end=1; set -- "$@" "$a" ;;
      -[uUGgPt]) skip=1; set -- "$@" "$a" ;;
      -[uUGgPt]?*) set -- "$@" "$a" ;;
      -?*) keep=$(printf '%s' "${a#-}" | tr -cd 'fxino'); [ -n "$keep" ] && set -- "$@" "-$keep" ;;
      *) set -- "$@" "$a" ;;
    esac
  done
  "$REAL_PGREP" "$@"
}

pids=$(dry_run "$@"); rc=$?
[ "$rc" -gt 1 ] && refuse "the dry run could not list matches (pgrep exit $rc)"
pids=$(printf '%s\n' "$pids" | grep -E '^[0-9]+$' | grep -vx "$$")
if [ -n "$pids" ]; then
  csv=$(printf '%s' "$pids" | tr '\n' ',' | sed 's/,$//')
  # Full command lines, so a claude run as "node .../claude" is still seen. The shim's own process (and its
  # command-substitution forks) carry the pattern in their argv, so lines naming this script are dropped.
  rows=$("$REAL_PS" -ww -o pid=,command= -p "$csv" 2>/dev/null | grep -vF -- "$0")
  count=$(printf '%s\n' "$rows" | grep -c '[0-9]')
  if [ "$count" -gt @MAX_MATCHES@ ]; then
    refuse "it would signal $count processes (more than @MAX_MATCHES@)"
  fi
  if printf '%s\n' "$rows" | grep -Eiq -- '@PROTECTED_PROCESS_REGEX@'; then
    refuse "it would signal a protected process (a claude session, tmux, or the Carnivore app or engine)"
  fi
fi
exec "$REAL_TOOL" "$@"
"""
