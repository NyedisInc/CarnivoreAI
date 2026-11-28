#!/usr/bin/env bash
refuse_in_pack_job() {
    if [ -n "${CARNIVORE_JOB_ID:-}" ]; then
        printf '%s: refused inside Pack job %s: this step belongs to the computer that owns the checkout; run it there, outside a job.\n' \
            "${1:-landing script}" "$CARNIVORE_JOB_ID" >&2
        exit 64
    fi
    return 0
}
