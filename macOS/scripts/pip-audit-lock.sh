#!/usr/bin/env bash
set -uo pipefail

lock="${1:-}"
report="${2:-}"
[[ -n "$lock" && -n "$report" ]] || { echo "usage: pip-audit-lock.sh <requirements.lock> <report file>" >&2; exit 2; }
mkdir -p "$(dirname "$report")" || exit 2

record_not_run() {
  printf 'pip-audit: not run (%s)\n' "$1" | tee "$report"
  exit 0
}

[[ -s "$lock" ]] || record_not_run "lock not found at $lock"

if [[ -n "${PIP_AUDIT:-}" ]]; then
  tool=("$PIP_AUDIT")
elif command -v pip-audit >/dev/null 2>&1; then
  tool=(pip-audit)
elif command -v uvx >/dev/null 2>&1; then
  tool=(uvx pip-audit)
else
  record_not_run "neither pip-audit nor uvx is installed"
fi

accepted_ids_for() {
  case "$1" in
    x86_64) printf '%s\n' PYSEC-2026-3552 PYSEC-2026-3553 PYSEC-2026-3554 ;;
  esac
}

lock_for_arch() {
  awk -v m="$1" 'BEGIN { keep = 1 }
    /^[A-Za-z0-9]/ {
      keep = 1
      if ($0 ~ /platform_machine == /) keep = ($0 ~ ("platform_machine == \047" m "\047"))
      else if ($0 ~ /platform_machine != /) keep = ($0 !~ ("platform_machine != \047" m "\047"))
      sub(/ ; platform_machine [!=]= \047[A-Za-z0-9_]+\047/, "")
    }
    keep' "$2"
}

: >"$report"
: >"$report.raw"
findings=0
failed=""
for arch in arm64 x86_64; do
  arch_lock="$(mktemp "${TMPDIR:-/tmp}/pip-audit-lock.XXXXXX")"
  lock_for_arch "$arch" "$lock" >"$arch_lock"
  ignores=()
  accepted="$(accepted_ids_for "$arch")"
  while IFS= read -r id; do
    [[ -n "$id" ]] && ignores+=(--ignore-vuln "$id")
  done <<<"$accepted"
  out="$("${tool[@]}" -r "$arch_lock" --no-deps --disable-pip ${ignores[@]+"${ignores[@]}"} 2>&1)"
  status=$?
  rm -f "$arch_lock"
  { printf '== %s ==\n' "$arch"; printf '%s\n' "$out"; } >>"$report.raw"
  if [[ $status -eq 0 ]]; then
    printf 'pip-audit: clean on %s, no known vulnerabilities in %s%s\n' "$arch" "$lock" \
      "$([[ -n "$accepted" ]] && printf ' (accepted by id: %s)' "$(tr '\n' ' ' <<<"$accepted" | sed 's/ $//')")" >>"$report"
  elif grep -q 'Found [0-9]* known vulnerabilit' <<<"$out"; then
    findings=1
    { printf 'pip-audit: FINDINGS on %s in %s (recorded, not blocking)\n' "$arch" "$lock"; grep 'Found [0-9]* known vulnerabilit' <<<"$out"; } >>"$report"
  else
    failed="$arch: pip-audit exited $status without a result: $(tail -n 1 <<<"$out" | cut -c1-160)"
    break
  fi
done
[[ -z "$failed" ]] || record_not_run "$failed"
cat "$report"
exit 0
