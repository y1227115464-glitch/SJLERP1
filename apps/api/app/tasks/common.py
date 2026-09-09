import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import and_, case, or_, select

from app.core.api import audit, fail, require_store, store_filter
from app.core.security import aware, has_permission, can_access_store
from app.models import User, new_id, now
from app.supply.common import insert_ignore
from app.supply.models import PurchaseOrder, Shipment
from app.tasks.dates import category, set_schedule
from app.tasks.models import Task, TaskHistory, TaskOperation

SOURCE_PERMISSIONS = {'purchase': 'purchases.view', 'shipment': 'shipments.view', 'imports': 'reports.view',
                      'sales': 'reports.view', 'inventory': 'inventory.view'}


def source_allowed(user, kind):
    return kind is None or has_permission(user, SOURCE_PERMISSIONS[kind])


def task_scope(statement, user, *, mine=False, store_id=None):
    access = (Task.assignee_id == user.id) | (Task.creator_id == user.id)
    if has_permission(user, 'tasks.assign'):
        access = access | Task.store_id.is_not(None)
    statement = statement.where(access)
    if user.role != 'admin':
        statement = statement.where(Task.store_id.is_(None) | store_filter(user, Task.store_id))
    allowed = [key for key in SOURCE_PERMISSIONS if source_allowed(user, key)]
    statement = statement.where(Task.source_kind.is_(None) | Task.source_kind.in_(allowed))
    if mine:
        statement = statement.where(Task.assignee_id == user.id)
    if store_id:
        statement = statement.where(Task.store_id == store_id)
    return statement


def task_record(db, identifier, user, lock=False):
    query = task_scope(select(Task).where(Task.id == identifier), user)
    if lock:
        query = query.with_for_update(of=Task).execution_options(populate_existing=True)
    item = db.scalar(query)
    if item is None:
        fail(404, 'not_found', '待办不存在或无权访问')
    return item


def source_record(db, kind, identifier, user):
    if not source_allowed(user, kind):
        fail(404, 'not_found', '关联业务不存在或无权访问')
    if kind not in {'purchase', 'shipment'}:
        return None
    model = PurchaseOrder if kind == 'purchase' else Shipment
    record = db.get(model, identifier)
    if record is None or not can_access_store(user, record.store_id):
        fail(404, 'not_found', '关联业务不存在或无权访问')
    return record


def assignee(db, identifier, user, store_id, source_kind, current=None):
    identifier = identifier or user.id
    if identifier != user.id and identifier != current and not has_permission(user, 'tasks.assign'):
        fail(403, 'permission_denied', '当前账号不能委派给其他人')
    target = user if identifier == user.id else db.get(User, identifier)
    if not target or not has_permission(target, 'tasks.manage') or not source_allowed(target, source_kind):
        fail(422, 'invalid_assignee', '负责人不存在、已停用或不能访问关联业务')
    if store_id and not can_access_store(target, store_id):
        fail(422, 'invalid_assignee', '负责人没有此店铺权限')
    return target


def claim(db, request_id, user, kind, body, result_id):
    fingerprint = hashlib.sha256(json.dumps({'actor': user.id, 'kind': kind, 'body': body}, sort_keys=True, default=str).encode()).hexdigest()
    inserted = insert_ignore(db, TaskOperation, [{'id': str(request_id), 'fingerprint': fingerprint,
                              'result_id': result_id, 'created_at': now()}], ['id'])
    op = db.get(TaskOperation, str(request_id))
    if op.fingerprint != fingerprint:
        fail(409, 'idempotency_conflict', '此请求编号已用于其他内容')
    return bool(inserted), op.result_id


def check_version(item, version):
    if item.version != version:
        fail(409, 'version_conflict', '待办或规则已更新，请刷新后再操作')


def history(db, item, action, user=None, data=None):
    db.add(TaskHistory(task_id=item.id, actor_id=user.id if user else None, action=action, data=data or {}))


def update_status(db, item, status, reason, moment, user=None):
    if item.status == status:
        return
    before = item.status
    item.status, item.completion_reason = status, reason
    item.completed_at = moment if status != 'pending' else None
    item.version += 1
    history(db, item, 'status', user, {'before': before, 'after': status, 'reason': reason})


def values(item, names):
    result = {}
    for name in names.split():
        value = getattr(item, name)
        if isinstance(value, datetime):
            value = aware(value)
        result[name] = value.isoformat() if hasattr(value, 'isoformat') else value
    return result


def task_out(item, moment=None):
    result = values(item, 'id creator_id assignee_id store_id title notes status source_kind source_id source_number action_kind rule_id occurrence_date due_date due_time timezone follow_source notify version completed_at completion_reason source_changed_at created_at updated_at')
    result.update(assignee_name=item.assignee.display_name, store_name=item.store.name if item.store else None,
                  category=category(item, moment or now()), suppressed=item.suppressed)
    return result


def group_condition(group, moment):
    deadline = case((Task.due_time.is_not(None), Task.due_at), else_=Task.day_end_at)
    pending = Task.status == 'pending'
    if group in {'completed', 'cancelled'}:
        return Task.status == group
    if group == 'overdue':
        return and_(pending, deadline <= moment)
    if group == 'today':
        return and_(pending, Task.day_start_at <= moment, Task.day_end_at > moment, deadline > moment)
    if group == 'future':
        return and_(pending, Task.day_start_at > moment)
    if group == 'unscheduled':
        return and_(pending, Task.due_date.is_(None))
    return pending


def task_row(rule, identity, moment, *, source=None, source_kind=None, day=None):
    item = Task(id=new_id(), identity_key=identity, creator_id=rule.owner_id, assignee_id=rule.owner_id,
                store_id=source.store_id if source else rule.store_id, title=rule.title,
                source_kind=source_kind, source_id=source.id if source else None,
                source_number=source.number if source else '', action_kind=rule.kind, rule_id=rule.id,
                occurrence_date=day if not source else None, notes='', status='pending',
                follow_source=bool(source and rule.kind in {'production', 'dispatch'}), offset_days=rule.offset_days,
                notify=rule.notify, version=1, schedule_version=1, notified_version=0, suppressed=False,
                created_at=moment, updated_at=moment, completed_at=None, completion_reason='', source_changed_at=None,
                source_ship_date=day - timedelta(days=rule.offset_days) if source and day and rule.kind in {'production', 'dispatch'} else None)
    set_schedule(item, day, rule.due_time, rule.timezone, changed=False)
    return {column.name: getattr(item, column.name) for column in Task.__table__.columns}


def insert_tasks(db, rows):
    if not rows:
        return []
    identifiers = insert_ignore(db, Task, rows, ['identity_key'])
    db.add_all([TaskHistory(task_id=identifier, action='created', data={'source': 'rule'}) for identifier in identifiers])
    return identifiers
