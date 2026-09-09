"""Transactional source events; reminders never participate in business validation."""
import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select

from app.core.security import aware, can_access_store, has_permission
from app.models import now
from app.supply.models import PurchaseOrder, Shipment
from app.tasks.common import history, insert_tasks, source_allowed, task_row, update_status
from app.tasks.dates import next_weekday, set_schedule, source_date
from app.tasks.models import SourceEvent, Task, TaskRule


def lock_source(db, kind, identifier):
    """Use the same aggregate lock order as supply commands: purchase, then shipment.

    Refresh after acquiring the lock; another worker may have reconciled a newer event
    while this transaction was waiting. Child shipment edits also lock their purchase.
    """
    parent_id = db.scalar(select(Shipment.purchase_order_id).where(Shipment.id == identifier)) if kind == 'shipment' else identifier
    if parent_id:
        db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == parent_id)
                  .with_for_update(of=PurchaseOrder).execution_options(populate_existing=True))
    model = PurchaseOrder if kind == 'purchase' else Shipment
    return db.scalar(select(model).where(model.id == identifier).with_for_update(of=model)
                     .execution_options(populate_existing=True))


def ship_date(db, source, kind):
    if kind == 'shipment' and not source.planned_ship_date and source.purchase_order_id:
        return db.get(PurchaseOrder, source.purchase_order_id).planned_ship_date
    return source.planned_ship_date


def eligible(rule, source, kind):
    return (rule.enabled and has_permission(rule.owner, 'tasks.manage')
            and source_allowed(rule.owner, kind) and can_access_store(rule.owner, source.store_id)
            and (rule.store_id is None or rule.store_id == source.store_id))


def materialize(db, source, kind, rules, origin, moment):
    if source.status in {'cancelled', 'closed', 'received'}:
        return
    rows = []
    planned = ship_date(db, source, kind)
    for rule in rules:
        if not eligible(rule, source, kind):
            continue
        if rule.kind == 'purchase_order':
            if kind != 'purchase' or source.status != 'draft':
                continue
            day = next_weekday(origin, rule.weekdays[0], rule.due_time, rule.timezone)
        elif rule.kind in {'production', 'dispatch'}:
            if kind == 'shipment' and (rule.kind != 'dispatch' or source.status != 'planned'):
                continue
            day = source_date(planned, rule.offset_days)
        else:
            continue
        rows.append(task_row(rule, f'{rule.id}:{kind}:{source.id}', origin, source=source, source_kind=kind, day=day))
    insert_tasks(db, rows)
    db.flush()


