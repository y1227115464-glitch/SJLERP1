from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas import Input

Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


def http_url(value: str) -> str:
    if not value:
        return value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or any(ord(c) < 32 for c in value):
        raise ValueError("链接仅支持 HTTP 或 HTTPS，且不能包含凭据")
    return value


class ProductCreate(Input):
    internal_sku: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=500)
    name_zh: str = Field(default="", max_length=200)
    brand: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=120)
    specifications: str = Field(default="", max_length=2000)
    material: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=20000)
    description: str = Field(default="", max_length=20000)
    asin: str = Field(default="", max_length=40)
    fnsku: str = Field(default="", max_length=40)
    image_url: str = Field(default="", max_length=2000)
    image_urls: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=200)
    bullet_points: list[Annotated[str, Field(max_length=20000)]] = Field(default_factory=list, max_length=100)
    amazon_url: str = Field(default="", max_length=2000)
    sale_price: Money | None = None
    original_sale_price: Money | None = None
    currency: Currency = "USD"
    is_active: bool = True
    notes: str = Field(default="", max_length=20000)
    review_notes: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=100)

    @field_validator("image_url", "amazon_url")
    @classmethod
    def valid_url(cls, value):
        return http_url(value)

    @field_validator("image_urls")
    @classmethod
    def valid_urls(cls, values):
        return [http_url(value) for value in values]


class SupplierCreate(Input):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=80)
    email: str = Field(default="", max_length=254)
    address: str = Field(default="", max_length=1000)
    payment_terms: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=10000)
    is_active: bool = True


class QuoteTier(Input):
    min_quantity: Annotated[int, Field(strict=True, gt=0, le=2147483647)] | None = None
    unit_price: Money | None = None
    tax_inclusive_price: Money | None = None
    unit: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=2000)


class QuoteCreate(Input):
    supplier_id: str = Field(min_length=1, max_length=36)
    product_ids: list[str] = Field(default_factory=list, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    packaging: str = Field(default="", max_length=500)
    currency: Currency = "CNY"
    tax_status: Literal["unknown", "included", "excluded", "mixed"] = "unknown"
    includes_shipping: bool | None = None
    includes_labeling: bool | None = None
    labeling_fee: Money | None = None
    review_status: Literal["confirmed", "needs_review"] = "needs_review"
    review_notes: str = Field(default="", max_length=20000)
    notes: str = Field(default="", max_length=20000)
    source_text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(default="", max_length=20000)
    source_reference: str = Field(default="", max_length=2000)
    is_active: bool = True
    tiers: list[QuoteTier] = Field(min_length=1, max_length=30)

    @field_validator("product_ids")
    @classmethod
    def distinct_products(cls, values):
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_tiers(self):
        quantities = [tier.min_quantity for tier in self.tiers if tier.min_quantity is not None]
        if len(quantities) != len(set(quantities)):
            raise ValueError("阶梯起订量不能重复")
        return self


class ImportConfirm(Input):
    token: str = Field(min_length=20, max_length=64)


# PATCH accepts only fields on the matching create schema, with validation after
# merging into the stored record. This preserves explicit null for unknown money
# while rejecting null for required strings and retaining the same limits.
def validate_patch(schema, stored: dict, changes: dict):
    return schema.model_validate({**stored, **changes})
