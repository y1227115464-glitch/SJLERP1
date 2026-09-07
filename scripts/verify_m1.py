#!/usr/bin/env python3
"""Verify migrations, HTTP boundaries and a real RQ worker against an isolated PostgreSQL database."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api'))


def main():
    from dotenv import dotenv_values
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from sqlalchemy import select, func

    from app.core.config import Settings
    from app.core.security import hash_password
    from app.main import create_app
    from app.models import User, Job, Notification

    original = {k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}
    pg_url = urlsplit(original['SJL_DATABASE_URL'])
    redis_url = urlsplit(original['SJL_REDIS_URL'])
    if pg_url.hostname != '127.0.0.1' or pg_url.port != 15432 or redis_url.hostname != '127.0.0.1' or redis_url.port != 16379:
        raise SystemExit('仅允许本项目独立本地数据库和队列进行此验收。')
    run_id = secrets.token_hex(6)
    database_name = f'sjlerp_verify_{run_id}'
    database_url = urlunsplit(pg_url._replace(path=f'/{database_name}'))
    queue_name = f'verify-{run_id}'
    redis_url_text = urlunsplit(redis_url._replace(path='/15'))
    env = {**os.environ, **original, 'SJL_ENVIRONMENT': 'test', 'SJL_DATABASE_URL': database_url,
           'SJL_QUEUE_NAME': queue_name, 'SJL_REDIS_URL': redis_url_text,
           'SJL_COOKIE_SECURE': 'false', 'SJL_LOGIN_LIMIT': '100'}
    control = psycopg.connect(host=pg_url.hostname, port=pg_url.port, user=pg_url.username,
                               password=pg_url.password, dbname='postgres', autocommit=True)
    control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)))
    worker = None
    app = None
    worker_log = None
    clients = []
    passed = []
    with tempfile.TemporaryDirectory(prefix='m1-', dir=ROOT / '.local') as storage:
        env['SJL_STORAGE_PATH'] = storage
        try:
            subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'apps/api',
                           env=env, check=True, capture_output=True)
            passed.append('PostgreSQL 从空库执行 Alembic 迁移')
            settings = Settings(_env_file=None, database_url=database_url, redis_url=redis_url_text,
                                storage_path=Path(storage), environment='test', cookie_secure=False,
                                queue_name=queue_name, login_limit=100)
            app = create_app(settings)
            admin_password = secrets.token_urlsafe(24)
            with app.state.database.session() as db:
                db.add(User(email='verify-admin@example.com', display_name='验收管理员', role='admin',
                            password_hash=hash_password(admin_password)))
                db.commit()
            base_headers = {'Origin': 'http://127.0.0.1:5173', 'X-Requested-With': 'SJLERP'}
            admin = TestClient(app, headers=base_headers)
            clients.append(admin)

            def expect(response, status):
                assert response.status_code == status, (response.status_code, response.text[:250])
                return response.json() if response.content else None

            def login(client, email, password):
                response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
                result = expect(response, 200)
                assert 'httponly' in response.headers.get('set-cookie', '').lower()
                client.headers['X-CSRF-Token'] = result['csrf_token']
                return result['user']

            expect(admin.get('/api/v1/auth/me'), 401)
            administrator = login(admin, 'verify-admin@example.com', admin_password)
            expect(admin.get('/health/ready'), 200)
            assert admin.cookies.get('sjlerp_session')
            passed.append('真实依赖健康检查、登录和会话读取')
            stores = []
            for number in (1, 2):
                stores.append(expect(admin.post('/api/v1/stores', json={
                    'name': f'验收店铺{number}', 'code': f'VERIFY-{number}', 'legal_entity': '验收主体',
                    'brand': '', 'marketplace': 'US', 'currency': 'USD',
                }), 201))
            operator_password = secrets.token_urlsafe(24)
            operator_record = expect(admin.post('/api/v1/users', json={
                'email': 'verify-operator@example.com', 'display_name': '验收运营', 'role': 'operator',
                'password': operator_password, 'store_ids': [stores[0]['id']],
            }), 201)
            operator = TestClient(app, headers=base_headers)
            clients.append(operator)
            operator_user = login(operator, 'verify-operator@example.com', operator_password)
            assert operator_user['store_ids'] == [stores[0]['id']]
            visible = expect(operator.get('/api/v1/stores'), 200)
            assert [row['id'] for row in visible['items']] == [stores[0]['id']]
            expect(operator.get(f'/api/v1/stores/{stores[1]["id"]}'), 404)
            export = operator.get('/api/v1/stores/export')
            if 'stores.export' in operator_user['permissions']:
                assert export.status_code == 200 and 'VERIFY-2' not in export.text
            else:
                expect(export, 403)
            expect(operator.get('/api/v1/users'), 403)
            expect(operator.get('/api/v1/audit-logs'), 403)
            assert expect(operator.get('/api/v1/workspace'), 200)['recent_activity'] == []
            passed.append('双店范围、列表/详情/导出/审计与账号管理权限')

            expect(admin.post('/api/v1/jobs', headers={'X-CSRF-Token': 'invalid'}, json={'kind': 'workspace_check'}), 403)
            expect(admin.post('/api/v1/jobs', headers={'Origin': 'https://untrusted.example'}, json={'kind': 'workspace_check'}), 403)
            expect(admin.patch(f'/api/v1/users/{administrator["id"]}', json={'is_active': False}), 409)
            passed.append('CSRF、来源校验和管理员防自锁')

            attachment = expect(admin.post('/api/v1/attachments', data={'store_id': stores[1]['id']},
                                           files={'file': ('../../scope.txt', b'isolated-store', 'text/plain')}), 201)
            expect(operator.get(f'/api/v1/attachments/{attachment["id"]}/download'), 404)
            assert admin.get(f'/api/v1/attachments/{attachment["id"]}/download').content == b'isolated-store'
            assert '..' not in attachment['filename']
            passed.append('附件保存、文件名处理及跨店下载拒绝')

            baseline_notifications = expect(operator.get('/api/v1/notifications'), 200)['total']
            job = expect(operator.post('/api/v1/jobs', json={'kind': 'workspace_check', 'store_id': stores[0]['id']}), 202)
            expect(admin.patch(f'/api/v1/users/{operator_record["id"]}', json={'is_active': False}), 200)
            expect(operator.get('/api/v1/auth/me'), 401)
            worker_log = (ROOT / '.local/logs/verification-worker.log').open('w')
            worker = subprocess.Popen([sys.executable, '-m', 'app.worker'], cwd=ROOT / 'apps/api', env=env,
                                      stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True)

            def await_job(job_id, status):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if worker.poll() is not None:
                        raise AssertionError('验收 worker 已退出，查看 verification-worker.log')
                    with app.state.database.session() as db:
                        saved = db.get(Job, job_id)
                        if saved.status == status:
                            return saved
                        if saved.status in {'failed', 'succeeded'}:
                            raise AssertionError(f'任务状态 {saved.status}，期望 {status}: {saved.error_message}')
                    time.sleep(0.2)
                raise AssertionError('真实后台任务未在30秒内完成')

            failed = await_job(job['id'], 'failed')
            assert failed.attempts == 1
            passed.append('账号停用使会话失效，已排队任务执行前重新检查权限')
            expect(admin.patch(f'/api/v1/users/{operator_record["id"]}', json={'is_active': True}), 200)
            login(operator, 'verify-operator@example.com', operator_password)
            expect(operator.post(f'/api/v1/jobs/{job["id"]}/retry'), 202)
            completed = await_job(job['id'], 'succeeded')
            assert completed.attempts == 2 and completed.result['store_count'] == 1
            expect(operator.post(f'/api/v1/jobs/{job["id"]}/retry'), 409)
            from app.jobs.service import execute_job
            execute_job(job['id'], settings)
            with app.state.database.session() as db:
                assert db.get(Job, job['id']).attempts == 2
                assert db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == operator_record['id'])) == baseline_notifications + 2
            notices = expect(operator.get('/api/v1/notifications'), 200)
            expect(operator.post(f'/api/v1/notifications/{notices["items"][0]["id"]}/read'), 200)
            assert expect(admin.get('/api/v1/notifications'), 200)['total'] == 0
            passed.append('真实 RQ worker 失败重试、完成去重、私有通知及已读')
            expect(operator.post('/api/v1/auth/logout'), 204)
            expect(operator.get('/api/v1/auth/me'), 401)
            passed.append('退出后会话失效')
            for label in passed:
                print(f'PASS {label}')
            print(f'PASS 共 {len(passed)} 组 PostgreSQL/Redis 集成验收；数据与主工作区隔离。')
        finally:
            if worker and worker.poll() is None:
                os.killpg(worker.pid, signal.SIGTERM)
                try:
                    worker.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGKILL)
                    worker.wait()
            if worker_log:
                worker_log.close()
            for client in clients:
                client.close()
            if app:
                app.state.database.engine.dispose()
            try:
                from rq import Queue
                from redis import Redis
                Queue(queue_name, connection=Redis.from_url(redis_url_text)).delete(delete_jobs=True)
            finally:
                control.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database_name)))
                control.close()


if __name__ == '__main__':
    main()