def reconcile(db, source, kind, moment, *, progress_at=None):
    """Reconcile one aggregate; all child quantities/tasks are fetched in batches."""
    if kind == 'shipment' and source.purchase_order_id:
        parent = db.get(PurchaseOrder, source.purchase_order_id)
        return reconcile(db, parent, 'purchase', moment)
    children = db.scalars(select(Shipment).where(Shipment.purchase_order_id == source.id)).all() if kind == 'purchase' else []
    ids = [source.id] + [child.id for child in children]
    tasks = db.scalars(select(Task).where(Task.source_id.in_(ids), Task.status == 'pending')
                       .order_by(Task.id).with_for_update(of=Task)).all()
    by_source = defaultdict(list)
    for task in tasks:
        by_source[task.source_id].append(task)
    children_by_id = {child.id: child for child in children}
    shipped, allocated = defaultdict(int), defaultdict(int)
    for child in children:
        if child.status == 'cancelled':
            continue
        for line in child.lines:
            allocated[line.product_id] += line.quantity
            if child.shipped_at:
                shipped[line.product_id] += line.quantity
    fully_shipped = kind == 'purchase' and all(shipped[line.product_id] >= line.quantity - line.cancelled_quantity for line in source.lines)
    fully_allocated = kind == 'purchase' and all(allocated[line.product_id] >= line.quantity - line.cancelled_quantity for line in source.lines)
    for task in tasks:
        record = children_by_id.get(task.source_id, source)
        cancelled = record.status == 'cancelled'
        # Manual tasks belong to the user, even when linked to a document.
        if task.action_kind == 'manual':
            continue
        if cancelled:
            update_status(db, task, 'cancelled', '关联单据已取消', moment)
            continue
        done = ((task.action_kind == 'purchase_order' and source.status != 'draft')
                or (task.action_kind == 'production' and progress_at and aware(task.created_at) <= progress_at)
                or (task.action_kind == 'dispatch' and (bool(record.shipped_at) if isinstance(record, Shipment) else fully_shipped)))
        if done:
            update_status(db, task, 'completed', '业务记录已完成对应事项', moment)
            continue
        covered = (record is source and task.action_kind == 'dispatch' and fully_allocated
                   and all(any(t.rule_id == task.rule_id and t.action_kind == 'dispatch' for t in by_source[child.id])
                           for child in children if child.status == 'planned'))
        if task.suppressed != bool(covered):
            task.suppressed = bool(covered)
            task.version += 1
            history(db, task, 'coverage', data={'covered_by_shipments': task.suppressed})
        planned = record.planned_ship_date or (source.planned_ship_date if isinstance(record, Shipment) else None)
        target = source_date(planned, task.offset_days)
        if task.action_kind in {'production', 'dispatch'} and task.source_ship_date != planned:
            task.source_ship_date = planned
            task.version += 1
            if task.follow_source:
                previous = task.due_date
                set_schedule(task, target, task.due_time, task.timezone)
                task.source_changed_at = None
                history(db, task, 'source_reschedule', data={'before': str(previous), 'after': str(target)})
            elif task.source_changed_at is None:
                task.source_changed_at = moment
                task.version += 1
                history(db, task, 'source_changed', data={'planned_ship_date': str(planned)})


def process_event(db, moment):
    event = db.scalar(select(SourceEvent).where(SourceEvent.processed_at.is_(None),
        SourceEvent.retry_at.is_(None) | (SourceEvent.retry_at <= moment))
                      .order_by(SourceEvent.created_at, SourceEvent.id).limit(1).with_for_update(skip_locked=True))
    if event is None:
        return False
    try:
        # Isolate a bad unit so unrelated recurring reminders and source events can proceed.
        with db.begin_nested():
            apply_event(db, event, moment)
        event.error_message, event.retry_at = '', None
    except Exception as error:
        event.attempts += 1
        event.retry_at = moment + timedelta(seconds=min(3600, 30 * 2 ** min(event.attempts, 7)))
        event.error_message = type(error).__name__
        logging.getLogger(__name__).error('Reminder source event %s failed (%s); retry scheduled', event.id, event.error_message)
    return True


def apply_event(db, event, moment):
    source = lock_source(db, event.source_kind, event.source_id)
    if source is None:
        event.processed_at = moment
        return True
    if event.kind == 'created':
        rules = db.scalars(select(TaskRule).where(TaskRule.owner_id == event.actor_id, TaskRule.enabled.is_(True),
                           TaskRule.active_since <= event.created_at, TaskRule.kind.in_(['purchase_order', 'production', 'dispatch']))).all()
        materialize(db, source, event.source_kind, rules, aware(event.created_at), moment)
        if isinstance(source, Shipment) and source.purchase_order_id:
            # Carry the parent's enabled dispatch rules into each batch, even if a colleague creates the shipment.
            inherited = db.scalars(select(TaskRule).where(TaskRule.enabled.is_(True), TaskRule.id.in_(
                select(Task.rule_id).where(Task.source_kind == 'purchase', Task.source_id == source.purchase_order_id,
                                           Task.action_kind == 'dispatch', Task.status == 'pending')))).all()
            materialize(db, source, 'shipment', inherited, aware(event.created_at), moment)
    reconcile(db, source, event.source_kind, moment, progress_at=aware(event.created_at) if event.kind == 'production' else None)
    event.processed_at = moment
    return True
