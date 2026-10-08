#!/bin/sh
# Build Showdown and export the Champions snapshot. Runs inside
# node:22.23.3-alpine via `make snapshot`, with the Showdown checkout (fetched
# on the host by git at a pinned commit) mounted as the working directory.
# The host needs no Node install. Takes under a minute, mostly `npm ci`.
set -eu

COMMIT="${1:?usage: run.sh <showdown-commit-sha>}"

# esbuild (needed by `node build`) is a runtime dependency, so dev deps can be skipped.
npm ci --omit=dev --no-audit --no-fund --loglevel=error
node build >/dev/null

SHOWDOWN_DIR="$PWD" node /work/tools/showdown_export/export.js "$COMMIT" \
  > /work/data/snapshots/showdown_champions.json
echo "wrote data/snapshots/showdown_champions.json (showdown@$COMMIT)"
