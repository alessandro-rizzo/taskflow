#!/usr/bin/env bash
# T0 evidence helper for TF-001.03. Throwaway, not part of any product build;
# lives outside prototype/bootstrap and is removable without impact.
#
# Times `taskflow list` invocations against prototype/bootstrap's self-hosted
# .taskflow "check" pipeline, in two modes:
#   cold: a fresh, empty TASKFLOW_DRIVER_CACHE per sample, forcing
#         projectdriver.Loader.Build to run `go build ./.taskflow` every time.
#   warm: one prewarming invocation populates a fixed cache dir, then N
#         samples reuse the cached driver binary (Build short-circuits).
#
# Usage: benchmark.sh <prototype-root> <taskflow-binary> <N> <out-dir>
set -euo pipefail

ROOT="$1"
BIN="$2"
N="${3:-15}"
OUT_DIR="$4"

mkdir -p "$OUT_DIR"
COLD_FILE="$OUT_DIR/cold-samples.txt"
WARM_FILE="$OUT_DIR/warm-samples.txt"
: > "$COLD_FILE"
: > "$WARM_FILE"

TIMEFORMAT='%R'

echo "cold: $N samples (fresh TASKFLOW_DRIVER_CACHE per sample; GOCACHE left warm)" >&2
for _ in $(seq 1 "$N"); do
  CACHE_DIR=$(mktemp -d)
  cd "$ROOT"
  SAMPLE=$( { time TASKFLOW_DRIVER_CACHE="$CACHE_DIR" "$BIN" list >/dev/null; } 2>&1 )
  echo "$SAMPLE" >> "$COLD_FILE"
  rm -rf "$CACHE_DIR"
done

echo "warm: prewarm + $N samples reusing one cached driver binary" >&2
WARM_CACHE=$(mktemp -d)
cd "$ROOT"
TASKFLOW_DRIVER_CACHE="$WARM_CACHE" "$BIN" list >/dev/null
for _ in $(seq 1 "$N"); do
  SAMPLE=$( { time TASKFLOW_DRIVER_CACHE="$WARM_CACHE" "$BIN" list >/dev/null; } 2>&1 )
  echo "$SAMPLE" >> "$WARM_FILE"
done
rm -rf "$WARM_CACHE"

echo "done: $COLD_FILE, $WARM_FILE" >&2
