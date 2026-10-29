#!/bin/bash

RELEASE_DMG_ARCH_SINCE="1.16.4"
RELEASE_DMG_LEGACY_ARCH="arm64"
RELEASE_ARCH_JSON="${RELEASE_ARCH_JSON:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/macOS/release-arch.json}"

dmg_name() { printf 'Carnivore-%s-%s.dmg' "$1" "$2"; }

release_version_at_least() {
  local a b i
  IFS=. read -r -a a <<<"${1%%-*}"
  IFS=. read -r -a b <<<"${2%%-*}"
  for i in 0 1 2; do
    if (( 10#${a[i]:-0} > 10#${b[i]:-0} )); then return 0; fi
    if (( 10#${a[i]:-0} < 10#${b[i]:-0} )); then return 1; fi
  done
  return 0
}

release_dmg_arch() {
  local arch
  arch=$(sed -n 's/.*"dmg_arch"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$RELEASE_ARCH_JSON" 2>/dev/null | head -1)
  if [ -z "$arch" ]; then
    echo "release_dmg_name: no dmg_arch in $RELEASE_ARCH_JSON" >&2
    return 1
  fi
  printf '%s' "$arch"
}

built_dmg_arch() {
  local prefix="Carnivore-$1-" f arch found=()
  for f in "$2/$prefix"*.dmg; do
    [ -f "$f" ] || continue
    arch="${f##*/}"; arch="${arch#"$prefix"}"; arch="${arch%.dmg}"
    [[ "$arch" =~ ^[A-Za-z0-9_]+$ ]] && found+=("$arch")
  done
  if [ "${#found[@]}" -ne 1 ]; then
    echo "release_dmg_name: ${#found[@]} DMGs for '$1' in $2 (want exactly one, or pass --arch)" >&2
    return 2
  fi
  printf '%s' "${found[0]}"
}

release_dmg_name() {
  local v="${1#v}" arch="${2:-}"
  if ! [[ "$v" =~ ^[0-9]+(\.[0-9]+)*(-.*)?$ ]]; then
    echo "release_dmg_name: not a release version: '$1'" >&2
    return 2
  fi
  if [ -z "$arch" ] && [[ "$v" == *-* ]]; then
    arch="${BUILD_ARCH:-}"
    if [ -z "$arch" ] && [ -n "${3:-}" ]; then
      arch=$(built_dmg_arch "$v" "$3") || return 2
    fi
    if [ -z "$arch" ]; then
      echo "release_dmg_name: '$v' is a try or preview build; pass its built arch" >&2
      return 2
    fi
  fi
  if [ -z "$arch" ]; then
    if release_version_at_least "$v" "$RELEASE_DMG_ARCH_SINCE"; then
      arch=$(release_dmg_arch) || return 1
    else
      arch="$RELEASE_DMG_LEGACY_ARCH"
    fi
  fi
  dmg_name "$v" "$arch"
}
