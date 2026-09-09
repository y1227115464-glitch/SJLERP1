from uuid import uuid4

from conftest import login


def test_manual_task_versions_scope_and_no_business_side_effects(system):
    client = system['client']; headers = login(client, 'operator')
    body = {'request_id': str(uuid4()), 'title': '今日分析', 'store_id': system['ids']['a'],
            'due_date': '2026-09-11', 'due_time': None, 'timezone': 'Asia/Shanghai'}
    response = client.post('/api/v1/tasks', headers=headers, json=body)
    assert response.status_code == 201, response.text
    task = response.json()
    assert client.post('/api/v1/tasks', headers=headers, json=body).json()['id'] == task['id']
    assert client.post('/api/v1/tasks', headers=headers, json={**body, 'title': '不同请求内容'}).status_code == 409
    assert client.get('/api/v1/tasks').json()['total'] == 1
    done = client.post(f"/api/v1/tasks/{task['id']}/status", headers=headers,
                      json={'request_id': str(uuid4()), 'version': task['version'], 'status': 'completed'})
    assert done.status_code == 200, done.text
    assert done.json()['status'] == 'completed'
    assert client.patch(f"/api/v1/tasks/{task['id']}", headers=headers,
                        json={'version': task['version'], 'title': '陈旧覆盖'}).status_code == 409
    headers = login(client, 'finance')
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert client.get('/api/v1/tasks').json()['total'] == 0
    assert client.post('/api/v1/tasks', headers=headers, json={**body, 'request_id': str(uuid4())}).status_code == 404


def test_template_defaults_are_explicit_and_idempotent(system):
    client = system['client']; headers = login(client)
    assert client.get('/api/v1/task-rules').status_code == 200
    assert client.get('/api/v1/task-rules').json()['total'] == 0
    payload = {'request_id': str(uuid4()), 'templates': ['daily_data', 'weekly_analysis', 'purchase_order', 'production', 'dispatch']}
    first = client.post('/api/v1/task-rules/templates', headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert client.post('/api/v1/task-rules/templates', headers=headers, json=payload).status_code == 201
    rules = client.get('/api/v1/task-rules').json()['items']
    assert len(rules) == 5
    by_kind = {r['kind']: r for r in rules}
    assert by_kind['daily']['due_time'] == '15:00'
    assert by_kind['weekly']['weekdays'] == [4]
    assert by_kind['production']['offset_days'] == -2
