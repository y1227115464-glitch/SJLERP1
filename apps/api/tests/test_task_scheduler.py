from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models import Notification
from app.tasks.models import Task
from app.tasks.scheduler import tick
from conftest import login
from test_supply import fixtures, post, shipment

UTC = timezone.utc


def test_periodic_recovery_pause_and_notifications(system, monkeypatch):
    client = system['client']; headers = login(client)
    start = datetime(2026, 9, 11, 6, tzinfo=UTC)  # Friday 14:00 Shanghai
    monkeypatch.setattr('app.tasks.rules.now', lambda: start)
    rule = post(client, '/task-rules', headers, {'request_id': str(uuid4()), 'title': '下载数据', 'kind': 'daily', 'due_time': '15:00'})
    factory = system['app'].state.database.session
    tick(factory, start)
    assert client.get('/api/v1/tasks').json()['total'] == 8
    assert client.get('/api/v1/tasks/summary').status_code == 200
    tick(factory, start + timedelta(hours=2))
    tick(factory, start + timedelta(hours=2))
    with factory() as db:
        assert len(db.scalars(select(Notification).where(Notification.task_id.is_not(None))).all()) == 1
    later = start + timedelta(days=20)
    tick(factory, later)
    tasks = client.get('/api/v1/tasks?group=all&page_size=100').json()['items']
    assert len(tasks) == 28
    assert len({t['id'] for t in tasks}) == 28
    monkeypatch.setattr('app.tasks.rules.now', lambda: later)
    assert client.patch(f"/api/v1/task-rules/{rule['id']}", headers=headers, json={'version': rule['version'], 'enabled': False}).status_code == 200
    tick(factory, later + timedelta(days=30))
    assert client.get('/api/v1/tasks?group=all').json()['total'] == 28


def test_source_dates_overrides_and_partial_dispatch(system):
    client, headers, product, supplier, source, target = fixtures(system)
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['purchase_order', 'production', 'dispatch']})
    body = {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'], 'order_date': '2026-09-08',
            'planned_ship_date': '2026-09-18', 'lines': [{'product_id': product['id'], 'quantity': 100, 'unit_price': '1'}]}
    order = post(client, '/purchase-orders', headers, body)
    factory = system['app'].state.database.session
    tick(factory)
    def tasks(kind='purchase', identifier=order['id']):
        return client.get('/api/v1/tasks', params={'group': 'all', 'source_kind': kind, 'source_id': identifier}).json()['items']
    rows = {t['action_kind']: t for t in tasks()}
    assert len(rows) == 3
    assert rows['production']['due_date'] == '2026-09-16'
    prod = rows['production']
    edited = client.patch(f"/api/v1/tasks/{prod['id']}", headers=headers, json={'version': prod['version'], 'due_date': '2026-09-15'}).json()
    assert edited['follow_source'] is False
    post(client, f"/purchase-orders/{order['id']}/schedule", headers, {'request_id': str(uuid4()), 'planned_ship_date': '2026-09-25'}, 200)
    tick(factory)
    rows = {t['action_kind']: t for t in tasks()}
    assert rows['production']['due_date'] == '2026-09-15' and rows['production']['source_changed_at']
    assert rows['dispatch']['due_date'] == '2026-09-25'
    post(client, f"/purchase-orders/{order['id']}/confirm", headers, {}, 200)
    tick(factory)
    assert next(t for t in tasks() if t['action_kind'] == 'purchase_order')['status'] == 'completed'
    first = shipment(system, client, headers, product, target, 60, order=order)
    tick(factory)
    assert tasks('shipment', first['id'])[0]['due_date'] == '2026-09-25'
    post(client, f"/shipments/{first['id']}/dispatch", headers, {}, 200)
    tick(factory)
    assert tasks('shipment', first['id'])[0]['status'] == 'completed'
    assert next(t for t in tasks() if t['action_kind'] == 'dispatch')['status'] == 'pending'
    second = shipment(system, client, headers, product, target, 40, order=order)
    tick(factory)
    assert next(t for t in tasks() if t['action_kind'] == 'dispatch')['suppressed'] is True
    post(client, f"/shipments/{second['id']}/cancel", headers, {}, 200)
    tick(factory)
    assert next(t for t in tasks() if t['action_kind'] == 'dispatch')['suppressed'] is False
    assert tasks('shipment', second['id'])[0]['status'] == 'cancelled'
    third = shipment(system, client, headers, product, target, 40, order=order)
    post(client, f"/shipments/{third['id']}/dispatch", headers, {}, 200)
    tick(factory)
    assert next(t for t in tasks() if t['action_kind'] == 'dispatch')['status'] == 'completed'
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").json()['status'] == 'ordered'


