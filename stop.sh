#!/bin/bash


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/scripts/resolve-port.sh"

echo "Stopping FastAPI server..."

PORT="$(resolve_port "${SCRIPT_DIR}")" || {
    echo "ERROR: could not determine port - see reason above. Fix PORT= in .env and re-run."
    exit 1
}

OWN=" $(port_own_listener_pids "${PORT}" "${SCRIPT_DIR}" | tr '\n' ' ') "
for PID in $(port_listener_pids "${PORT}"); do
    case "${OWN}" in
        *" ${PID} "*) ;;
        *) echo "left alone: PID ${PID} listens on port ${PORT} but is not this checkout's engine" ;;
    esac
done

PIDS=$(port_own_listener_pids "${PORT}" "${SCRIPT_DIR}")

if [ -z "$PIDS" ]; then
    echo "No processes of this checkout found on port ${PORT}"
    exit 0
fi

echo "Found processes: $PIDS"

for PID in $PIDS; do
    echo "Killing process $PID..."
    kill $PID 2>/dev/null
done

sleep 2

REMAINING=$(port_own_listener_pids "${PORT}" "${SCRIPT_DIR}")
if [ ! -z "$REMAINING" ]; then
    echo "Force killing remaining processes: $REMAINING"
    for PID in $REMAINING; do
        kill -9 $PID 2>/dev/null
    done
fi

if [ -n "$(port_own_listener_pids "${PORT}" "${SCRIPT_DIR}")" ]; then
    echo "ERROR: Port ${PORT} is still in use"
    exit 1
else
    echo "This checkout's engine on port ${PORT} is stopped"
fi
