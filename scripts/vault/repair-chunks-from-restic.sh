#!/bin/bash
set -u

DRY=0; VAULT=""; BLOBS=""; HEALTH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --vault) VAULT="${2:-}"; shift ;;
    --blobs) BLOBS="${2:-}"; shift ;;
    --from-health) HEALTH="${2:-}"; shift ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { echo "error: $*" >&2; exit 2; }
for tool in restic op python3 shasum; do command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed or not on PATH"; done
[ -n "$VAULT" ] && [ -d "$VAULT/blobs" ] || die "--vault must be the vault folder (it has no blobs/ folder: $VAULT)"
[ -n "${RESTIC_REPO_REF:-}" ] && [ -n "${RESTIC_PASSWORD_REF:-}" ] || die "set RESTIC_REPO_REF and RESTIC_PASSWORD_REF to op:// references (this script stores no credentials)"

if [ -n "$HEALTH" ]; then
  [ -f "$HEALTH/vault-health.json" ] || die "no $HEALTH/vault-health.json"
  BLOBS="$(python3 -I - "$HEALTH/vault-health.json" <<'PY'
import json, sys
alerts = (json.load(open(sys.argv[1])).get("offload_alerts") or {})
names = sorted({b for part in alerts.values() if isinstance(part, dict) for b in part.get("blobs") or []})
print(",".join(names))
PY
)" || die "could not read the health record"
fi
[ -n "$BLOBS" ] || { echo "no chunk names to repair"; exit 0; }

RESTIC_REPOSITORY="$(op read "$RESTIC_REPO_REF")" || die "op could not read RESTIC_REPO_REF"
RESTIC_PASSWORD="$(op read "$RESTIC_PASSWORD_REF")" || die "op could not read RESTIC_PASSWORD_REF"
export RESTIC_REPOSITORY RESTIC_PASSWORD

WORK="$(mktemp -d "${TMPDIR:-/tmp}/repair-chunks.XXXXXX")" || die "no temp folder"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FAILED=0; FIXED=0; FINE=0

on_disk() { find "$VAULT/blobs/${1:0:2}" -maxdepth 1 -type f -name "$1.*" 2>/dev/null | head -n 1; }

proves() {
  local name="$1" file="$2" sum
  case "$file" in
    *.xz)  sum="$(python3 -I -c 'import lzma,sys,hashlib; print(hashlib.sha256(lzma.decompress(open(sys.argv[1],"rb").read())).hexdigest())' "$file" 2>/dev/null)" ;;
    *.zst) command -v zstd >/dev/null 2>&1 || return 2; sum="$(zstd -dc "$file" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)" ;;
    *) return 1 ;;
  esac
  [ "$sum" = "$name" ]
}

IFS=',' read -r -a NAMES <<< "$BLOBS"
for name in "${NAMES[@]}"; do
  name="$(echo "$name" | tr -d '[:space:]')"
  case "$name" in *[!0-9a-f]*|"") echo "skip (not a chunk name): $name"; FAILED=1; continue ;; esac
  [ "${#name}" -eq 64 ] || { echo "skip (not 64 characters): $name"; FAILED=1; continue; }
  here="$(on_disk "$name")"
  if [ -n "$here" ]; then
    proves "$name" "$here"; rc=$?
    if [ "$rc" -eq 0 ]; then echo "ok (already good): $name"; FINE=$((FINE+1)); continue; fi
    if [ "$rc" -eq 2 ]; then echo "cannot check $name (install zstd): the copy on disk is left alone"; FAILED=1; continue; fi
  fi
  found="$(restic find --json "$name.*" 2>/dev/null | python3 -I -c '
import json, sys
hits = []
for group in json.load(sys.stdin):
    for match in group.get("matches", []):
        hits.append((group.get("snapshot", ""), match.get("path", "")))
print("\n".join(f"{s} {p}" for s, p in hits[-1:]))
' 2>/dev/null)"
  if [ -z "$found" ]; then echo "NOT IN RESTIC: $name"; FAILED=1; continue; fi
  snap="${found%% *}"; path="${found#* }"
  echo "found $name in snapshot ${snap:0:8} at $path"
  [ "$DRY" -eq 1 ] && continue
  mkdir -p "$WORK/restore-$name"
  restic restore "$snap" --target "$WORK/restore-$name" --include "$path" >/dev/null 2>&1 || { echo "restic restore failed: $name"; FAILED=1; continue; }
  got="$(find "$WORK/restore-$name" -type f -name "$name.*" | head -n 1)"
  [ -n "$got" ] || { echo "restic restored nothing for: $name"; FAILED=1; continue; }
  proves "$name" "$got"; rc=$?
  if [ "$rc" -eq 2 ]; then echo "cannot check restic's copy of $name (install zstd): not used"; FAILED=1; continue; fi
  if [ "$rc" -ne 0 ]; then echo "restic's copy does not prove itself, not used: $name"; FAILED=1; continue; fi
  dest_dir="$VAULT/blobs/${name:0:2}"; dest="$dest_dir/$(basename "$got")"; part="$dest_dir/.$(basename "$got").repair-part"
  mkdir -p "$dest_dir"
  cp "$got" "$part" || { echo "copy failed: $name"; FAILED=1; continue; }
  if [ -n "$here" ]; then mkdir -p "$VAULT/blobs-quarantine/$STAMP"; mv "$here" "$VAULT/blobs-quarantine/$STAMP/" || { mv "$part" "$WORK/"; echo "could not set the damaged copy aside: $name"; FAILED=1; continue; }; fi
  if mv "$part" "$dest"; then echo "repaired: $name"; FIXED=$((FIXED+1)); else echo "could not put the copy in place: $name"; FAILED=1; fi
done

TRASH="${REPAIR_TRASH_DIR:-/Volumes/Backup/.Trashes/$(id -u)}"
if [ -d "$TRASH" ] && mv "$WORK" "$TRASH/repair-chunks.$STAMP" 2>/dev/null; then echo "temp folder moved to $TRASH/repair-chunks.$STAMP"
else echo "note: temp folder left at $WORK"; fi
echo "done: $FIXED repaired, $FINE already good, failed=$FAILED (dry run: $DRY)"
[ "$FAILED" -eq 0 ]
