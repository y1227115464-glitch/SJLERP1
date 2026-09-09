"""Persist reminder intent in the same transaction as the business fact."""
from app.tasks.models import SourceEvent


def enqueue(db, source, source_kind, user, kind, data=None):
    db.add(SourceEvent(source_kind=source_kind, source_id=source.id, actor_id=user.id, kind=kind, data=data or {}))
