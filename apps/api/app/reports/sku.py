"""Established weekly-report SKU grouping; never infer other aliases."""
from sqlalchemy import case

SIZE_ALIASES = {'CMBQ-XXL-250S', 'CMBQ-XXXL-250S', 'CMBQ-XS-250S', 'CMBQ-M-250S', 'CMBQ-S-250S', 'CMBQ-XL-250S'}


def normalized_sku(value):
    return 'CMBQ-L-250S' if value in SIZE_ALIASES else value


def sku_column(column):
    return case((column.in_(sorted(SIZE_ALIASES)), 'CMBQ-L-250S'), else_=column)
