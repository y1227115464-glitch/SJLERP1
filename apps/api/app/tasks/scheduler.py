"""Bounded, restart-safe scheduler. Each unit commits independently of business requests."""
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select

from app.core.security import aware, can_access_store, has_permission
from app.models import Notification, new_id, now
from app.supply.models import Shipment
from app.tasks.common import insert_tasks, source_allowed, task_row
from app.tasks.dates import scheduled_times
from app.tasks.models import RuleSchedule, SourceEvent, Task, TaskRule, TaskNotice
from app.tasks.sources import process_event


def periodic(db, moment):
    schedule = db.scalar(select(RuleSchedule).where(RuleSchedule.exhausted.is_(False), RuleSchedule.next_run_at <= moment)
                         .order_by(RuleSchedule.cursor_date, RuleSchedule.id).limit(1).with_for_update(skip_locked=True))
    if schedule is None:
        return False
    rule = db.get(TaskRule, schedule.rule_id)
    config = schedule.config
    zone = ZoneInfo(config['timezone'])
    horizon = moment.astimezone(zone).date() + timedelta(days=7)
    end = aware(schedule.end_at) if schedule.end_at else None
    if end:
        horizon = min(horizon, end.astimezone(zone).date())
    if schedule.cursor_date >= horizon:
        if end:
            schedule.exhausted = True
            return True
        tomorrow = moment.astimezone(zone).date() + timedelta(days=1)
        schedule.next_run_at = scheduled_times(tomorrow, None, config['timezone'])[1]
        return True
    last = min(horizon, schedule.cursor_date + timedelta(days=90))
    active = has_permission(rule.owner, 'tasks.manage') and (not config['store_id'] or can_access_store(rule.owner, config['store_id']))
    target = {'daily_data': 'imports', 'weekly_analysis': 'sales'}.get((rule.preset_key or '').rsplit(':', 1)[-1])
    active = active and source_allowed(rule.owner, target)
    snapshot = SimpleNamespace(id=rule.id, owner_id=rule.owner_id, **config)
    rows = []
    day = schedule.cursor_date + timedelta(days=1)
    while day <= last:
        due, start, finish = scheduled_times(day, config['due_time'], config['timezone'])
        in_window = (due >= aware(schedule.start_at) if config['due_time'] else finish > aware(schedule.start_at)) and (end is None or (due < end if config['due_time'] else start < end))
        if active and day.weekday() in config['weekdays'] and in_window:
            rows.append(task_row(snapshot, f'{rule.id}:{day}', moment, source_kind=target, day=day))
        day += timedelta(days=1)
    insert_tasks(db, rows)
    schedule.cursor_date = last
    schedule.exhausted = bool(end and last >= horizon)
    schedule.next_run_at = (scheduled_times(moment.astimezone(zone).date() + timedelta(days=1), None, config['timezone'])[1]
                            if last >= horizon and not end else moment)
    return True


def deliver(db, moment):
    # Do not send stale reminders while a source event awaits reconciliation.
    source_pending = exists(select(SourceEvent.id).where(SourceEvent.processed_at.is_(None),
        (SourceEvent.source_id == Task.source_id) | SourceEvent.source_id.in_(
            select(Shipment.purchase_order_id).where(Shipment.id == Task.source_id).correlate(Task))))
    tasks = db.scalars(select(Task).where(Task.status == 'pending', Task.suppressed.is_(False), Task.notify.is_(True),
        Task.due_time.is_not(None), Task.due_at <= moment, Task.notified_version < Task.schedule_version, ~source_pending)
        .order_by(Task.due_at, Task.id).limit(200).with_for_update(of=Task, skip_locked=True)).all()
    groups = defaultdict(list)
    for task in tasks:
        if (has_permission(task.assignee, 'tasks.manage') and source_allowed(task.assignee, task.source_kind)
                and (not task.store_id or can_access_store(task.assignee, task.store_id))):
            groups[task.assignee_id].append(task)
        # Revoked or inactive recipients are not retried forever; the task remains accessible on permission restoration.
        task.notified_version = task.schedule_version
    notices, links = [], []
    for user_id, items in groups.items():
        identifier = new_id()
        # Keep all contributing tasks so a reassignment/revocation cannot hide other due work.
        notices.append(Notification(id=identifier, user_id=user_id, task_id=items[0].id, title='待办提醒',
                                    message='有待办到了提醒时间，请前往工作台处理。'))
        links.extend(TaskNotice(notification_id=identifier, task_id=item.id) for item in items)
    db.add_all(notices)
    db.flush()
    db.add_all(links)
    return len(tasks)


def tick(session_factory, moment=None):
    moment = moment or now()
    for _ in range(30):
        with session_factory() as db, db.begin():
            more = process_event(db, moment)
        if not more:
            break
    for _ in range(30):
        with session_factory() as db, db.begin():
            more = periodic(db, moment)
        if not more:
            break
    with session_factory() as db, db.begin():
        return deliver(db, moment)
