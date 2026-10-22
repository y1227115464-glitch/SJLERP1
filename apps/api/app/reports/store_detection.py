"""Resolve report ownership from exact business identifiers, never UI filters."""
from collections import defaultdict

from sqlalchemy import select

from app.core.security import can_access_store
from app.models import Product, Store
from app.reports.comparison import chunks
from app.reports.models import AdRecord, BrandAdAllocation, SalesRecord
from app.reports.sku import normalized_sku, sku_column


def detect_store(db, user, rows):
    stores = {store.id: store for store in db.scalars(select(Store))}
    brands = defaultdict(set)
    for store in stores.values():
        if store.brand.strip():
            brands[store.brand].add(store.id)
    identifiers = {
        'sku': {normalized_sku(row['data']['sku']) for row in rows if row['data'].get('sku')},
        'asin': {row['data']['asin'] for row in rows if row['data'].get('asin')},
        'campaign': {row['data']['campaign'] for row in rows if row['data'].get('ad_type') == 'sponsored_brands'},
    }
    matches = {field: defaultdict(set) for field in identifiers}
    # Include all stores before applying access/active checks: a duplicate in an
    # unauthorized or inactive store must not turn into a false unique match.
    for field in ('sku', 'asin'):
        column = sku_column(Product.internal_sku) if field == 'sku' else Product.asin
        for group in chunks(identifiers[field]):
            for value, brand in db.execute(select(column, Product.brand).where(column.in_(group)).distinct()):
                matches[field][value].update(brands.get(brand, set()))
            for model in (SalesRecord, AdRecord):
                column_history = sku_column(model.sku) if field == 'sku' else model.asin
                for value, store_id in db.execute(select(column_history, model.store_id)
                        .where(column_history.in_(group)).distinct()):
                    matches[field][value].add(store_id)
    for group in chunks(identifiers['campaign']):
        for campaign, store_id in db.execute(select(BrandAdAllocation.campaign, BrandAdAllocation.store_id)
                .where(BrandAdAllocation.campaign.in_(group), BrandAdAllocation.is_deleted.is_(False))):
            matches['campaign'][campaign].add(store_id)
        for campaign, store_id in db.execute(select(AdRecord.campaign, AdRecord.store_id)
                .where(AdRecord.campaign.in_(group), AdRecord.ad_type == 'sponsored_brands').distinct()):
            matches['campaign'][campaign].add(store_id)
    candidates = set(stores)
    if not rows:
        return None
    for row in rows:
        data = row['data']
        fields = ('campaign',) if data.get('ad_type') == 'sponsored_brands' else ('sku', 'asin')
        evidence = []
        for field in fields:
            value = normalized_sku(data.get(field, '')) if field == 'sku' else data.get(field, '')
            if matches[field].get(value):
                evidence.append(matches[field][value])
        # Every row needs evidence; conflicting identifiers or mixed-store files
        # remain unresolved, even if most rows point to one store.
        if not evidence:
            return None
        candidates.intersection_update(set.intersection(*evidence))
        if not candidates:
            return None
    if len(candidates) != 1:
        return None
    store = stores[candidates.pop()]
    return store if store.is_active and can_access_store(user, store.id) else None
