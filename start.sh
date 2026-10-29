#!/bin/bash

#
# CARNIVORE_LOG_FILE

set -u

source venv/bin/activate

DEV_LOG_DIR="$HOME/Library/Logs/Carnivore/dev"
DEV_LOG_FILE="$DEV_LOG_DIR/server.log"

if [ -L "$HOME/Library/Logs/Carnivore" ] || [ -L "$DEV_LOG_DIR" ] || [ -L "$DEV_LOG_FILE" ]; then
    echo "refusing: a symlink in $DEV_LOG_DIR; starting without a dev log file" >&2
    exec python3 -m src.main
fi

DEV_LOG_MAX_BYTES=$((10 * 1024 * 1024))

mkdir -p "$DEV_LOG_DIR"
if [ -L "$HOME/Library/Logs/Carnivore" ] || [ -L "$DEV_LOG_DIR" ]; then
    echo "refusing: a symlink appeared in $DEV_LOG_DIR; starting without a dev log file" >&2
    exec python3 -m src.main
fi
chmod -h 700 "$HOME/Library/Logs/Carnivore" "$DEV_LOG_DIR"
if [ -f "$DEV_LOG_FILE" ] && [ "$(stat -f%z "$DEV_LOG_FILE")" -gt "$DEV_LOG_MAX_BYTES" ]; then
    mv -f "$DEV_LOG_FILE" "$DEV_LOG_FILE.1"
fi
(umask 077; : >>"$DEV_LOG_FILE")
export CARNIVORE_LOG_FILE="$DEV_LOG_FILE"

exec python3 -m src.main > >(tee -a "$DEV_LOG_FILE") 2>&1
