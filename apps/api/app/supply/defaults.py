from sqlalchemy import select

from app.core.api import audit, fail
from app.models import new_id
from app.supply.common import active_warehouse, insert_ignore
from app.supply.models import Warehouse


DEFAULT_FBA_CODE = 'FBA-DEFAULT'


def resolve_warehouse(db, user, identifier=None):
    """Omitted warehouse fields share an active FBA ledger, without a site choice."""
    if identifier is not None:
        return active_warehouse(db, identifier)
    warehouse = db.scalar(select(Warehouse).where(Warehouse.kind == 'fba', Warehouse.is_active.is_(True))
                          .order_by(Warehouse.created_at, Warehouse.id).limit(1))
    if warehouse is not None:
        return warehouse
    inserted = insert_ignore(db, Warehouse, [dict(id=new_id(), code=DEFAULT_FBA_CODE,
                             name='FBA仓库', kind='fba', address='', is_active=True)], ['code'])
    warehouse = db.scalar(select(Warehouse).where(Warehouse.code == DEFAULT_FBA_CODE))
    if warehouse.kind != 'fba' or not warehouse.is_active:
        fail(409, 'default_fba_unavailable', '请启用一个 FBA 仓库，或检查 FBA-DEFAULT 仓库档案')
    if inserted:
        audit(db, user, 'warehouses.create', 'warehouse', warehouse.id, '自动建立默认 FBA 仓库')
    return warehouse
