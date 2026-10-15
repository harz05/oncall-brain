#!/usr/bin/env bash
# Fetch FalkorDB's prebuilt module (rhel8 build: needs only glibc >= 2.28) and build redis-server
# from source into $FALKORDB_BIN. For hosts where the falkordblite wheel (glibc >= 2.39) won't install.
set -euo pipefail
: "${FALKORDB_BIN:?set FALKORDB_BIN (source devenv/env.sh)}"
VERSION="${FALKORDB_VERSION:-v4.22.0}"
WORK="${TMPDIR:-/tmp}/falkordb-build"
mkdir -p "$FALKORDB_BIN" "$WORK"

if [[ ! -f "$FALKORDB_BIN/falkordb.so" ]]; then
  curl -fsSL -o "$FALKORDB_BIN/falkordb.so" \
    "https://github.com/FalkorDB/FalkorDB/releases/download/$VERSION/falkordb-rhel8-x64.so"
fi
if [[ ! -x "$FALKORDB_BIN/redis-server" ]]; then
  curl -fsSL -o "$WORK/redis.tgz" https://download.redis.io/redis-stable.tar.gz
  tar xzf "$WORK/redis.tgz" -C "$WORK"
  # Only the core server is needed; bundled optional modules may fail to build, that's fine.
  make -C "$WORK/redis-stable/src" -j"$(nproc)" redis-server redis-cli >/dev/null
  cp "$WORK/redis-stable/src/redis-server" "$WORK/redis-stable/src/redis-cli" "$FALKORDB_BIN/"
fi
"$FALKORDB_BIN/redis-server" --version
