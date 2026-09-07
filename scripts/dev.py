#!/usr/bin/env python3
"""Project-local development runner. Never installs or changes system services."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
RUNTIME = ROOT / '.runtime'
PYTHON = ROOT / '.venv/bin/python'
API = ROOT / 'apps/api'


def execute(args, *, cwd=ROOT, env=None, check=True):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=check)


def environment():
    from dotenv import dotenv_values
    if not (ROOT / '.env').exists():
        raise SystemExit('请先运行 .venv/bin/python scripts/dev.py init')
    return {**os.environ, **{k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}}


def executable(name, preferred):
    candidate = Path(preferred)
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(f'缺少 {name}。安装本地依赖或运行 bash scripts/build-local-services.sh。')


def pg(name):
    return executable(name, RUNTIME / 'pgsql/bin' / name)


def redis(name):
    return executable(name, RUNTIME / 'src/redis-8.2.9/src' / name)


def private_file(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(contents)


def initialize():
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    if (ROOT / '.env').exists():
        print('已有 .env，保持原配置。')
        return
    db_password = secrets.token_urlsafe(30)
    redis_password = secrets.token_urlsafe(30)
    values = {
        'SJL_ENVIRONMENT': 'local',
        'SJL_DATABASE_URL': f'postgresql+psycopg://sjlerp:{db_password}@127.0.0.1:15432/sjlerp',
        'SJL_REDIS_URL': f'redis://:{redis_password}@127.0.0.1:16379/0',
        'SJL_DB_PASSWORD': db_password,
        'SJL_REDIS_PASSWORD': redis_password,
        'SJL_STORAGE_PATH': str(LOCAL / 'storage'),
        'SJL_ALLOWED_ORIGINS': 'http://127.0.0.1:5173,http://localhost:5173',
        'SJL_COOKIE_SECURE': 'false',
        'SJL_QUEUE_NAME': 'sjlerp',
    }
    private_file(ROOT / '.env', ''.join(f'{key}={value}\n' for key, value in values.items()))
    print('已生成项目本地配置和随机数据库/队列密码。')


def require_managed_local(env):
    if env.get('SJL_ENVIRONMENT') != 'local':
        raise SystemExit('本地服务管理仅允许 SJL_ENVIRONMENT=local。')
    for key, port in [('SJL_DATABASE_URL', 15432), ('SJL_REDIS_URL', 16379)]:
        target = urlsplit(env[key])
        if target.hostname != '127.0.0.1' or target.port != port:
            raise SystemExit(f'{key} 不是本项目独立实例地址；使用已有服务时请跳过 infra-up / infra-down。')


def infra_up():
    from redis import Redis
    import psycopg
    env = environment()
    require_managed_local(env)
    for directory in ['logs', 'run', 'redis', 'storage']:
        (LOCAL / directory).mkdir(parents=True, exist_ok=True)
    data = LOCAL / 'postgres'
    if not (data / 'PG_VERSION').exists():
        password_file = LOCAL / 'run/initdb-password'
        if password_file.exists():
            password_file.unlink()
        private_file(password_file, env['SJL_DB_PASSWORD'] + '\n')
        try:
            execute([pg('initdb'), '-D', data, '-U', 'sjlerp', '--auth=scram-sha-256',
                     '--encoding=UTF8', '--locale=C', f'--pwfile={password_file}'])
        finally:
            password_file.unlink(missing_ok=True)
    running = subprocess.run([pg('pg_ctl'), '-D', str(data), 'status'], capture_output=True).returncode == 0
    if not running:
        execute([pg('pg_ctl'), '-D', data, '-l', LOCAL / 'logs/postgres.log',
                 '-o', f'-p 15432 -h 127.0.0.1 -k "{LOCAL / "run"}"', '-w', 'start'])
    database_env = {**env, 'PGPASSWORD': env['SJL_DB_PASSWORD']}
    with psycopg.connect(host='127.0.0.1', port=15432, user='sjlerp',
                         password=env['SJL_DB_PASSWORD'], dbname='postgres', autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'sjlerp'").fetchone():
            conn.execute('CREATE DATABASE sjlerp')
    client = Redis.from_url(env['SJL_REDIS_URL'], socket_connect_timeout=1)
    try:
        client.ping()
    except Exception:
        config = LOCAL / 'redis/redis.conf'
        if config.exists():
            config.unlink()
        private_file(config, '\n'.join([
            'bind 127.0.0.1', 'port 16379', 'protected-mode yes',
            f'requirepass {env["SJL_REDIS_PASSWORD"]}', 'daemonize yes',
            f'pidfile "{LOCAL / "run/redis.pid"}"', f'dir "{LOCAL / "redis"}"',
            f'logfile "{LOCAL / "logs/redis.log"}"', 'appendonly yes', '',
        ]))
        execute([redis('redis-server'), config], env=database_env)
        for _ in range(30):
            try:
                client.ping()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise SystemExit('Redis 未就绪，请检查 .local/logs/redis.log')
    print('本地 PostgreSQL :15432 与 Redis :16379 已就绪。')


def infra_down():
    from redis import Redis
    env = environment()
    require_managed_local(env)
    if (LOCAL / 'run/redis.pid').exists():
        Redis.from_url(env['SJL_REDIS_URL']).shutdown(save=True)
    if (LOCAL / 'postgres/PG_VERSION').exists():
        execute([pg('pg_ctl'), '-D', LOCAL / 'postgres', '-m', 'fast', '-w', 'stop'], check=False)


def migrate():
    execute([PYTHON, '-m', 'alembic', 'upgrade', 'head'], cwd=API, env=environment())


def create_admin(args):
    env = environment()
    command = [PYTHON, '-m', 'app.cli', 'create-admin', '--email', args.email, '--name', args.name]
    if args.generate:
        credentials = LOCAL / 'admin-credentials.txt'
        if credentials.exists():
            raise SystemExit('本地管理员凭据文件已存在。不会覆盖；如需新增账号，请省略 --generate 交互输入密码。')
        password = secrets.token_urlsafe(24)
        env['SJL_BOOTSTRAP_PASSWORD'] = password
        execute(command, cwd=API, env=env)
        private_file(credentials, f'书剑录 ERP 本地管理员\n账号：{args.email}\n密码：{password}\n入口：http://127.0.0.1:5173\n')
        print('已建立管理员，随机密码保存于 .local/admin-credentials.txt（仅当前用户可读）。')
    else:
        execute(command, cwd=API, env=env)


def run_apps(args):
    env = environment()
    if args.built and args.service in {'all', 'web'} and not (ROOT / 'apps/web/dist/index.html').is_file():
        raise SystemExit('缺少网站构建结果，请先运行 npm --prefix apps/web run build。')
    web_mode = 'preview' if args.built else 'dev'
    definitions = {
        'api': ([str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], API),
        'worker': ([str(PYTHON), '-m', 'app.worker'], API),
        'web': (['npm', 'run', web_mode, '--', '--port', '5173', '--strictPort'], ROOT / 'apps/web'),
    }
    selected = definitions if args.service == 'all' else {args.service: definitions[args.service]}
    logs = LOCAL / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    children = []
    handles = []
    def stop(_signum=None, _frame=None):
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for name, (command, cwd) in selected.items():
            stream = (logs / f'{name}.log').open('a')
            handles.append(stream)
            children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                             stderr=subprocess.STDOUT, start_new_session=True))
            print(f'{name} 已启动，日志：.local/logs/{name}.log', flush=True)
        print('Web http://127.0.0.1:5173 · API http://127.0.0.1:8000 · Ctrl+C 停止应用', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        failed = [child.returncode for child in children if child.returncode not in (None, 0, -15)]
        if failed:
            raise SystemExit('应用进程退出，请查看对应日志。')
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        for stream in handles:
            stream.close()


def main():
    parser = argparse.ArgumentParser(description='书剑录 ERP 本地开发管理')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ['init', 'infra-up', 'infra-down', 'migrate']:
        commands.add_parser(name)
    admin = commands.add_parser('create-admin')
    admin.add_argument('--email', default='admin@shujianlu.local')
    admin.add_argument('--name', default='书剑录管理员')
    admin.add_argument('--generate', action='store_true')
    run = commands.add_parser('run')
    run.add_argument('service', choices=['all', 'api', 'worker', 'web'], default='all', nargs='?')
    run.add_argument('--built', action='store_true', help='通过本地预览服务运行已构建的网站')
    args = parser.parse_args()
    actions = {'init': initialize, 'infra-up': infra_up, 'infra-down': infra_down, 'migrate': migrate}
    if args.command in actions:
        actions[args.command]()
    elif args.command == 'create-admin':
        create_admin(args)
    else:
        run_apps(args)


if __name__ == '__main__':
    main()
