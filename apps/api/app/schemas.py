from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Role = Literal["admin", "manager", "operator", "finance", "warehouse"]
Password = Annotated[str, StringConstraints(strip_whitespace=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    email: str = Field(min_length=3, max_length=254)
    password: Password = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()


class UserCreate(Input):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    display_name: str = Field(min_length=1, max_length=100)
    password: Password = Field(min_length=12, max_length=256)
    role: Role
    store_ids: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()


class UserUpdate(Input):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    password: Password | None = Field(default=None, min_length=12, max_length=256)
    role: Role | None = None
    store_ids: list[str] | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class StoreCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    legal_entity: str = Field(default="", max_length=200)
    brand: str = Field(default="", max_length=120)
    marketplace: str = Field(default="US", min_length=2, max_length=20)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    is_active: bool = True


class StoreUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    legal_entity: str | None = Field(default=None, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    marketplace: str | None = Field(default=None, min_length=2, max_length=20)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    is_active: bool | None = None


class JobCreate(Input):
    kind: Literal["workspace_check"]
    store_id: str | None = None
