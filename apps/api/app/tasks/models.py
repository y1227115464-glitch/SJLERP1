from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, Store, User, new_id, now


class TaskRule(Base):
    __tablename__ = 'task_rules'
    __table_args__ = (Index('ix_task_rule_owner', 'owner_id', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    store_id: Mapped[str | None] = mapped_column(ForeignKey('stores.id'), nullable=True)
    preset_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    weekdays: Mapped[list] = mapped_column(JSON, default=list)
    due_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default='Asia/Shanghai')
    offset_days: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    owner: Mapped[User] = relationship(lazy='joined')
    store: Mapped[Store | None] = relationship(lazy='joined')


class RuleSchedule(Base):
    __tablename__ = 'task_rule_schedules'
    __table_args__ = (UniqueConstraint('rule_id', 'revision'), Index('ix_rule_schedule_cursor', 'next_run_at', 'cursor_date'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_id: Mapped[str] = mapped_column(ForeignKey('task_rules.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor_date: Mapped[date] = mapped_column(Date)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    exhausted: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (CheckConstraint("status IN ('pending','completed','cancelled')"),
        Index('ix_task_owner_status_due', 'assignee_id', 'status', 'due_at'),
        Index('ix_task_store_status_due', 'store_id', 'status', 'due_at'),
        Index('ix_task_source', 'source_kind', 'source_id'), Index('ix_task_delivery', 'status', 'due_at'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_key: Mapped[str] = mapped_column(String(180), unique=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    assignee_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    store_id: Mapped[str | None] = mapped_column(ForeignKey('stores.id'), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    source_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_number: Mapped[str] = mapped_column(String(60), default='')
    action_kind: Mapped[str] = mapped_column(String(30), default='manual')
    rule_id: Mapped[str | None] = mapped_column(ForeignKey('task_rules.id'), nullable=True, index=True)
    occurrence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default='Asia/Shanghai')
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    day_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    day_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_source: Mapped[bool] = mapped_column(Boolean, default=False)
    offset_days: Mapped[int] = mapped_column(Integer, default=0)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    schedule_version: Mapped[int] = mapped_column(Integer, default=1)
    notified_version: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_reason: Mapped[str] = mapped_column(String(200), default='')
    source_ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id], lazy='joined')
    store: Mapped[Store | None] = relationship(lazy='joined')


class TaskHistory(Base):
    __tablename__ = 'task_history'
    __table_args__ = (Index('ix_task_history_time', 'task_id', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SourceEvent(Base):
    __tablename__ = 'task_source_events'
    __table_args__ = (Index('ix_task_event_pending', 'processed_at', 'created_at'),
                     Index('ix_task_event_source', 'source_kind', 'source_id'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(String(200), default='')


class TaskOperation(Base):
    __tablename__ = 'task_operations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskNotice(Base):
    __tablename__ = 'task_notices'
    notification_id: Mapped[str] = mapped_column(ForeignKey('notifications.id'), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), primary_key=True, index=True)
