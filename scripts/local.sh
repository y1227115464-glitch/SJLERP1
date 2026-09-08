#!/usr/bin/env bash
# Manage the built local website without keeping a terminal open.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TASK_ROOT"
export PATH="$TASK_ROOT/.local/bin:$PATH"
TASK_PID_FILE="$TASK_ROOT/.local/run/apps.pid"
TASK_PYTHON="$TASK_ROOT/.venv/bin/python"
TASK_RUNNER="$TASK_ROOT/scripts/dev.py"

running() {
  [ -f "$TASK_PID_FILE" ] || return 1
  TASK_PID="$(cat "$TASK_PID_FILE")"
  [[ "$TASK_PID" =~ ^[0-9]+$ ]] || return 1
  local command
  command="$(ps -p "$TASK_PID" -o command=)" || return 1
  [[ "$command" == *"$TASK_RUNNER run --built"* ]]
}

case "${1:-status}" in
  start)
    if running; then
      echo "应用已运行（PID ${TASK_PID}）。"
      exit 0
    fi
    if [ ! -f apps/web/dist/index.html ]; then
      npm --prefix apps/web run build
    fi
    "$TASK_PYTHON" "$TASK_RUNNER" infra-up
    "$TASK_PYTHON" "$TASK_RUNNER" migrate
    mkdir -p .local/logs .local/run
    TASK_PID="$("$TASK_PYTHON" - "$TASK_RUNNER" <<'PY'
import subprocess
import sys
with open('.local/logs/runner.log', 'a') as log:
    process = subprocess.Popen(
        [sys.executable, sys.argv[1], 'run', '--built'],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
print(process.pid)
PY
    )"
    echo "$TASK_PID" >"$TASK_PID_FILE"
    for ((attempt=0; attempt<30; attempt++)); do
      if ! kill -0 "$TASK_PID" 2>/dev/null; then
        echo '启动失败，请检查 .local/logs/ 中的日志。' >&2
        exit 1
      fi
      if curl --noproxy '*' --fail --silent --max-time 2 http://127.0.0.1:5173/health/ready >/dev/null; then
        echo "应用已在后台运行（PID ${TASK_PID}），本机入口 http://127.0.0.1:5173。"
        echo '局域网入口使用 .env 中 SJL_ALLOWED_ORIGINS 配置的本机 IP。'
        exit 0
      fi
      sleep 1
    done
    echo '服务尚未就绪，请检查 .local/logs/ 中的日志。' >&2
    exit 1
    ;;
  stop)
    if running; then
      kill -TERM "$TASK_PID"
      for ((attempt=0; attempt<15; attempt++)); do
        if ! running; then break; fi
        sleep 1
      done
      if running; then
        echo '应用尚未停止，请检查 .local/logs/ 中的日志。' >&2
        exit 1
      fi
    fi
    rm -f "$TASK_PID_FILE"
    "$TASK_PYTHON" "$TASK_RUNNER" infra-down
    echo '应用、项目数据库和队列已停止，数据保留。'
    ;;
  status)
    if running; then
      echo "应用运行中（PID ${TASK_PID}）。"
      curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:5173/health/ready
      echo
    else
      echo '后台应用未运行。'
      exit 1
    fi
    ;;
  *)
    echo '用法：bash scripts/local.sh {start|stop|status}' >&2
    exit 2
    ;;
esac
