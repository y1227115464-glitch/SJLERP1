from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from app.schemas import Input

Clock = Annotated[str, Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')]
Id = Annotated[str, Field(min_length=1, max_length=36)]
Kind = Literal['daily', 'weekly', 'purchase_order', 'production', 'dispatch']
Source = Literal['purchase', 'shipment', 'imports', 'sales', 'inventory']


class ScheduleInput(Input):
    due_date: date | None = Field(default=None, ge=date(1900, 1, 1), le=date(2200, 12, 31))
    due_time: Clock | None = None
    timezone: str = Field(default='Asia/Shanghai', max_length=64)

    @field_validator('timezone')
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('未知时区')
        return value


class TaskCreate(ScheduleInput):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default='', max_length=5000)
    store_id: Id | None = None
    assignee_id: Id | None = None
    source_kind: Source | None = None
    source_id: Id | None = None
    notify: bool = True

    @model_validator(mode='after')
    def source_pair(self):
        if (self.source_kind in {'purchase', 'shipment'}) != bool(self.source_id):
            raise ValueError('单据来源及编号需要同时填写')
        return self


class TaskEdit(ScheduleInput):
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default='', max_length=5000)
    assignee_id: Id | None = None
    follow_source: bool = False
    notify: bool = True


class StatusInput(Input):
    request_id: UUID
    version: int = Field(ge=1)
    status: Literal['pending', 'completed', 'cancelled']


class RuleInput(ScheduleInput):
    title: str = Field(min_length=1, max_length=200)
    kind: Kind
    store_id: Id | None = None
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    offset_days: int = Field(default=0, ge=-365, le=365)
    enabled: bool = True
    notify: bool = True

    @field_validator('title')
    @classmethod
    def title_text(cls, value):
        if not value.strip():
            raise ValueError('请填写标题')
        return value.strip()

    @field_validator('weekdays')
    @classmethod
    def days(cls, value):
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError('周几必须为0至6且不重复')
        return sorted(value)

    @model_validator(mode='after')
    def rule_fields(self):
        if self.due_date is not None:
            raise ValueError('规则不指定单次日期')
        if self.kind == 'purchase_order' and len(self.weekdays) != 1:
            raise ValueError('下单提醒需指定一个星期')
        return self


class RuleCreate(RuleInput):
    request_id: UUID


class TemplatesInput(Input):
    request_id: UUID
    store_id: Id | None = None
    templates: list[Literal['daily_data', 'weekly_analysis', 'purchase_order', 'production', 'dispatch']] = Field(min_length=1, max_length=5)


class ApplyRulesInput(Input):
    request_id: UUID
    source_kind: Literal['purchase', 'shipment']
    source_id: Id
    rule_ids: list[Id] = Field(min_length=1, max_length=20)


class ProgressInput(Input):
    request_id: UUID
    notes: str = Field(min_length=1, max_length=2000)