def test_no_historical_backfill_and_manual_tasks_remain_independent(system):
    client, headers, product, supplier, source, target = fixtures(system)
    order = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
        'order_date': '2026-09-08', 'lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': '1'}]})
    installed = post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['production']})
    factory = system['app'].state.database.session
    tick(factory)
    assert client.get('/api/v1/tasks').json()['total'] == 0
    post(client, '/tasks/apply-rules', headers, {'request_id': str(uuid4()), 'source_kind': 'purchase', 'source_id': order['id'],
                                              'rule_ids': [installed['items'][0]['id']]}, 200)
    manual = post(client, '/tasks', headers, {'request_id': str(uuid4()), 'title': '私人复核', 'source_kind': 'purchase', 'source_id': order['id']})
    post(client, f"/purchase-orders/{order['id']}/production", headers, {'request_id': str(uuid4()), 'notes': '已向供应商核实数量'}, 200)
    tick(factory)
    rows = client.get('/api/v1/tasks?group=all').json()['items']
    assert next(t for t in rows if t['action_kind'] == 'production')['status'] == 'completed'
    assert next(t for t in rows if t['id'] == manual['id'])['status'] == 'pending'


def test_group_notification_reassignment_and_revocation(system):
    from app.models import User
    client = system['client']; headers = login(client)
    factory = system['app'].state.database.session
    items = [post(client, '/tasks', headers, {'request_id': str(uuid4()), 'title': title, 'due_date': '2026-09-01', 'due_time': '15:00'}) for title in ['事项甲', '事项乙']]
    tick(factory)
    notices = client.get('/api/v1/notifications').json()['items']
    assert len(notices) == 1
    anchor = next(task for task in items if task['id'] == notices[0]['task_id'])
    response = client.patch(f"/api/v1/tasks/{anchor['id']}", headers=headers, json={'version': anchor['version'], 'assignee_id': system['ids']['finance']})
    assert response.status_code == 200, response.text
    tick(factory)
    assert client.get('/api/v1/notifications').json()['total'] == 1  # Remaining task still keeps the grouped notice visible.
    login(client, 'finance')
    assert client.get('/api/v1/notifications').json()['total'] == 1
    task = post(client, '/tasks', login(client), {'request_id': str(uuid4()), 'title': '甲店专属事项', 'store_id': system['ids']['a'],
                 'assignee_id': system['ids']['operator'], 'due_date': '2026-09-01', 'due_time': '15:00'})
    tick(factory)
    login(client, 'operator')
    notice = client.get('/api/v1/notifications').json()['items'][0]
    with factory() as db:
        user = db.get(User, system['ids']['operator']); user.stores.clear(); db.commit()
    headers = login(client, 'operator')
    assert client.get('/api/v1/notifications').json()['total'] == 0
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert client.post(f"/api/v1/notifications/{notice['id']}/read", headers=headers).status_code == 404


def test_templates_link_to_reports_and_edits_preserve_single_occurrence(system, monkeypatch):
    client = system['client']; headers = login(client)
    start = datetime(2026, 9, 11, 6, tzinfo=UTC)
    monkeypatch.setattr('app.tasks.rules.now', lambda: start)
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['daily_data', 'weekly_analysis']})
    factory = system['app'].state.database.session; tick(factory, start)
    tasks = client.get('/api/v1/tasks?group=all&limit=200').json()['items']
    assert {t['source_kind'] for t in tasks} == {'imports', 'sales'}
    today = next(t for t in tasks if t['due_date'] == '2026-09-11' and t['action_kind'] == 'daily')
    assert client.post(f"/api/v1/tasks/{today['id']}/status", headers=headers, json={'request_id': str(uuid4()), 'version': today['version'], 'status': 'cancelled'}).status_code == 200
    tick(factory, start + timedelta(days=1))
    tasks = client.get('/api/v1/tasks?group=all&limit=200').json()['items']
    assert next(t for t in tasks if t['id'] == today['id'])['status'] == 'cancelled'
    assert any(t['due_date'] == '2026-09-12' and t['status'] == 'pending' for t in tasks)


