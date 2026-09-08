import hashlib
import secrets
from datetime import timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

hasher = PasswordHasher()
ALL_PERMISSIONS = [
    "workspace.view", "stores.view", "stores.manage", "stores.export", "users.manage", "audit.view",
    "jobs.view", "jobs.run", "files.view", "files.upload", "notifications.view", "approvals.view",
    "costs.view", "finance.view",
    "products.view", "products.manage", "suppliers.view", "suppliers.manage", "quotes.view", "quotes.manage",
    "purchases.view", "purchases.manage", "shipments.view", "shipments.manage", "inventory.view", "inventory.adjust", "warehouses.manage",
    "reports.view", "reports.import",
]
BASIC = ["workspace.view", "stores.view", "jobs.view", "jobs.run", "files.view", "files.upload", "notifications.view", "approvals.view"]
ROLES = {
    "admin": {"label": "管理员", "permissions": ALL_PERMISSIONS},
    "manager": {"label": "经理", "permissions": BASIC + ["stores.export", "audit.view", "costs.view", "finance.view"]},
    "operator": {"label": "运营", "permissions": BASIC + ["stores.export"]},
    "finance": {"label": "财务", "permissions": BASIC + ["stores.export", "audit.view", "costs.view", "finance.view"]},
    "warehouse": {"label": "仓库", "permissions": BASIC},
}
for role, config in ROLES.items():
    if role == "admin":
        continue
    config["permissions"] = list(config["permissions"]) + ["products.view"]
    if role in {"manager", "operator"}:
        config["permissions"].append("products.manage")
    if role in {"manager", "finance", "warehouse"}:
        config["permissions"].append("suppliers.view")
    if role in {"manager", "finance"}:
        config["permissions"] += ["suppliers.manage", "quotes.view", "quotes.manage"]
    config['permissions'] += ['shipments.view', 'inventory.view']
    if role in {'manager', 'finance', 'warehouse'}:
        config['permissions'].append('purchases.view')
    if role in {'manager', 'finance'}:
        config['permissions'].append('purchases.manage')
    if role in {'manager', 'warehouse'}:
        config['permissions'] += ['shipments.manage', 'inventory.adjust', 'warehouses.manage']
    if role in {'manager', 'operator', 'finance'}:
        config['permissions'] += ['reports.view', 'reports.import']


def permissions(user) -> list[str]:
    return ROLES.get(user.role, {}).get("permissions", [])


def has_permission(user, permission: str) -> bool:
    return user.is_active and permission in permissions(user)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def token() -> str:
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, VerifyMismatchError, InvalidHashError):
        return False


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def can_access_store(user, store_id: str) -> bool:
    return user.role == "admin" or store_id in {store.id for store in user.stores}
