from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Barrier, Event, current_thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import now
from app.supply.models import PurchaseOrder
from app.tasks.models import Task, SourceEvent
from app.tasks.scheduler import tick
from conftest import login
from test_supply import fixtures, post


def postgres(system):
    if system['app'].state.database.engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    return system['app'].state.database.session


def test_postgres_task_create_and_delivery_are_idempotent(system):
    factory = postgres(system); barrier = Barrier(2)
    body = {'request_id': str(uuid4()), 'title': '并发创建', 'due_date': '2026-09-01', 'due_time': '15:00'}
    def submit():
        with TestClient(system['app']) as client:
            headers = login(client); barrier.wait(timeout=10)
            response = client.post('/api/v1/tasks', headers=headers, json=body)
            assert response.status_code == 201, response.text
            return response.json()['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        identifiers = list(pool.map(lambda _: submit(), range(2)))
        list(pool.map(lambda _: tick(factory), range(2)))
    assert len(set(identifiers)) == 1
    login(system['client'])
    assert system['client'].get('/api/v1/notifications').json()['total'] == 1


def test_postgres_old_source_event_cannot_overwrite_new_date(system, monkeypatch):
    from app.tasks import sources
    factory = postgres(system)
    client, headers, product, supplier, source, target = fixtures(system)
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['dispatch']})
    order = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
        'order_date': '2026-09-08', 'planned_ship_date': '2026-09-18', 'lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': '1'}]})
    tick(factory)
    def change(day):
        post(client, f"/purchase-orders/{order['id']}/schedule", headers, {'request_id': str(uuid4()), 'planned_ship_date': day}, 200)
    change('2026-09-19')
    stale_read, resume = Event(), Event(); original = sources.lock_source
    def delayed(db, kind, identifier):
        if current_thread().name.startswith('stale'):
            cached = db.get(PurchaseOrder, identifier)
            assert cached.planned_ship_date == date(2026, 9, 19)
            stale_read.set(); assert resume.wait(10)
        return original(db, kind, identifier)
    monkeypatch.setattr(sources, 'lock_source', delayed)
    def process():
        with factory() as db, db.begin():
            assert sources.process_event(db, now())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='stale') as pool:
        future = pool.submit(process)
        try:
            assert stale_read.wait(10)
            change('2026-09-25'); process()
        finally:
            resume.set()
        future.result(timeout=10)
    with factory() as db:
        task = db.scalar(select(Task).where(Task.source_id == order['id']))
        assert task.due_date == date(2026, 9, 25)
        events = db.scalars(select(SourceEvent).where(SourceEvent.source_id == order['id'])).all()
        assert all(event.processed_at and not event.error_message for event in events)


def test_postgres_rule_edit_does_not_deadlock_periodic_generation(system, monkeypatch):
    from app.tasks import rules, scheduler
    factory = postgres(system); client = system['client']; headers = login(client)
    moment = datetime(2026, 9, 11, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(rules, 'now', lambda: moment)
    rule = post(client, '/task-rules', headers, {'request_id': str(uuid4()), 'title': '每日事项', 'kind': 'daily'})
    inserting, editing = Event(), Event(); original_insert, original_check = scheduler.insert_tasks, rules.check_version
    def paused_insert(db, rows):
        inserting.set(); assert editing.wait(10)
        return original_insert(db, rows)
    def checked(item, version):
        original_check(item, version); editing.set()
    monkeypatch.setattr(scheduler, 'insert_tasks', paused_insert); monkeypatch.setattr(rules, 'check_version', checked)
    def generate():
        with factory() as db, db.begin():
            return scheduler.periodic(db, moment)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(generate)
        assert inserting.wait(10)
        response = client.patch(f"/api/v1/task-rules/{rule['id']}", headers=headers, json={'version': rule['version'], 'title': '修改后的事项'})
        assert response.status_code == 200, response.text
        assert future.result(timeout=10)
