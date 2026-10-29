#!/usr/bin/env bash
set -euo pipefail
set +x
readonly KEYCHAIN_DEFAULT="$HOME/Library/Keychains/carnivore-signing.keychain-db"
readonly KEYCHAIN_SECRET="carnivore/macos-signing-keychain"
readonly REGION="us-east-1"
readonly TEAM_ID="ARD6KN4BX4"
export AWS_PAGER=""
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
mac_dir="$(cd "$here/.." && pwd -P)"
ent="$here/entitlements.payload.plist"
session_open=0

die() { printf 'sign-payload.sh: %s\n' "$*" >&2; exit 1; }

cleanup() {
  local rc=$?
  trap '' INT TERM HUP QUIT
  if [[ "$session_open" == 1 ]] && ! kcs_close && [[ "$rc" == 0 ]]; then exit 1; fi
}

macho_list() {
  python3 -I - "$1" <<'PY'
import os, struct, sys
LE = {b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"}
BE = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf"}
FAT = {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
MH_EXECUTE = 2

def thin_kind(head):
    magic = head[:4]
    if magic in LE or magic in BE:
        return struct.unpack("<I" if magic in LE else ">I", head[12:16])[0]
    return None

def classify(fh):
    head = fh.read(16)
    kind = thin_kind(head)
    if kind is not None:
        return "E" if kind == MH_EXECUTE else "L"
    if head[:4] in FAT:
        wide = head[:4] == b"\xca\xfe\xba\xbf"
        n = struct.unpack(">I", head[4:8])[0]
        if not 0 < n <= 16:
            return None
        kinds = []
        for i in range(n):
            fh.seek(8 + i * (32 if wide else 20))
            ent = fh.read(32 if wide else 20)
            off = struct.unpack(">Q", ent[8:16])[0] if wide else struct.unpack(">I", ent[8:12])[0]
            fh.seek(off)
            k = thin_kind(fh.read(16))
            if k is None:
                return None
            kinds.append(k)
        return "E" if MH_EXECUTE in kinds else "L"
    return None

rows = []
for root, _, files in os.walk(sys.argv[1]):
    for f in files:
        p = os.path.join(root, f)
        if os.path.islink(p) or not os.path.isfile(p):
            continue
        with open(p, "rb") as fh:
            kind = classify(fh)
        if kind:
            rows.append((kind, p))
rows.sort(key=lambda r: (-r[1].count(os.sep), r[1]))
for kind, p in rows:
    print(kind, p)
PY
}

entitlement_keys() {
  local raw
  raw="$(codesign -d --entitlements - --xml "$1" 2>/dev/null)" || return 1
  printf '%s' "$raw" | python3 -I -c '
import plistlib, sys
raw = sys.stdin.buffer.read()
if raw.strip():
    for k in plistlib.loads(raw):
        print(k)'
}

check_entitlements() {
  local keys
  keys="$(entitlement_keys "$2")" || die "could not read the entitlements of $2"
  if [[ "$1" == "E" && -n "$keys" ]]; then die "executable carries entitlements: $2"; fi
  return 0
}

check_signature() {
  local f="$1" mode="$2" details
  codesign --verify --strict "$f" >/dev/null 2>&1 || die "payload file fails strict verification: $f"
  details="$(codesign -dvv "$f" 2>&1)" || die "could not read the signature of $f"
  grep -Eq 'flags=0x[0-9a-f]+\([^)]*runtime' <<<"$details" || die "hardened runtime is off: $f"
  if [[ "$mode" == "release" ]]; then
    codesign --verify --strict -R="anchor apple generic and certificate leaf[subject.OU] = \"$TEAM_ID\"" "$f" >/dev/null 2>&1 ||
      die "not signed by team $TEAM_ID with a Developer ID: $f"
    grep -q '^Timestamp=' <<<"$details" || die "no secure timestamp: $f"
  fi
  return 0
}

sign_tree() {
  local tree="$1" sha1="$2" keychain="$3" kind f n=0 args mode=release
  if [[ "$sha1" == "-" ]]; then mode=adhoc; fi
  while read -r kind f; do
    args=(--force --options runtime --sign "$sha1")
    if [[ "$sha1" == "-" ]]; then args+=(--timestamp=none); else args+=(--timestamp --keychain "$keychain"); fi
    if [[ "$kind" == "E" ]]; then args+=(--entitlements "$ent"); fi
    codesign "${args[@]}" "$f" >/dev/null 2>&1 || die "codesign failed for $f"
    printf 'signed %s\n' "$f"
    n=$((n + 1))
  done < <(macho_list "$tree")
  [[ "$n" -gt 0 ]] || die "no Mach-O files found under $tree (a tree that signs nothing is not a signed tree)"
  while read -r kind f; do
    check_signature "$f" "$mode"
    check_entitlements "$kind" "$f"
  done < <(macho_list "$tree")
  return 0
}

verify_app() {
  local app="$1" kind f n=0 payload="$1/Contents/Resources/payload"
  [[ -d "$payload" ]] || die "no payload folder in $app"
  while read -r kind f; do
    check_signature "$f" release
    check_entitlements "$kind" "$f"
    n=$((n + 1))
  done < <(macho_list "$payload")
  [[ "$n" -gt 0 ]] || die "no Mach-O files in $payload"
  codesign --verify --strict --verbose=2 "$app" || die "the app fails strict verification"
  spctl --assess --type execute --verbose=2 "$app" || die "spctl does not accept the app"
  printf 'verified %d payload Mach-O files, the app seal and spctl\n' "$n"
}

trees=(); identity=""; keychain=""
if [[ "${1:-}" == "--verify-app" ]]; then
  [[ -d "${2:-}" ]] || die "usage: sign-payload.sh --verify-app <App.app>"
  verify_app "$2"; exit 0
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --identity) identity="${2:?--identity needs a sha1 or -}"; shift 2 ;;
    --keychain) keychain="${2:?--keychain needs a path}"; shift 2 ;;
    -*) die "unknown option $1" ;;
    *) trees+=("$1"); shift ;;
  esac
done
[[ ${#trees[@]} -gt 0 ]] || die "usage: sign-payload.sh <tree dir>... [--identity <sha1>|- --keychain <path>]"
for t in "${trees[@]}"; do [[ -d "$t" ]] || die "no such payload directory: $t"; done
if [[ -z "$identity" ]]; then
  keychain="$KEYCHAIN_DEFAULT"
  [[ -f "$keychain" ]] || die "signing keychain missing: $keychain"
  # shellcheck source=../scripts/signing-keychain-session.sh
  source "$mac_dir/scripts/signing-keychain-session.sh"
  trap cleanup EXIT
  trap 'exit 130' INT TERM HUP QUIT
  kcs_open "$keychain" "$KEYCHAIN_SECRET" "$REGION"; session_open=1
  identity="$(node "$mac_dir/scripts/signing-config.js" "$keychain")"
  [[ "$identity" =~ ^[0-9A-F]{40}$ ]] || die "no usable Nyedis identity in the signing keychain (got '$identity')"
elif [[ "$identity" != "-" ]]; then
  [[ "$identity" =~ ^[0-9A-Fa-f]{40}$ && -f "$keychain" ]] || die "--identity needs a 40-hex sha1 and an existing --keychain"
fi
for t in "${trees[@]}"; do sign_tree "$t" "$identity" "$keychain"; done
