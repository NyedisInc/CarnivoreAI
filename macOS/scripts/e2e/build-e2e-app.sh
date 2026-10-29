#!/usr/bin/env bash
#
#
set -euo pipefail
set +x
mac_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$mac_dir"

while IFS= read -r name; do
  case "$name" in CSC_* | APPLE_* | *_SIGN_IDENTITY) unset "$name" ;; esac
done < <(compgen -e)
export CSC_IDENTITY_AUTO_DISCOVERY=false

npm run package -- --dir --universal -c.directories.output=dist-e2e \
  -c.electronFuses.runAsNode=true \
  -c.electronFuses.enableNodeOptionsEnvironmentVariable=true \
  -c.electronFuses.enableNodeCliInspectArguments=true \
  -c.electronFuses.enableEmbeddedAsarIntegrityValidation=false \
  -c.mac.notarize=false \
  -c.mac.extendInfo.CarnivoreBuildPurpose=e2e-test

app="$mac_dir/dist-e2e/mac-universal/Carnivore.app"
[[ -d "$app" ]] || { echo "build-e2e-app.sh: the build produced no app at $app" >&2; exit 1; }
purpose="$(/usr/libexec/PlistBuddy -c 'Print :CarnivoreBuildPurpose' "$app/Contents/Info.plist")"
[[ "$purpose" == "e2e-test" ]] || { echo "build-e2e-app.sh: the app is stamped '$purpose', not e2e-test" >&2; exit 1; }
echo "$app"
