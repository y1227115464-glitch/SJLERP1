"""Manual purchase payment and invoice follow-up, independent of receipt status."""
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.api import audit
from app.core.security import has_permission
from app.models import Base, new_id, now
from app.supply.common import operation, purchase_out, scoped_record, values
from app.supply.models import PurchaseOrder
from app.supply.schemas import ActionInput

PaymentStatus = Literal['unpaid', 'partial', 'paid']
InvoiceStatus = Literal['pending', 'partial', 'received', 'not_required']


class FinanceInput(ActionInput):
    payment_status: PaymentStatus
    invoice_status: InvoiceStatus
    notes: str = Field(default='', max_length=2000)


class PurchaseFinanceEvent(Base):
    __tablename__ = 'purchase_finance_events'
    __table_args__ = (Index('ix_purchase_finance_event_time', 'purchase_order_id', 'created_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    purchase_order_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id'))
    payment_status: Mapped[str] = mapped_column(String(20))
    invoice_status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text)
    actor_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def history(db, identifier, user):
    if not has_permission(user, 'costs.view'):
        return []
    rows = db.scalars(select(PurchaseFinanceEvent).where(PurchaseFinanceEvent.purchase_order_id == identifier)
        .order_by(PurchaseFinanceEvent.created_at.desc(), PurchaseFinanceEvent.id).limit(50))
    return [values(row, 'id payment_status invoice_status notes actor_name created_at') for row in rows]


def followup(identifier, payload, db, user):
    scoped_record(db, PurchaseOrder, identifier, user)
    inserted, _ = operation(db, payload, user, f'purchase.finance:{identifier}', identifier)
    record = scoped_record(db, PurchaseOrder, identifier, user, lock=True)
    if inserted:
        record.payment_status, record.invoice_status = payload.payment_status, payload.invoice_status
        record.finance_notes, record.finance_updated_at = payload.notes, now()
        db.add(PurchaseFinanceEvent(purchase_order_id=identifier, payment_status=payload.payment_status,
            invoice_status=payload.invoice_status, notes=payload.notes, actor_name=user.display_name))
        audit(db, user, 'purchases.finance.update', 'purchase_order', identifier, '更新付款和发票跟进状态', record.store_id)
    db.commit()
    return purchase_out(record, user)
