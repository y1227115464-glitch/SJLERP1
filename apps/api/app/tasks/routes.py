from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.api import DB, Page, audit, fail, paginated, require, require_store
from app.core.security import has_permission
from app.models import User, new_id, now
from app.tasks.common import assignee, check_version, claim, group_condition, history, source_record, task_out, task_record, task_scope, update_status, values
from app.tasks.dates import set_schedule, source_date
from app.tasks.models import Task, TaskHistory, SourceEvent
from app.tasks.schemas import StatusInput, TaskCreate, TaskEdit

router = APIRouter(prefix='/api/v1/tasks')
Reader = Annotated[User, Depends(require('tasks.view'))]
Writer = Annotated[User, Depends(require('tasks.manage'))]


@router.get('')
def listing(db: DB, user: Reader, page: Page, group: Literal['pending', 'overdue', 'today', 'future', 'unscheduled', 'completed', 'cancelled', 'all'] = 'pending',
            store_id: str | None = None, mine: bool = True, q: str = '', source_kind: str | None = None, source_id: str | None = None):
    statement = task_scope(select(Task), user, mine=mine, store_id=store_id)
    if source_id:
        statement = statement.where(Task.source_kind == source_kind, Task.source_id == source_id)
    else:
        statement = statement.where(Task.suppressed.is_(False))
    moment = now()
    if group != 'all':
        statement = statement.where(group_condition(group, moment))
    if q.strip():
        statement = statement.where(Task.title.icontains(q.strip(), autoescape=True) | Task.source_number.icontains(q.strip(), autoescape=True))
    return paginated(db, statement.order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc(), Task.id), page, lambda item: task_out(item, moment))


@router.get('/summary')
def summary(db: DB, user: Reader, store_id: str | None = None, mine: bool = True):
    moment = now()
    base = task_scope(select(Task.id), user, mine=mine, store_id=store_id).where(Task.suppressed.is_(False))
    # One aggregate query, with exactly the same visibility predicates as the task list.
    from sqlalchemy import case
    columns = [func.sum(case((group_condition(group, moment), 1), else_=0)).label(group)
               for group in ['overdue', 'today', 'future', 'unscheduled']]
    row = db.execute(base.with_only_columns(*columns)).one()
    result = {key: int(value or 0) for key, value in row._mapping.items()}
    from app.supply.models import PurchaseOrder, Shipment
    from app.supply.common import scoped
    sources = []
    for kind, model, permission in [('purchase', PurchaseOrder, 'purchases.view'), ('shipment', Shipment, 'shipments.view')]:
        if has_permission(user, permission):
            identifiers = scoped(select(model.id), user, model.store_id, store_id)
            sources.append((SourceEvent.source_kind == kind) & SourceEvent.source_id.in_(identifiers))
    if sources:
        from sqlalchemy import or_
        pending, failed = db.execute(select(func.count(), func.sum(case((SourceEvent.error_message != '', 1), else_=0)))
            .where(SourceEvent.processed_at.is_(None), SourceEvent.actor_id == user.id, or_(*sources))).one()
        result.update(pending_sync=pending, failed_sync=int(failed or 0))
    return result


@router.get('/assignees')
def assignees(db: DB, user: Reader, store_id: str | None = None, q: str = ''):
    if store_id:
        require_store(db, user, store_id)
    if not has_permission(user, 'tasks.assign'):
        return {'items': [{'id': user.id, 'display_name': user.display_name}]}
    statement = select(User.id, User.display_name).where(User.is_active.is_(True))
    if store_id:
        statement = statement.where((User.role == 'admin') | User.stores.any(id=store_id))
    if q.strip():
        statement = statement.where(User.display_name.icontains(q.strip(), autoescape=True))
    return {'items': [dict(row._mapping) for row in db.execute(statement.order_by(User.display_name, User.id).limit(50))]}


