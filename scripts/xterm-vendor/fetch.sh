#!/usr/bin/env bash

set -euo pipefail

XTERM_VERSION="5.3.0"
FIT_VERSION="0.8.0"
WEBGL_VERSION="0.16.0"
UNICODE11_VERSION="0.6.0"
SEARCH_VERSION="0.13.0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$SCRIPT_DIR/../../client/vendor/xterm"

ASSETS="\
xterm.css|https://cdn.jsdelivr.net/npm/xterm@${XTERM_VERSION}/css/xterm.css|832f3f2c603b43ad4351ff04970150cc7a873014276db126a6065c6dd81e4872
xterm.js|https://cdn.jsdelivr.net/npm/xterm@${XTERM_VERSION}/lib/xterm.js|f0aea0f75f48559013ae6643c2479dd737d26da42d5524e6d2b70915ae6523c7
xterm-addon-fit.js|https://cdn.jsdelivr.net/npm/xterm-addon-fit@${FIT_VERSION}/lib/xterm-addon-fit.js|10f3194c5f17c1786fb7d5db865c1ec8539b6736a318063fd38bdaaf7c46848f
xterm-addon-webgl.js|https://cdn.jsdelivr.net/npm/xterm-addon-webgl@${WEBGL_VERSION}/lib/xterm-addon-webgl.js|0c9c48c9391c4cee816eacf95699dbde97e8cc8f191e87f3a571e73d214c8df8
xterm-addon-unicode11.js|https://cdn.jsdelivr.net/npm/xterm-addon-unicode11@${UNICODE11_VERSION}/lib/xterm-addon-unicode11.js|ab10d83642883e5e17ea741cd5b6e5f8c0f6a06e3271f2f0c0e043be4fc5e738
xterm-addon-search.js|https://cdn.jsdelivr.net/npm/xterm-addon-search@${SEARCH_VERSION}/lib/xterm-addon-search.js|6a6db33f16b764552377a2c5ba4327c6dab6beaf25484533afd7dbecd0b03793
"

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        sha256sum "$1" | cut -d' ' -f1
    fi
}

mkdir -p "$OUT_DIR"

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/xterm-vendor.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

echo "fetching pinned xterm assets (staged in $STAGE, installed into $OUT_DIR only if all verify)"

count=0
while IFS='|' read -r file url expected_sha256; do
    [ -n "$file" ] || continue
    dest="$STAGE/$file"

    echo "  -> $file  ($url)"
    curl -sSfL -o "$dest" "$url"

    size=$(wc -c <"$dest" | tr -d ' ')
    if [ "$size" -eq 0 ]; then
        echo "FAIL: $file downloaded empty from $url" >&2
        exit 1
    fi

    actual_sha256=$(sha256_of "$dest")

    if [ "$actual_sha256" != "$expected_sha256" ]; then
        echo "FAIL: sha256 mismatch for $file" >&2
        echo "  expected: $expected_sha256" >&2
        echo "  actual:   $actual_sha256" >&2
        echo "  if this is a deliberate version bump, update ASSETS" >&2
        echo "  in this script and client/vendor/xterm/VERSION.md together" >&2
        exit 1
    fi

    echo "     ok  ($size bytes, sha256 $actual_sha256)"
    count=$((count + 1))
done <<EOF
$ASSETS
EOF

if [ "$count" -ne 6 ]; then
    echo "FAIL: verified $count assets, expected 6 - the asset list did not parse" >&2
    exit 1
fi

while IFS='|' read -r file _url _sha; do
    [ -n "$file" ] || continue
    mv -f "$STAGE/$file" "$OUT_DIR/$file"
done <<EOF
$ASSETS
EOF

echo "all six xterm assets verified against pinned sha256"
