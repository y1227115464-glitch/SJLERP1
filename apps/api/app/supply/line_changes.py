import hashlib
import json
from uuid import UUID

from pydantic import Field, model_validator

from app.catalog_schemas import Money
from app.core.api import fail
from app.schemas import Input
from app.supply.schemas import Identifier, Quantity, ShipmentItem


def lines_version(record):
    # Includes receipts and packing: these can change without updating the header timestamp.
    rows = [(line.id, line.product_id, line.quantity, line.received_quantity,
             getattr(line, 'cancelled_quantity', 0), getattr(line, 'units_per_carton', None))
            for line in record.lines]
    return hashlib.sha256(json.dumps([record.status, sorted(rows)]).encode()).hexdigest()


def check_version(record, expected):
    if lines_version(record) != expected:
        fail(409, 'lines_changed', '单据商品、数量或收货状态已变化，请关闭编辑并刷新后重试')


class PurchaseQuantity(Input):
    product_id: Identifier
    quantity: Quantity
    unit_price: Money | None = None


class LineChange(Input):
    request_id: UUID
    expected_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    reason: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def distinct_products(self):
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError('同一商品只能填写一行')
        return self


class PurchaseLineChange(LineChange):
    lines: list[PurchaseQuantity] = Field(min_length=1, max_length=100)


class ShipmentLineChange(LineChange):
    lines: list[ShipmentItem] = Field(min_length=1, max_length=100)
