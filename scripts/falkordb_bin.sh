#!/usr/bin/env bash
# Fetch FalkorDB's prebuilt module (rhel8 build: needs only glibc >= 2.28) and build redis-server
# from source into $FALKORDB_BIN. For hosts where the falkordblite wheel (glibc >= 2.39) won't install.
set -euo pipefail
: "${FALKORDB_BIN:?set FALKORDB_BIN (source devenv/env.sh)}"
# Pinned versions + sha256 (verified 2026-10-15 on Ubuntu 22.04).
FALKORDB_VERSION=v4.22.0
FALKORDB_SHA=c3ba3e0fdda567fbe436c985c46d8021d8582d41e514f63f4123e62758106100
REDIS_VERSION=8.10.2
REDIS_SHA=b9ffee226b5eecdba98a679260dad764b2a4ebd90dce4ad5ac9e9f3eef9c02b3
WORK="$(mktemp -d "${TMPDIR:-/tmp}/falkordb-build.XXXXXX")"  # private (mode 700): the checked file is the used file
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$FALKORDB_BIN"

if [[ ! -f "$FALKORDB_BIN/falkordb.so" ]]; then
  curl -fsSL -o "$WORK/falkordb.so" \
    "https://github.com/FalkorDB/FalkorDB/releases/download/$FALKORDB_VERSION/falkordb-rhel8-x64.so"
  echo "$FALKORDB_SHA  $WORK/falkordb.so" | sha256sum -c -
  cp "$WORK/falkordb.so" "$FALKORDB_BIN/falkordb.so"
fi
if [[ ! -x "$FALKORDB_BIN/redis-server" ]]; then
  curl -fsSL -o "$WORK/redis.tgz" "https://download.redis.io/releases/redis-$REDIS_VERSION.tar.gz"
  echo "$REDIS_SHA  $WORK/redis.tgz" | sha256sum -c -
  tar xzf "$WORK/redis.tgz" -C "$WORK"
  # Only the core server is needed; bundled optional modules may fail to build, that's fine.
  make -C "$WORK/redis-$REDIS_VERSION/src" -j"$(nproc)" redis-server redis-cli >/dev/null
  cp "$WORK/redis-$REDIS_VERSION/src/redis-server" "$WORK/redis-$REDIS_VERSION/src/redis-cli" "$FALKORDB_BIN/"
fi
"$FALKORDB_BIN/redis-server" --version
