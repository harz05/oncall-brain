#!/usr/bin/env bash
# Start/stop a local FalkorDB (redis-server + falkordb.so module) without Docker.
# Binary lookup order:
#   1. $FALKORDB_BIN/redis-server + falkordb.so  (glibc < 2.39 hosts; see `make falkordb-bin`)
#   2. the redis-server + falkordb.so bundled in the `falkordblite` wheel (glibc >= 2.39 hosts)
set -euo pipefail
PORT="${FALKORDB_PORT:-6379}"
DATA="${FALKORDB_DATA:-$PWD/.falkordb-data}"
mkdir -p "$DATA"

if [[ -n "${FALKORDB_BIN:-}" && -x "$FALKORDB_BIN/redis-server" && -f "$FALKORDB_BIN/falkordb.so" ]]; then
  BIN="$FALKORDB_BIN"
else
  BIN="$(python -c 'import redislite,os;print(os.path.join(os.path.dirname(redislite.__file__),"bin"))' 2>/dev/null || true)"
fi
[[ -n "$BIN" && -x "$BIN/redis-server" ]] || { echo "No FalkorDB binaries. Run 'make falkordb-bin' or 'pip install falkordblite'." >&2; exit 1; }

case "${1:-start}" in
  start)
    if "$BIN/redis-cli" -p "$PORT" ping >/dev/null 2>&1; then echo "FalkorDB already up on :$PORT"; exit 0; fi
    "$BIN/redis-server" --port "$PORT" --loadmodule "$BIN/falkordb.so" --dir "$DATA" \
      --daemonize yes --logfile "$DATA/falkordb.log"
    for _ in $(seq 20); do "$BIN/redis-cli" -p "$PORT" ping >/dev/null 2>&1 && { echo "FalkorDB up on :$PORT"; exit 0; }; sleep 0.25; done
    echo "FalkorDB failed to start, see $DATA/falkordb.log" >&2; exit 1 ;;
  stop) "$BIN/redis-cli" -p "$PORT" shutdown save 2>/dev/null || true; echo "FalkorDB stopped (data saved to $DATA)" ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
