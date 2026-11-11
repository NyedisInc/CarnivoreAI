#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:?out dir}"; MODE="${2:-dark}"; PORT="${NOTIFY_PORT:-5897}"
KINDS="${3:-yesno,choice,permission,file,link,image,video,finished,died,update,appupdate,swarm,crosstalk,signin,notice}"
UDID="${NOTIFY_UDID:-C4D8935C-D21D-4F98-B4B2-D9688509CF5C}"
mkdir -p "$OUT"; rm -f "$OUT"/want-* "$OUT"/pushed-*
xcrun simctl boot "$UDID" 2>/dev/null || true
xcrun simctl bootstatus "$UDID" -b >/dev/null
xcrun simctl ui "$UDID" appearance "$MODE"
(cd "$ROOT/ios" && xcodegen generate >/dev/null)
python3 "$ROOT/scripts/ios/notify_acceptance_computer.py" "$OUT" "$UDID" "$PORT" "$KINDS" & HELPER=$!
trap 'kill $HELPER 2>/dev/null || true' EXIT
cd "$ROOT/ios"
TEST_RUNNER_NOTIFY_SHOTS_DIR="$OUT" TEST_RUNNER_NOTIFY_KINDS="$KINDS" TEST_RUNNER_NOTIFY_ORIGIN="http://127.0.0.1:$PORT" \
  xcodebuild test -scheme CarnivoreAcceptance -destination "platform=iOS Simulator,id=$UDID" \
  CODE_SIGN_IDENTITY=- CODE_SIGNING_ALLOWED=YES CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= -only-testing:CarnivoreShotTests
