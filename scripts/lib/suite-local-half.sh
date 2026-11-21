#!/usr/bin/env bash

set -u
SHA="${1:?sha}"; LOG="${2:?log}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAIN="$(dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")"
GUI="$HOME/dev-worktrees/cloudecode/master-suite.gui"
[ -d "$GUI" ] || git -C "$REPO" worktree add -q --detach "$GUI" "$SHA" || exit 2
git -C "$GUI" checkout -q --force --detach "$SHA" && git -C "$GUI" clean -qfd || exit 2
[ -e "$GUI/venv" ] || ln -s "$MAIN/venv" "$GUI/venv"
cp "$GUI/config.example.json" "$GUI/config.json"
OUTF="$(mktemp)"
(
    for v in $(compgen -e | grep -E '^(CARNIVORE|CLOUDE|CLOUDECODE)_' | grep -v '^CLOUDE_HEAVY_RUN_'); do unset "$v"; done
    unset TMUX TMUX_PANE HOST PORT PYTEST_ADDOPTS
    cd "$GUI" && "$GUI/venv/bin/python3" -m pytest -q -p no:cacheprovider -m mac_gui_session -rs tests
) > "$OUTF" 2>&1
RC=$?
{ echo "--- local half (mac_gui_session) at $SHA, exit $RC"; tail -15 "$OUTF"; } | tee -a "$LOG"
SUMMARY="$(tail -1 "$OUTF")"
rm -f "$OUTF"
[ "$RC" -eq 0 ] && printf '%s' "$SUMMARY" | grep -q ' passed' && ! printf '%s' "$SUMMARY" | grep -q 'skipped' || exit 1
