set -u
umask 077
ROOT=$1; JOB=$2; META=$ROOT/meta/$JOB
. "$META/job.conf"
ident() { if [ -r "/proc/$1/stat" ]; then sed 's/^.*) //' "/proc/$1/stat" | cut -d ' ' -f 20; fi; }
if [ -r /proc/sys/kernel/random/boot_id ]; then cat /proc/sys/kernel/random/boot_id > "$META/boot"; fi
ident $$ > "$META/pidid"
echo $$ > "$META/pid.tmp" && mv -f "$META/pid.tmp" "$META/pid"
exec >> "$META/output.log" 2>&1 < /dev/null

finish() { printf '%s\n' "$1" > "$META/exit.tmp"; mv -f "$META/exit.tmp" "$META/exit"; exit "$1"; }
die() { printf '%s\n' "$2" > "$META/reason"; finish "$1"; }

KILLBIN=/usr/bin/kill
if [ ! -x "$KILLBIN" ]; then KILLBIN=/bin/kill; fi
FD=$ROOT/folders/$NAME-$(printf '%.8s' "$UID_")
SLOTDIR=$FD/slot$SLOT
CACHE=$ROOT/repos/$UID_.git

if [ -n "$BLOB" ]; then
  git -c transfer.fsckObjects=true -C "$CACHE" fetch -q --no-tags --force "$ROOT/in/$BLOB.bundle" "+refs/*:refs/carnivore/jobs/$JOB/in/*" \
    || die 125 "the bundle could not be fetched into the folder cache"
fi
if [ -e "$SLOTDIR/.git" ]; then
  { git -C "$SLOTDIR" checkout -q -f --detach "$COMMIT" && git -C "$SLOTDIR" reset -q --hard && git -C "$SLOTDIR" clean -fdq; } \
    || die 125 "the folder could not be cleaned and moved to the commit"
else
  git -C "$CACHE" worktree prune
  git -C "$CACHE" worktree add -q -f --detach "$SLOTDIR" "$COMMIT" || die 125 "the folder could not be made from the commit"
fi

JP=$(cat "$META/path")
U=$(id -un)
SH=${SHELL:-/bin/sh}
if [ ! -x "$SH" ]; then SH=/bin/sh; fi
echo running > "$META/phase"
cd "$SLOTDIR" || die 125 "the folder cannot be entered"
setsid env -i HOME="$HOME" USER="$U" LOGNAME="$U" SHELL="$SH" TMPDIR="${TMPDIR:-/tmp}" LANG=C.UTF-8 PATH="$JP" \
  CARNIVORE_JOB_ID="$JOB" CARNIVORE_JOB_DIR="$SLOTDIR" GIT_CONFIG_COUNT=6 \
  GIT_CONFIG_KEY_0=url.carnivore-no-push://.pushInsteadOf GIT_CONFIG_VALUE_0=https:// \
  GIT_CONFIG_KEY_1=url.carnivore-no-push://.pushInsteadOf GIT_CONFIG_VALUE_1=git@ \
  GIT_CONFIG_KEY_2=url.carnivore-no-push://.pushInsteadOf GIT_CONFIG_VALUE_2=ssh:// \
  GIT_CONFIG_KEY_3=url.carnivore-no-push://.pushInsteadOf GIT_CONFIG_VALUE_3=http:// \
  GIT_CONFIG_KEY_4=url.carnivore-no-push://.pushInsteadOf GIT_CONFIG_VALUE_4=git:// \
  GIT_CONFIG_KEY_5=url.carnivore-no-push://.pushInsteadOf GIT_CONFIG_VALUE_5=file:// \
  /bin/sh -c '. "$1" || exit 125; if [ -s "$2" ]; then /bin/sh "$2" || exit 126; fi; exec "$3" "$4"' \
  sh "$META/env.sh" "$META/steps.sh" "$SH" "$META/command.sh" >> "$META/output.log" 2>&1 < /dev/null &
CP=$!
ident "$CP" > "$META/cpidid"
echo "$CP" > "$META/cpid.tmp" && mv -f "$META/cpid.tmp" "$META/cpid"
setsid /bin/sh -c 'sleep "$1"; : > "$2"; "$3" -s TERM -- "-$4"; sleep 10; "$3" -s KILL -- "-$4"' \
  sh "$CAP" "$META/capped" "$KILLBIN" "$CP" < /dev/null > /dev/null 2>&1 &
WP=$!
wait "$CP"
RC=$?
"$KILLBIN" -s KILL -- "-$CP" 2> /dev/null || true
"$KILLBIN" -s TERM -- "-$WP" 2> /dev/null
if [ -e "$META/capped" ]; then RC=124; echo "the time cap was reached" > "$META/reason"; fi
echo finishing > "$META/phase"

if [ "$RC" -ne 126 ] && [ -s "$META/memo.in" ]; then cp "$META/memo.in" "$FD/slot$SLOT.memo"; fi
git add -A -- . ':(exclude,glob)**/node_modules/**' ':(exclude,glob)**/.venv/**' ':(exclude,glob)**/venv/**' ':(exclude,glob)**/__pycache__/**'
TREE=$(git write-tree) && BASE=$(git rev-parse "$COMMIT^{tree}")
if [ -n "$TREE" ] && [ "$TREE" != "$BASE" ]; then
  RES=$(GIT_AUTHOR_NAME=carnivore-job GIT_AUTHOR_EMAIL=job@carnivore.invalid GIT_COMMITTER_NAME=carnivore-job \
    GIT_COMMITTER_EMAIL=job@carnivore.invalid git commit-tree "$TREE" -p "$COMMIT" -m "job $JOB result")
  git update-ref "refs/carnivore/jobs/$JOB/result" "$RES"
  if git bundle create "$ROOT/out/$JOB.tmp" "refs/carnivore/jobs/$JOB/result" "^$COMMIT" && mv -f "$ROOT/out/$JOB.tmp" "$ROOT/out/$JOB.bundle"; then
    CH=$(git diff-tree -r --no-renames --name-only "$COMMIT" "$RES" | wc -l)
    printf 'commit %s\nchanged %s\n' "$RES" "$((CH))" > "$META/result"
  fi
fi
finish "$RC"
