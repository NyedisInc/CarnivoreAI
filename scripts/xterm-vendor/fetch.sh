#!/usr/bin/env bash


set -euo pipefail

XTERM_VERSION="5.5.0"
FIT_VERSION="0.10.0"
WEBGL_VERSION="0.18.0"
UNICODE11_VERSION="0.8.0"
SEARCH_VERSION="0.15.0"
WEB_LINKS_VERSION="0.11.0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$SCRIPT_DIR/../../client/vendor/xterm"

ASSETS="\
xterm.css|https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM_VERSION}/css/xterm.css|ba8e6985669488981ccf40c0cefe3aba80722cb6c92de7ad628b0bd717faf2b6
xterm.js|https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM_VERSION}/lib/xterm.js|1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495
xterm-addon-fit.js|https://cdn.jsdelivr.net/npm/@xterm/addon-fit@${FIT_VERSION}/lib/addon-fit.js|bdaefa370b1bfc42ee88d46fe6072400902a4d4b2d45cd93438dda9b23c97089
xterm-addon-webgl.js|https://cdn.jsdelivr.net/npm/@xterm/addon-webgl@${WEBGL_VERSION}/lib/addon-webgl.js|9ffa9ac3ff6d47d4e6216ed1972ca8e0b5336cef744f50ebdc3f67b0ed727cdb
xterm-addon-unicode11.js|https://cdn.jsdelivr.net/npm/@xterm/addon-unicode11@${UNICODE11_VERSION}/lib/addon-unicode11.js|b0c3be540a9984713aea996966c24ed1a639d11f60d44986b22661e3a8a148d0
xterm-addon-search.js|https://cdn.jsdelivr.net/npm/@xterm/addon-search@${SEARCH_VERSION}/lib/addon-search.js|3cf52d71d9deb4ba60125087434c53e3fb35bb2249db9b13987991fd2db1c7bd
xterm-addon-web-links.js|https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@${WEB_LINKS_VERSION}/lib/addon-web-links.js|f230a6c8211ce4614dda5441f27b603c7c1ca95151a655bc0efac6377ee643f0
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

if [ "$count" -ne 7 ]; then
    echo "FAIL: verified $count assets, expected 7 - the asset list did not parse" >&2
    exit 1
fi

while IFS='|' read -r file _url _sha; do
    [ -n "$file" ] || continue
    mv -f "$STAGE/$file" "$OUT_DIR/$file"
done <<EOF
$ASSETS
EOF

echo "all seven xterm assets verified against pinned sha256"
