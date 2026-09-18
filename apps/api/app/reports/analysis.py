"""SKU profit estimates from imported order lines and daily advertising facts."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import Query
from sqlalchemy import Numeric, cast, func, select, union

from app.core.api import DB, Page
from app.models import Store
from app.reports.costs import Reader, router, visible_rates
from app.reports.fba import FBA_PRICE_THRESHOLD, applicable, visible_fba_rates
from app.reports.models import AdRecord, BrandAdAllocation, SalesRecord
from app.reports.routes import records_query, scope
from app.reports.sku import normalized_sku, sku_column

ZERO = Decimal(0)
MONEY_FIELDS = ['product_cost', 'fba_fee', 'commission', 'sales_profit', 'sales', 'ad_spend', 'actual_profit']
CURRENCIES = ['USD', 'CAD', 'MXN']


def money(value):
    return None if value is None else Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def rate(numerator, denominator):
    if numerator is None or denominator is None:
        return None
    return numerator / denominator if denominator else ZERO


def output(row):
    return {key: (format(value, '.6f' if key.endswith('_rate') else '.2f') if isinstance(value, Decimal) else
        sorted(value) if isinstance(value, set) else value) for key, value in row.items() if not key.startswith('_')}


def queries(user, store_id, start_date, end_date, order_scope):
    sales = records_query(SalesRecord, user, store_id, start_date, end_date, '')
    ads = records_query(AdRecord, user, store_id, start_date, end_date, '').where(AdRecord.report_date.is_not(None))
    sales = sales.where(~SalesRecord.order_status.in_(['Cancelled', 'Canceled']),
        ~SalesRecord.item_status.in_(['Cancelled', 'Canceled']))
    if order_scope == 'shipped':
        sales = sales.where(SalesRecord.item_status == 'Shipped', SalesRecord.order_status.in_(['Shipped', 'Partially Shipped']))
    return sales, ads


def calculate(db, user, store_id=None, start_date=None, end_date=None, q='', sku='', order_scope='shipped',
              cad_per_usd=Decimal('1.36'), mxn_per_usd=Decimal('17.66')):
    sales_query, ad_query = queries(user, store_id, start_date, end_date, order_scope)
    divisors = {'USD': Decimal(1), 'CAD': cad_per_usd, 'MXN': mxn_per_usd}
    # Use explicit report assumptions, not a live or implicit exchange rate.
    excluded_sales = db.scalar(select(func.count()).select_from(sales_query.where(
        (~SalesRecord.currency.in_(CURRENCIES)) | SalesRecord.currency.is_(None)).subquery()))
    excluded_ads = db.scalar(select(func.count()).select_from(ad_query.where(~AdRecord.currency.in_(CURRENCIES)).subquery()))
    ad_stores = set(db.scalars(ad_query.where(AdRecord.currency.in_(CURRENCIES)).with_only_columns(AdRecord.store_id).distinct()))
    source_sales = sales_query.where(SalesRecord.currency.in_(CURRENCIES))
    source_ads = ad_query.where(AdRecord.currency.in_(CURRENCIES), AdRecord.ad_type == 'sponsored_products')
    for model, query in [(SalesRecord, source_sales), (AdRecord, source_ads)]:
        if q:
            query = query.where(sku_column(model.sku).icontains(normalized_sku(q), autoescape=True))
        if sku:
            query = query.where(sku_column(model.sku) == normalized_sku(sku))
        if model is SalesRecord:
            source_sales = query
        else:
            source_ads = query
    rows = {}
    def row_for(store, seller_sku):
        canonical = normalized_sku(seller_sku)
        key = (store, canonical)
        if key not in rows:
            rows[key] = {'store_id': store, 'sku': canonical, 'quantity': 0, 'sales_rows': 0, 'ad_rows': 0,
                **{field: ZERO for field in MONEY_FIELDS}, 'issues': set(), 'source_skus': set(), '_sources': set()}
        rows[key]['source_skus'].add(seller_sku)
        return rows[key]

    rates = defaultdict(list)
    for cost in db.scalars(visible_rates(user, store_id)):
        rates[(cost.scope_key, cost.sku)].append(cost)
    for values in rates.values():
        values.sort(key=lambda cost: cost.effective_from, reverse=True)
    def cost_on(store, seller_sku, day):
        for scope in [store, '*']:
            for cost in rates[(scope, normalized_sku(seller_sku))]:
                if cost.effective_from <= day:
                    return cost
        return None

    fba_rates = defaultdict(list)
    for fee in db.scalars(visible_fba_rates(user, store_id)):
        fba_rates[fee.sku].append(fee)

    s = source_sales.subquery()
    day = func.date(func.timezone('UTC', s.c.purchase_date)) if db.bind.dialect.name == 'postgresql' else func.date(s.c.purchase_date)
    price = cast(s.c.data['item_price'].as_string(), Numeric(20, 4))
    discount = func.coalesce(cast(s.c.data['item_promotion_discount'].as_string(), Numeric(20, 4)), 0)
    groups = db.execute(select(s.c.store_id, s.c.sku, day, s.c.currency, func.sum(s.c.quantity), func.sum(price - discount),
        func.count(), func.count(price), price, s.c.quantity).group_by(s.c.store_id, s.c.sku, day, s.c.currency, price, s.c.quantity))
    for store, seller_sku, source_day, currency, quantity, sales, count, amount_count, line_price, line_quantity in groups:
        sales = sales / divisors[currency] if sales is not None else None
        row = row_for(store, seller_sku)
        quantity = int(quantity)
        row['quantity'] += quantity
        row['sales_rows'] += count
        source_day = date.fromisoformat(source_day) if isinstance(source_day, str) else source_day
        cost = cost_on(store, seller_sku, source_day)
        fee = applicable(fba_rates[seller_sku], store, source_day)
        if count != amount_count:
            row['issues'].add('缺少销售金额')
            row['sales'] = row['commission'] = None
        if row['sales'] is not None:
            row['sales'] += sales or ZERO
            row['commission'] += (sales or ZERO) * (cost.commission_rate if cost else Decimal('.15'))
        for field in ['product_cost', 'fba_fee']:
            unit = None
            if cost:
                unit = cost.fba_fee if field == 'fba_fee' else (
                    cost.product_cost + cost.inbound_fee if cost.product_cost is not None and cost.inbound_fee is not None else None)
            if field == 'fba_fee' and fee:
                # Compare unrounded, pre-discount unit price in USD. Group by source
                # line price/quantity so same-day mixed price tiers never get averaged.
                unit = (fee.low_price_fee if line_price <= FBA_PRICE_THRESHOLD * line_quantity * divisors[currency]
                    else fee.high_price_fee) if line_price is not None and line_quantity > 0 else None
                if quantity and line_price is None:
                    row['issues'].add('缺少商品金额，无法判断物流费档位')
            if quantity and unit is None:
                row[field] = None
                if field == 'fba_fee':
                    row['issues'].add('缺少 FBA 派送费')
                else:
                    if cost is None or cost.product_cost is None:
                        row['issues'].add('缺少产品成本及头程')
                    if cost is None or cost.inbound_fee is None:
                        row['issues'].add('入库配置费待确认')
            elif row[field] is not None:
                row[field] += quantity * (unit or ZERO)
        if cost:
            row['_sources'].add(cost.id)
        if fee and quantity:
            row['_sources'].add(fee.id)

    a = source_ads.subquery()
    for store, seller_sku, currency, spend, count in db.execute(select(a.c.store_id, a.c.sku, a.c.currency, func.sum(a.c.spend),
            func.count()).group_by(a.c.store_id, a.c.sku, a.c.currency)):
        row = row_for(store, seller_sku)
        row['ad_spend'] += spend / divisors[currency]
        row['ad_rows'] += count
    mappings = {(item.store_id, item.campaign): item.allocations for item in db.scalars(
        scope(select(BrandAdAllocation).where(BrandAdAllocation.is_deleted.is_(False)), BrandAdAllocation, user, store_id))}
    brand = ad_query.where(AdRecord.currency.in_(CURRENCIES), AdRecord.ad_type == 'sponsored_brands').subquery()
    pending = []
    for store, campaign, currency, spend, count in db.execute(select(brand.c.store_id, brand.c.campaign,
            brand.c.currency, func.sum(brand.c.spend), func.count()).group_by(brand.c.store_id, brand.c.campaign, brand.c.currency)):
        allocations = mappings.get((store, campaign))
        if not allocations:
            pending.append({'store_id': store, 'campaign': campaign, 'currency': currency, 'spend': format(spend, '.4f')})
            continue
        # Allocate whole cents with the largest remainder method before filtering SKUs.
        # This keeps allocations equal to campaign spend and filtered results stable.
        cents = int(money(spend / divisors[currency]) * 100)
        parts = [(item['sku'], Decimal(cents) * Decimal(item['percentage']) / 100) for item in allocations]
        amounts = {seller_sku: int(value) for seller_sku, value in parts}
        remainder = cents - sum(amounts.values())
        for seller_sku, _ in sorted(parts, key=lambda part: (-(part[1] % 1), part[0]))[:remainder]:
            amounts[seller_sku] += 1
        for seller_sku, allocated in amounts.items():
            if (q and normalized_sku(q) not in seller_sku) or (sku and normalized_sku(sku) != seller_sku):
                continue
            row = row_for(store, seller_sku)
            row['ad_spend'] += Decimal(allocated) / 100
            row['ad_rows'] += count
    pending_stores = {item['store_id'] for item in pending}
    names = dict(db.execute(select(Store.id, Store.name)).all())
    for row in rows.values():
        row['store_name'] = names[row['store_id']]
        row['key'] = row['store_id'] + ':' + row['sku']
        if row['store_id'] not in ad_stores:
            row['ad_spend'] = None
            row['issues'].add('所选期间未导入广告日报')
        if row['store_id'] in pending_stores:
            row['ad_spend'] = None
            row['issues'].add('该店铺存在未配置商品分摊的品牌广告，请到广告数据维护')
        for field in ['product_cost', 'fba_fee', 'commission', 'sales', 'ad_spend']:
            row[field] = money(row[field])
        row['sales_profit'] = (row['sales'] - row['product_cost'] - row['fba_fee'] - row['commission']
            if all(row[field] is not None for field in ['sales', 'product_cost', 'fba_fee', 'commission']) else None)
        row['actual_profit'] = (row['sales_profit'] - row['ad_spend']
            if row['sales_profit'] is not None and row['ad_spend'] is not None else None)
        row['sales_profit_rate'] = rate(row['sales_profit'], row['sales'])
        row['actual_profit_rate'] = rate(row['actual_profit'], row['sales'])
        row['cost_versions'] = len(row['_sources'])
    values = list(rows.values())
    total = {'sku': '合计', 'quantity': sum(row['quantity'] for row in values)}
    for field in MONEY_FIELDS:
        total[field] = sum((row[field] for row in values), ZERO) if all(row[field] is not None for row in values) else None
    total['sales_profit_rate'] = rate(total['sales_profit'], total['sales'])
    total['actual_profit_rate'] = rate(total['actual_profit'], total['sales'])
    total['incomplete_rows'] = sum(bool(row['issues']) for row in values)
    if pending:
        total['ad_spend'] = total['actual_profit'] = total['actual_profit_rate'] = None
    return values, output(total), {'unsupported_sales_rows': excluded_sales, 'unsupported_ad_rows': excluded_ads,
        'unallocated_brand_campaigns': pending}


@router.get('/suggestions')
def suggestions(db: DB, user: Reader, store_id: str | None = None, start_date: date | None = None,
                end_date: date | None = None, order_scope: Literal['shipped', 'non_cancelled'] = 'shipped',
                q: str = Query('', max_length=200), limit: int = Query(50, ge=1, le=100)):
    sales, ads = queries(user, store_id, start_date, end_date, order_scope)
    source = union(sales.with_only_columns(sku_column(SalesRecord.sku).label('sku')).where(SalesRecord.currency.in_(CURRENCIES)),
        ads.with_only_columns(sku_column(AdRecord.sku).label('sku')).where(AdRecord.currency.in_(CURRENCIES))).subquery()
    query = select(source.c.sku).where(source.c.sku != '', source.c.sku.icontains(normalized_sku(q.strip()), autoescape=True)).order_by(source.c.sku)
    values = set(db.scalars(query.limit(limit + 1)).all())
    campaigns = ads.where(AdRecord.ad_type == 'sponsored_brands', AdRecord.currency.in_(CURRENCIES)).with_only_columns(
        AdRecord.store_id, AdRecord.campaign).distinct().subquery()
    mappings = db.scalars(select(BrandAdAllocation).where(BrandAdAllocation.is_deleted.is_(False)).join(campaigns,
        (campaigns.c.store_id == BrandAdAllocation.store_id) & (campaigns.c.campaign == BrandAdAllocation.campaign)))
    values.update(item['sku'] for mapping in mappings for item in mapping.allocations if normalized_sku(q.strip()) in item['sku'])
    values = sorted(values)
    return {'items': values[:limit], 'has_more': len(values) > limit}


@router.get('')
def analysis(db: DB, user: Reader, page: Page, store_id: str | None = None,
             start_date: date | None = None, end_date: date | None = None,
             q: str = Query('', max_length=200), sku: str = Query('', max_length=120),
             order_scope: Literal['shipped', 'non_cancelled'] = 'shipped',
             cad_per_usd: Decimal = Query(Decimal('1.36'), ge=Decimal('.000001'), le=100000),
             mxn_per_usd: Decimal = Query(Decimal('17.66'), ge=Decimal('.000001'), le=100000),
             sort_by: Literal['sku', 'quantity', 'sales', 'actual_profit', 'actual_profit_rate', 'ad_spend'] = 'sales',
             descending: bool = True):
    values, totals, excluded = calculate(db, user, store_id, start_date, end_date, q, sku, order_scope, cad_per_usd, mxn_per_usd)
    values.sort(key=lambda row: (row['sku'], row['store_id']))
    # Missing figures always stay at the end, for either sort direction.
    known = [row for row in values if row[sort_by] is not None]
    unknown = [row for row in values if row[sort_by] is None]
    known.sort(key=lambda row: row[sort_by], reverse=descending)
    values = known + unknown
    return {'items': [output(row) for row in values[page.offset:page.offset + page.limit]],
        'total': len(values), 'totals': totals, 'excluded': excluded, 'currency': 'USD',
        'exchange_rates': {'cad_per_usd': str(cad_per_usd), 'mxn_per_usd': str(mxn_per_usd)}}
