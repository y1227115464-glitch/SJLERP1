#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_RUNTIME="$TASK_ROOT/.runtime"
mkdir -p "$TASK_RUNTIME/downloads" "$TASK_RUNTIME/src" "$TASK_RUNTIME/logs"

download() {
  local url="$1" filename="$2" checksum="$3"
  if [ ! -f "$TASK_RUNTIME/downloads/$filename" ]; then
    curl --fail --location --connect-timeout 15 "$url" --output "$TASK_RUNTIME/downloads/$filename"
  fi
  python3 - "$TASK_RUNTIME/downloads/$filename" "$checksum" <<'PY'
import hashlib, pathlib, sys
actual = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
if actual != sys.argv[2]:
    raise SystemExit('下载文件校验失败，未执行解压或构建。')
PY
}

if [ ! -x "$TASK_RUNTIME/pgsql/bin/postgres" ]; then
  download 'https://ftp.postgresql.org/pub/source/v18.6/postgresql-18.6.tar.bz2' \
    'postgresql-18.6.tar.bz2' '555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f'
  tar -xjf "$TASK_RUNTIME/downloads/postgresql-18.6.tar.bz2" -C "$TASK_RUNTIME/src"
  (
    cd "$TASK_RUNTIME/src/postgresql-18.6"
    ./configure --prefix="$TASK_RUNTIME/pgsql" --without-icu --without-readline --without-zlib > "$TASK_RUNTIME/logs/postgres-configure.log" 2>&1
    make -j4 > "$TASK_RUNTIME/logs/postgres-build.log" 2>&1
    make install > "$TASK_RUNTIME/logs/postgres-install.log" 2>&1
  )
fi
if [ ! -x "$TASK_RUNTIME/src/redis-8.2.9/src/redis-server" ]; then
  download 'https://download.redis.io/releases/redis-8.2.9.tar.gz' \
    'redis-8.2.9.tar.gz' '531b314e5557ad76d941f605b3e3162ac61dc141f37c407e1f91fcfe17ea8c30'
  tar -xzf "$TASK_RUNTIME/downloads/redis-8.2.9.tar.gz" -C "$TASK_RUNTIME/src"
  make -C "$TASK_RUNTIME/src/redis-8.2.9" -j4 MALLOC=libc BUILD_TLS=no > "$TASK_RUNTIME/logs/redis-build.log" 2>&1
fi
"$TASK_RUNTIME/pgsql/bin/postgres" --version
"$TASK_RUNTIME/src/redis-8.2.9/src/redis-server" --version
