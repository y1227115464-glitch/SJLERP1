"""Resolve current campaign products for display without rewriting source facts."""
from collections import defaultdict

from sqlalchemy import select, tuple_

from app.models import Product
from app.reports.comparison import chunks
from app.reports.models import BrandAdAllocation, SalesRecord
from app.reports.sku import sku_column


def with_ad_products(db, rows):
    # Call only after the source rows have passed report/store authorization.
    keys = {(row['store_id'], row['campaign']) for row in rows if row.get('ad_type') == 'sponsored_brands'}
    if not keys:
        return rows
    mappings = {(item.store_id, item.campaign): item.allocations for group in chunks(keys) for item in db.scalars(
        select(BrandAdAllocation).where(tuple_(BrandAdAllocation.store_id, BrandAdAllocation.campaign).in_(group)))}
    skus = {item['sku'] for items in mappings.values() for item in items}
    products = {item.internal_sku: item for group in chunks(skus) for item in db.scalars(
        select(Product).where(Product.internal_sku.in_(group)))}
    sales_asins = defaultdict(set)
    targets = {(store, item['sku']) for (store, _), items in mappings.items() for item in items
               if item['sku'] not in products or not products[item['sku']].asin}
    for group in chunks(targets):
        canonical = sku_column(SalesRecord.sku)
        for store, sku, asin in db.execute(select(SalesRecord.store_id, canonical, SalesRecord.asin).where(
                tuple_(SalesRecord.store_id, canonical).in_(group), SalesRecord.asin != '').distinct()):
            sales_asins[(store, sku)].add(asin)
    result = []
    for row in rows:
        if row.get('ad_type') != 'sponsored_brands':
            result.append(row)
            continue
        items = []
        for item in mappings.get((row['store_id'], row['campaign']), []):
            product = products.get(item['sku'])
            asins = [product.asin] if product and product.asin else sorted(sales_asins[(row['store_id'], item['sku'])])
            items.append({**item, 'name': product.name if product else '', 'asins': asins})
        result.append({**row, 'allocation_products': items})
    return result
