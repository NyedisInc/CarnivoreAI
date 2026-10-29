#!/bin/bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/deploy-dmg.sh"
FAILED=0

check() {
  local desc="$1" got="$2" want="$3"
  if [ "$got" != "$want" ]; then
    echo "FAIL: $desc (got '$got', want '$want')"
    FAILED=1
  else
    echo "ok: $desc"
  fi
}

check_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if ! grep -qF "$needle" <<<"$haystack"; then
    echo "FAIL: $desc (missing '$needle')"
    FAILED=1
  else
    echo "ok: $desc"
  fi
}

out=$("$SCRIPT" 2>&1)
rc=$?
check "no version exits 2" "$rc" "2"
check_contains "no version prints usage" "$out" "usage: deploy-dmg.sh"

out=$("$SCRIPT" -h)
rc=$?
check "-h exits 0" "$rc" "0"
check_contains "-h prints usage" "$out" "usage: deploy-dmg.sh"

out=$("$SCRIPT" 1.0.0 --bogus 2>&1)
rc=$?
check "unknown flag exits 2" "$rc" "2"
check_contains "unknown flag names itself" "$out" "unknown flag: --bogus"

out=$("$SCRIPT" 1.0.0 2.0.0 2>&1)
rc=$?
check "extra positional exits 2" "$rc" "2"

out=$("$SCRIPT" 1.0.0 --releases-dir 2>&1)
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "FAIL: --releases-dir with no value should not exit 0"
  FAILED=1
else
  echo "ok: --releases-dir with no value exits non-zero"
fi

out=$("$SCRIPT" 1.11.3 --releases-dir /tmp/does-not-exist-anywhere --dry-run 2>&1)
rc=$?
check "dry-run exits 0" "$rc" "0"
check_contains "dry-run names the resolved dmg path" "$out" \
  "dmg=/tmp/does-not-exist-anywhere/Carnivore-1.11.3-arm64.dmg"
check_contains "dry-run states nothing was touched" "$out" \
  "nothing was read from or written to disk"

check_contains "dry-run describes the swap preflight" "$out" \
  "deploy/swap_dirs.py --check"
check_contains "dry-run describes the atomic swap" "$out" \
  "ONE atomic renamex_np(RENAME_SWAP)"
check_contains "dry-run describes the drive check" "$out" \
  "would then check the backup drive"
check_contains "dry-run names the drive-refused exit code" "$out" \
  "exits 5 naming v1.11.3"

out=$("$SCRIPT" 9.9.9 --dry-run 2>&1)
check_contains "dry-run defaults releases dir" "$out" \
  "dmg=/Volumes/Backup/releases/Carnivore-9.9.9-universal.dmg"

out=$(CLOUDE_DEPLOY_RELEASES_DIR=/tmp/env-releases "$SCRIPT" 1.2.3 --dry-run 2>&1)
check_contains "env var overrides releases dir" "$out" \
  "dmg=/tmp/env-releases/Carnivore-1.2.3-arm64.dmg"

out=$(CLOUDE_DEPLOY_RELEASES_DIR=/tmp/env-releases "$SCRIPT" 1.2.3 --releases-dir /tmp/flag-releases --dry-run 2>&1)
check_contains "flag outranks env var" "$out" \
  "dmg=/tmp/flag-releases/Carnivore-1.2.3-arm64.dmg"

out=$("$SCRIPT" 1.16.4 --releases-dir /tmp/r --dry-run 2>&1)
check_contains "1.16.4 looks for the universal DMG" "$out" "dmg=/tmp/r/Carnivore-1.16.4-universal.dmg"
out=$("$SCRIPT" 1.16.3 --releases-dir /tmp/r --dry-run 2>&1)
check_contains "1.16.3 keeps the arm64 DMG" "$out" "dmg=/tmp/r/Carnivore-1.16.3-arm64.dmg"

TRY=1.16.5-try.joe-staging.g0fc50d3
out=$("$SCRIPT" "$TRY" --arch arm64 --releases-dir /tmp/r --dry-run 2>&1)
check_contains "try build asks for its arm64 DMG and sha256" "$out" \
  "dmg=/tmp/r/Carnivore-$TRY-arm64.dmg (and /tmp/r/Carnivore-$TRY-arm64.dmg.sha256)"
out=$(BUILD_ARCH=arm64 "$SCRIPT" "$TRY" --releases-dir /tmp/r --dry-run 2>&1)
check_contains "try build takes BUILD_ARCH from the environment" "$out" "Carnivore-$TRY-arm64.dmg"
out=$("$SCRIPT" "$TRY" --releases-dir /tmp/r --dry-run 2>&1 || true)
check_contains "try build with no arch and no DMG on disk is refused" "$out" "0 DMGs for"
out=$("$SCRIPT" 1.16.5 --releases-dir /tmp/r --dry-run 2>&1)
check_contains "plain 1.16.5 asks for the universal DMG" "$out" \
  "dmg=/tmp/r/Carnivore-1.16.5-universal.dmg (and /tmp/r/Carnivore-1.16.5-universal.dmg.sha256)"

D=$(mktemp -d); touch "$D/Carnivore-$TRY-arm64.dmg" "$D/Carnivore-$TRY-arm64.dmg.sha256"
out=$(env -u BUILD_ARCH "$SCRIPT" "$TRY" --releases-dir "$D" --dry-run 2>&1)
check_contains "try build with one DMG on disk resolves its arch" "$out" \
  "dmg=$D/Carnivore-$TRY-arm64.dmg (and $D/Carnivore-$TRY-arm64.dmg.sha256)"
touch "$D/Carnivore-$TRY-x64.dmg"
out=$(env -u BUILD_ARCH "$SCRIPT" "$TRY" --releases-dir "$D" --dry-run 2>&1 || true)
check_contains "try build with two DMGs on disk is refused" "$out" "2 DMGs for"
rm -f "$D"/Carnivore-* && rmdir "$D"

if [ "$FAILED" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
else
  echo "SOME TESTS FAILED"
  exit 1
fi