def test_completed_tasks_and_manual_overrides_ignore_unrelated_source_updates(system):
    client, headers, product, supplier, source, target = fixtures(system)
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['production', 'dispatch']})
    order = post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
        'order_date': '2026-09-08', 'planned_ship_date': '2026-09-18', 'already_ordered': True, 'lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': '1'}]})
    assert order['status'] == 'ordered' and order['ordered_at']
    factory = system['app'].state.database.session; tick(factory)
    rows = client.get('/api/v1/tasks').json()['items']; prod = next(t for t in rows if t['action_kind'] == 'production')
    response = client.patch(f"/api/v1/tasks/{prod['id']}", headers=headers, json={'version': prod['version'], 'due_date': '2026-09-15'})
    assert response.status_code == 200
    # Applying a rule again must not mistake the intentionally different reminder date for a new source change.
    post(client, '/tasks/apply-rules', headers, {'request_id': str(uuid4()), 'source_kind': 'purchase', 'source_id': order['id'], 'rule_ids': [prod['rule_id']]}, 200)
    assert client.get(f"/api/v1/tasks/{prod['id']}").json()['source_changed_at'] is None
    post(client, f"/purchase-orders/{order['id']}/production", headers, {'request_id': str(uuid4()), 'notes': '已确认本批可以供货'}, 200)
    tick(factory)
    post(client, f"/purchase-orders/{order['id']}/schedule", headers, {'request_id': str(uuid4()), 'planned_ship_date': '2026-09-20'}, 200)
    tick(factory)
    saved = client.get(f"/api/v1/tasks/{prod['id']}").json()
    assert saved['status'] == 'completed' and saved['due_date'] == '2026-09-15'
    assert client.get(f"/api/v1/purchase-orders/{order['id']}").json()['production_history'][0]['notes'] == '已确认本批可以供货'


def test_invalid_dates_rejected_and_bad_event_does_not_block_other_reminders(system, monkeypatch):
    from app.tasks.models import SourceEvent
    client, headers, product, supplier, source, target = fixtures(system)
    for bad_date in ['0001-01-01', '9999-12-31']:
        response = client.post('/api/v1/purchase-orders', headers=headers, json={'request_id': str(uuid4()), 'store_id': system['ids']['a'],
            'supplier_id': supplier['id'], 'order_date': '2026-09-08', 'planned_ship_date': bad_date,
            'lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': '1'}]})
        assert response.status_code == 422
        assert client.post('/api/v1/tasks', headers=headers, json={'request_id': str(uuid4()), 'title': '不可支持的日期', 'due_date': bad_date}).status_code == 422
    post(client, '/purchase-orders', headers, {'request_id': str(uuid4()), 'store_id': system['ids']['a'], 'supplier_id': supplier['id'],
        'order_date': '2026-09-08', 'lines': [{'product_id': product['id'], 'quantity': 1, 'unit_price': '1'}]})
    post(client, '/task-rules/templates', headers, {'request_id': str(uuid4()), 'templates': ['daily_data']})
    factory = system['app'].state.database.session
    def broken(*args, **kwargs):
        raise ValueError('Simulated one-unit failure')
    with monkeypatch.context() as patch:
        patch.setattr('app.tasks.sources.apply_event', broken)
        tick(factory)
    assert client.get('/api/v1/tasks').json()['total'] > 0
    with factory() as db:
        events = db.scalars(select(SourceEvent)).all()
        assert all(event.attempts == 1 and event.retry_at and event.error_message == 'ValueError' for event in events)
    tick(factory, datetime.now(UTC) + timedelta(minutes=2))
    with factory() as db:
        assert all(event.processed_at and not event.error_message for event in db.scalars(select(SourceEvent)))
