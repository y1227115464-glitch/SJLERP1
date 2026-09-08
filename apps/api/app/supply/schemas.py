from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.catalog_schemas import Currency, Money
from app.schemas import Input

Identifier = Annotated[str, Field(min_length=1, max_length=36)]
Quantity = Annotated[int, Field(strict=True, gt=0, le=1000000000)]


class WarehouseInput(Input):
    code: str = Field(min_length=1, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=120)
    kind: Literal['domestic', 'overseas', 'fba'] = 'domestic'
    address: str = Field(default='', max_length=1000)
    is_active: bool = True


class PurchaseItem(Input):
    product_id: Identifier
    quantity: Quantity
    unit_price: Money


class PurchaseInput(Input):
    request_id: UUID
    store_id: Identifier
    supplier_id: Identifier
    order_date: date
    expected_date: date | None = None
    currency: Currency = 'CNY'
    payment_terms: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=5000)
    lines: list[PurchaseItem] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def valid_order(self):
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError('同一商品只能填写一行')
        if self.expected_date and self.expected_date < self.order_date:
            raise ValueError('预计到货不能早于采购日期')
        return self


class ShipmentItem(Input):
    product_id: Identifier
    quantity: Quantity


class ShipmentInput(Input):
    request_id: UUID
    store_id: Identifier
    purchase_order_id: Identifier | None = None
    source_warehouse_id: Identifier | None = None
    destination_warehouse_id: Identifier
    carrier: str = Field(default='', max_length=120)
    tracking_number: str = Field(default='', max_length=120)
    amazon_shipment_id: str = Field(default='', max_length=120)
    expected_date: date | None = None
    notes: str = Field(default='', max_length=5000)
    lines: list[ShipmentItem] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def valid_shipment(self):
        if bool(self.purchase_order_id) == bool(self.source_warehouse_id):
            raise ValueError('请选择采购单或发货仓库作为唯一来源')
        if self.source_warehouse_id == self.destination_warehouse_id:
            raise ValueError('发货仓库和目的仓库不能相同')
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError('同一商品只能填写一行')
        return self


class ShipmentUpdate(Input):
    carrier: str = Field(default='', max_length=120)
    tracking_number: str = Field(default='', max_length=120)
    amazon_shipment_id: str = Field(default='', max_length=120)
    expected_date: date | None = None
    notes: str = Field(default='', max_length=5000)


class EventInput(Input):
    request_id: UUID
    stage: Literal['in_transit', 'customs', 'delivered', 'delayed']
    notes: str = Field(min_length=1, max_length=2000)


class ActionInput(Input):
    request_id: UUID


class ReceiptItem(Input):
    line_id: Identifier
    quantity: Quantity


class ReceiptInput(Input):
    request_id: UUID
    notes: str = Field(default='', max_length=2000)
    lines: list[ReceiptItem] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError('收货行不能重复')
        return self


class AdjustmentInput(Input):
    request_id: UUID
    store_id: Identifier
    warehouse_id: Identifier
    product_id: Identifier
    quantity: Annotated[int, Field(strict=True, ge=-1000000000, le=1000000000)]
    reason: str = Field(min_length=1, max_length=2000)
    kind: Literal['opening', 'adjustment'] = 'adjustment'

    @model_validator(mode='after')
    def valid_delta(self):
        if self.quantity == 0 or (self.kind == 'opening' and self.quantity < 0):
            raise ValueError('变动数量不能为零，期初数量必须为正数')
        return self
