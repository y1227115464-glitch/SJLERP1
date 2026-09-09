from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select

from app.core.api import DB, Page, fail, paginated, require, require_store, audit
from app.core.security import aware, can_access_store, has_permission
from app.models import User, new_id, now
from app.tasks.common import check_version, claim, source_allowed, source_record, task_out, task_scope, values
from app.tasks.models import RuleSchedule, TaskRule, Task
from app.tasks.schemas import ApplyRulesInput, RuleCreate, RuleInput, TemplatesInput

router = APIRouter(prefix='/api/v1')
Writer = Annotated[User, Depends(require('tasks.manage'))]
PRESETS = {
    'daily_data': {'title': '下载经营数据', 'kind': 'daily', 'due_time': '15:00', 'weekdays': list(range(7))},
    'weekly_analysis': {'title': '分析销售数据与库存情况', 'kind': 'weekly', 'weekdays': [4]},
    'purchase_order': {'title': '向供应商下单', 'kind': 'purchase_order', 'due_time': '09:00', 'weekdays': [0]},
    'production': {'title': '确认生产进度', 'kind': 'production', 'offset_days': -2},
    'dispatch': {'title': '跟进发货', 'kind': 'dispatch'},
}
CONFIG_FIELDS = 'title kind store_id weekdays due_time timezone offset_days enabled notify'


def rule_scope(statement, user):
    statement = statement.where(TaskRule.owner_id == user.id)
    if user.role != 'admin':
        statement = statement.where(TaskRule.store_id.is_(None) | TaskRule.store_id.in_([s.id for s in user.stores]))
    kinds = ['daily', 'weekly']
    if has_permission(user, 'purchases.view'):
        kinds += ['purchase_order', 'production']
    if has_permission(user, 'shipments.view'):
        kinds += ['dispatch']
    return statement.where(TaskRule.kind.in_(kinds))


def validate_scope(db, user, payload):
    if payload.store_id:
        require_store(db, user, payload.store_id)
    permission = {'purchase_order': 'purchases.view', 'production': 'purchases.view', 'dispatch': 'shipments.view'}.get(payload.kind)
    if permission and not has_permission(user, permission):
        fail(403, 'permission_denied', '当前账号不能为此业务配置提醒')


def rule_out(rule):
    output = values(rule, 'id owner_id title kind store_id weekdays due_time timezone offset_days enabled notify version active_since created_at')
    output['store_name'] = rule.store.name if rule.store else None
    return output


def open_schedule(db, rule, moment):
    if rule.enabled and rule.kind in {'daily', 'weekly'}:
        day = moment.astimezone(ZoneInfo(rule.timezone)).date()
        db.add(RuleSchedule(rule_id=rule.id, revision=rule.version, config=values(rule, CONFIG_FIELDS),
                            start_at=moment, next_run_at=moment, cursor_date=day - timedelta(days=1)))


def make_rule(db, user, payload, identifier, moment, preset_key=None):
    rule = TaskRule(id=identifier, owner_id=user.id, preset_key=preset_key, version=1,
                    active_since=moment, created_at=moment, **payload.model_dump(exclude={'due_date', 'request_id'}))
    db.add(rule); db.flush()
    open_schedule(db, rule, moment)
    return rule


@router.get('/task-rules')
def listing(db: DB, user: Writer, page: Page):
    return paginated(db, rule_scope(select(TaskRule), user).order_by(TaskRule.created_at, TaskRule.id), page, rule_out)


@router.post('/task-rules', status_code=201)
def create(payload: RuleCreate, db: DB, user: Writer):
    validate_scope(db, user, payload)
    inserted, identifier = claim(db, payload.request_id, user, 'rule.create', payload.model_dump(mode='json'), new_id())
    if not inserted:
        item = db.scalar(rule_scope(select(TaskRule).where(TaskRule.id == identifier), user))
        if item is None:
            fail(404, 'not_found', '规则不存在或无权访问')
        return rule_out(item)
    rule = make_rule(db, user, payload, identifier, now())
    audit(db, user, 'tasks.rule_create', 'task_rule', rule.id, '添加提醒规则', rule.store_id)
    db.commit(); db.refresh(rule)
    return rule_out(rule)