@router.post('', status_code=201)
def create(payload: TaskCreate, db: DB, user: Writer):
    source = source_record(db, payload.source_kind, payload.source_id, user)
    store_id = source.store_id if source else payload.store_id
    if source and payload.store_id and payload.store_id != source.store_id:
        fail(422, 'source_scope_mismatch', '待办店铺与关联单据不一致')
    if store_id:
        require_store(db, user, store_id)
    target = assignee(db, payload.assignee_id, user, store_id, payload.source_kind)
    inserted, identifier = claim(db, payload.request_id, user, 'task.create', payload.model_dump(mode='json'), new_id())
    if not inserted:
        return task_out(task_record(db, identifier, user))
    item = Task(id=identifier, identity_key='manual:' + str(payload.request_id), creator_id=user.id,
                assignee_id=target.id, store_id=store_id, title=payload.title.strip(), notes=payload.notes,
                source_kind=payload.source_kind, source_id=payload.source_id, source_number=source.number if source else '',
                notify=payload.notify, version=1, schedule_version=1)
    if not item.title:
        fail(422, 'empty_title', '请填写待办标题')
    set_schedule(item, payload.due_date, payload.due_time, payload.timezone, changed=False)
    db.add(item); db.flush()
    history(db, item, 'created', user)
    audit(db, user, 'tasks.create', 'task', item.id, '创建待办', store_id)
    db.commit(); db.refresh(item)
    return task_out(item)


@router.get('/{identifier}')
def detail(identifier: str, db: DB, user: Reader):
    item = task_record(db, identifier, user)
    result = task_out(item)
    events = db.scalars(select(TaskHistory).where(TaskHistory.task_id == identifier)
                        .order_by(TaskHistory.created_at.desc(), TaskHistory.id).limit(100)).all()
    result['history'] = [values(event, 'id action data created_at') for event in events]
    return result


@router.patch('/{identifier}')
def edit(identifier: str, changes: dict, db: DB, user: Writer):
    item = task_record(db, identifier, user, lock=True)
    allowed = set(TaskEdit.model_fields)
    if not set(changes).issubset(allowed) or 'version' not in changes:
        fail(422, 'invalid_edit', '只能修改标题、负责人、时间、备注与提醒设置，请携带版本号')
    stored = {key: getattr(item, key) for key in TaskEdit.model_fields}
    if {'due_date', 'due_time', 'timezone'} & changes.keys() and 'follow_source' not in changes:
        stored['follow_source'] = False
    try:
        payload = TaskEdit.model_validate({**stored, **changes})
    except ValidationError:
        fail(422, 'invalid_edit', '请检查待办日期、标题与时区')
    check_version(item, payload.version)
    target = assignee(db, payload.assignee_id, user, item.store_id, item.source_kind, item.assignee_id)
    before = values(item, 'due_date due_time timezone assignee_id follow_source')
    day = payload.due_date
    if payload.follow_source:
        if item.action_kind not in {'production', 'dispatch'} or item.source_kind not in {'purchase', 'shipment'}:
            fail(422, 'no_source_date', '此待办没有可跟随的业务日期')
        source = source_record(db, item.source_kind, item.source_id, user)
        from app.tasks.sources import ship_date
        item.source_ship_date = ship_date(db, source, item.source_kind)
        day = source_date(item.source_ship_date, item.offset_days)
    item.source_changed_at = None
    item.title, item.notes = payload.title.strip(), payload.notes
    if not item.title:
        fail(422, 'empty_title', '请填写待办标题')
    if target.id != item.assignee_id:
        item.schedule_version += 1
    item.assignee_id, item.follow_source, item.notify = target.id, payload.follow_source, payload.notify
    set_schedule(item, day, payload.due_time, payload.timezone)
    item.version += 1
    history(db, item, 'updated', user, {'before': before, 'after': values(item, 'due_date due_time timezone assignee_id follow_source')})
    db.commit(); db.refresh(item)
    return task_out(item)


@router.post('/{identifier}/status')
def status(identifier: str, payload: StatusInput, db: DB, user: Writer):
    task_record(db, identifier, user)
    inserted, _ = claim(db, payload.request_id, user, 'task.status:' + identifier, payload.model_dump(mode='json'), identifier)
    item = task_record(db, identifier, user, lock=True)
    if inserted:
        check_version(item, payload.version)
        update_status(db, item, payload.status, '手动处理', now(), user)
        audit(db, user, 'tasks.status', 'task', item.id, '更新待办状态', item.store_id)
        db.commit()
    return task_out(item)
