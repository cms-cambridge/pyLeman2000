#!/usr/bin/env bash
# Container entrypoint for the Octave Leman (2000) model.
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "Usage: $0 <input.wav> <output.json> <local_decay_csv> <global_decay_csv> <detail>" >&2
  exit 2
fi

IN_FILE=$1
OUT_FILE=$2
LOCAL_DECAY=$3
GLOBAL_DECAY=$4
DETAIL=$5

# Escape single quotes for Octave string literals.
escape_sq() {
  printf '%s' "$1" | sed "s/'/''/g"
}

IN_ESC=$(escape_sq "$IN_FILE")
OUT_ESC=$(escape_sq "$OUT_FILE")
LOCAL_ESC=$(escape_sq "$LOCAL_DECAY")
GLOBAL_ESC=$(escape_sq "$GLOBAL_DECAY")

octave --no-gui --quiet --eval \
  "addpath('/opt'); leman_2000('${IN_ESC}', '${OUT_ESC}', '${LOCAL_ESC}', '${GLOBAL_ESC}', ${DETAIL});"