@router.post('/task-rules/templates', status_code=201)
def templates(payload: TemplatesInput, db: DB, user: Writer):
    if payload.store_id:
        require_store(db, user, payload.store_id)
    # Serialize template installations for one owner; a second click never resets edited presets.
    db.scalar(select(User).where(User.id == user.id).with_for_update(of=User))
    claim(db, payload.request_id, user, 'rule.templates', payload.model_dump(mode='json'), user.id)
    keys = {code: f'{user.id}:{payload.store_id or "personal"}:{code}' for code in dict.fromkeys(payload.templates)}
    existing = {r.preset_key: r for r in db.scalars(select(TaskRule).where(TaskRule.preset_key.in_(keys.values())))}
    rows = []
    for code, key in keys.items():
        value = RuleInput.model_validate({**PRESETS[code], 'store_id': payload.store_id})
        validate_scope(db, user, value)
        if code in {'daily_data', 'weekly_analysis'} and not has_permission(user, 'reports.view'):
            fail(403, 'permission_denied', '当前账号不能配置经营报表提醒')
        rows.append(existing.get(key) or make_rule(db, user, value, new_id(), now(), key))
    audit(db, user, 'tasks.templates', 'user', user.id, '添加推荐提醒模板', payload.store_id)
    db.commit()
    return {'items': [rule_out(row) for row in rows]}


@router.patch('/task-rules/{identifier}')
def edit(identifier: str, changes: dict, db: DB, user: Writer):
    rule = db.scalar(rule_scope(select(TaskRule).where(TaskRule.id == identifier), user)
                     .with_for_update(of=TaskRule, key_share=True).execution_options(populate_existing=True))
    if rule is None:
        fail(404, 'not_found', '规则不存在或无权访问')
    if 'version' not in changes or set(changes) - (set(CONFIG_FIELDS.split()) - {'kind', 'store_id'} | {'version'}):
        fail(422, 'invalid_rule', '请携带版本号；规则类型及所属店铺不能变更')
    check_version(rule, changes['version'])
    try:
        payload = RuleInput.model_validate({**values(rule, CONFIG_FIELDS), **{k: v for k, v in changes.items() if k != 'version'}})
    except ValidationError:
        fail(422, 'invalid_rule', '请检查规则时间、时区和星期')
    validate_scope(db, user, payload)
    moment = now()
    schedules = db.scalars(select(RuleSchedule).where(RuleSchedule.rule_id == rule.id, RuleSchedule.end_at.is_(None))
                          .with_for_update()).all()
    for schedule in schedules:
        schedule.end_at = moment
        schedule.next_run_at = moment
    if payload.enabled and not rule.enabled:
        rule.active_since = moment
    for key, value in payload.model_dump(exclude={'due_date'}).items():
        setattr(rule, key, value)
    rule.version += 1
    open_schedule(db, rule, moment)
    audit(db, user, 'tasks.rule_update', 'task_rule', rule.id, '修改提醒规则；已生成待办保留单次安排', rule.store_id)
    db.commit()
    return rule_out(rule)


@router.post('/tasks/apply-rules')
def apply_rules(payload: ApplyRulesInput, db: DB, user: Writer):
    source = source_record(db, payload.source_kind, payload.source_id, user)
    claim(db, payload.request_id, user, 'task.apply_rules', payload.model_dump(mode='json'), payload.source_id)
    from app.tasks.sources import lock_source
    source = lock_source(db, payload.source_kind, payload.source_id)
    rules = db.scalars(rule_scope(select(TaskRule).where(TaskRule.id.in_(payload.rule_ids)), user)
                       .order_by(TaskRule.id).with_for_update(of=TaskRule, key_share=True)).all()
    if len(rules) != len(set(payload.rule_ids)) or any(not r.enabled or r.kind in {'daily', 'weekly'} for r in rules):
        fail(422, 'invalid_rules', '请选择自己已启用的单据提醒规则')
    if any(r.store_id and r.store_id != source.store_id for r in rules):
        fail(422, 'rule_scope_mismatch', '规则与单据店铺不一致')
    if payload.source_kind == 'shipment' and any(r.kind != 'dispatch' for r in rules):
        fail(422, 'invalid_rules', '货件只适用发货提醒')
    from app.tasks.sources import materialize, reconcile
    moment = now()
    materialize(db, source, payload.source_kind, rules, moment, moment)
    reconcile(db, source, payload.source_kind, moment)
    db.commit()
    query = task_scope(select(Task).where(Task.source_kind == payload.source_kind, Task.source_id == source.id,
                                        Task.rule_id.in_(payload.rule_ids)), user)
    return {'items': [task_out(item) for item in db.scalars(query)]}
