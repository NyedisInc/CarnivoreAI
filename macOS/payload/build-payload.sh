#!/usr/bin/env bash
set -euo pipefail

readonly PBS_TAG="20261009"
readonly PY_VER="3.12.15"
readonly TMUX_TAG="v3.7c"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

pin() {
  case "$1" in
    arm64|aarch64-apple-darwin)  echo "aarch64-apple-darwin 233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f macos-arm64 0a763dd0380aa980d239509654da1bc7455843706a3c050f6709c8cd2e13d12d aarch64-apple-darwin -" ;;
    x86_64|x86_64-apple-darwin) echo "x86_64-apple-darwin fb3187d95334813b88940db0f1ca57b84cedfd552739c3a5771c3ea0e49988c9 macos-x86_64 1c21f9ade964e4a539be05ffe3a4e95854ab76a0a9c4c05d0ffbe7fc6c4d783f x86_64-apple-darwin x86_64" ;;
    *) echo "usage: build-payload.sh <arm64|x86_64|aarch64-apple-darwin|x86_64-apple-darwin> [output dir]" >&2; return 1 ;;
  esac
}

fetch() {
  local url="$1" dest="$2" want="$3"
  if [[ ! -f "$dest" ]]; then curl -fsSL --retry 3 -o "$dest.part" "$url"; mv "$dest.part" "$dest"; fi
  local got; got="$(shasum -a 256 "$dest" | cut -d' ' -f1)"
  [[ "$got" == "$want" ]] || { rm -f "$dest"; echo "sha256 mismatch for $dest: got $got, want $want" >&2; exit 1; }
}

pins_only=0; if [[ "${1:-}" == "--pins" ]]; then pins_only=1; shift; fi
target="${1:-}"; read -r triple pbs_sha tmux_asset tmux_sha uvplat runas < <(pin "$target") || exit 1
case "$triple" in aarch64-apple-darwin) arch=arm64 ;; *) arch=x86_64 ;; esac
pbs="cpython-$PY_VER+$PBS_TAG-$triple-install_only_stripped.tar.gz"
pbs_url="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/${pbs//+/%2B}"
tm="tmux-${TMUX_TAG#v}-$tmux_asset.tar.gz"
tm_url="https://github.com/tmux/tmux-builds/releases/download/$TMUX_TAG/$tm"
if [[ "$pins_only" == 1 ]]; then
  printf '{"arch":"%s","components":[{"name":"python","version":"%s","build":"%s","url":"%s","sha256":"%s"},{"name":"tmux","version":"%s","url":"%s","sha256":"%s"}]}\n' \
    "$arch" "$PY_VER" "$PBS_TAG" "$pbs_url" "$pbs_sha" "${TMUX_TAG#v}" "$tm_url" "$tmux_sha"
  exit 0
fi
cache="${CARNIVORE_PAYLOAD_CACHE:-$HOME/.cache/carnivore-payload}"
out="${2:-${CARNIVORE_PAYLOAD_OUT:-$cache/out}}"
dest="$out/payload-$arch"; mkdir -p "$cache" "$out"; rm -rf "$dest"; mkdir -p "$dest/bin"

fetch "$pbs_url" "$cache/$pbs" "$pbs_sha"
fetch "$tm_url" "$cache/$tm" "$tmux_sha"

tar -xzf "$cache/$pbs" -C "$dest"
tar -xzf "$cache/$tm" -C "$dest/bin" tmux
site="$dest/python/lib/python3.12/site-packages"

uv pip install --target "$site" --python-platform "$uvplat" --python-version 3.12 \
  --only-binary :all: --require-hashes --no-deps --link-mode copy -r "$here/runtime.lock"

run=(); [[ "$runas" != "-" ]] && run=(arch "-$runas")
find "$dest/python" -name __pycache__ -type d -prune -exec rm -rf {} +
${run[@]+"${run[@]}"} "$dest/python/bin/python3.12" -I -B -m compileall -q -j 0 --invalidation-mode unchecked-hash "$dest/python/lib/python3.12"

printf '{"arch":"%s","python":"%s","pbs":"%s","tmux":"%s"}\n' "$arch" "$PY_VER" "$PBS_TAG" "${TMUX_TAG#v}" > "$dest/PAYLOAD.json"
echo "built $dest ($(du -sh "$dest" | cut -f1))"
