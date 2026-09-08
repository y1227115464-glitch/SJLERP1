from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer

from app.core.api import DB, Page, fail, paginated, require, store_filter
from app.reports.comparison import compare
from app.reports.models import AdRecord, ReportImport, SalesRecord
from app.reports.service import batch_out, confirm_import, create_preview, get_batch

router = APIRouter(prefix='/api/v1', tags=['Amazon reports'])
Reader = Annotated[object, Depends(require('reports.view'))]
Writer = Annotated[object, Depends(require('reports.import'))]


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verification_token: str = Field(pattern=r'^[0-9a-f]{64}$')


def scope(query, model, user, store_id=None):
    if user.role != 'admin':
        query = query.where(store_filter(user, model.store_id))
    if store_id:
        query = query.where(model.store_id == store_id)
    return query


@router.post('/report-imports/preview', status_code=201)
def preview(db: DB, user: Writer, request: Request, file: UploadFile = File(), kind: Literal['sales', 'ads'] = Form(), store_id: str = Form()):
    return create_preview(db, user, file, kind, store_id, request.app.state.settings)


@router.get('/report-imports')
def batches(db: DB, user: Reader, page: Page, store_id: str | None = None, kind: Literal['sales', 'ads'] | None = None):
    query = scope(select(ReportImport), ReportImport, user, store_id)
    if kind:
        query = query.where(ReportImport.kind == kind)
    query = query.options(defer(ReportImport.parsed_rows), defer(ReportImport.errors)).order_by(ReportImport.created_at.desc(), ReportImport.id.desc())
    return paginated(db, query, page, batch_out)


@router.get('/report-imports/{identifier}')
def batch_detail(identifier: str, db: DB, user: Reader):
    batch = get_batch(db, user, identifier)
    return batch_out(batch, compare(db, batch) if batch.result is None else None) | {'can_confirm': user.id == batch.owner_id}


@router.get('/report-imports/{identifier}/rows')
def batch_rows(identifier: str, db: DB, user: Reader, page: Page, action: Literal['create', 'update', 'skip', 'conflict', 'error'] | None = None):
    batch = get_batch(db, user, identifier)
    if batch.result is not None:
        rows = [{'row': row['row'], 'action': 'source', 'data': row['data'], 'message': '该批次来源数据，确认结果见批次摘要'} for row in batch.parsed_rows]
    else:
        rows = [{key: row[key] for key in ['row', 'action', 'message', 'data']} for row in compare(db, batch)['rows']]
    rows += [{'row': error['row'], 'action': 'error', 'data': None, 'message': error['message']} for error in batch.errors]
    rows.sort(key=lambda row: row['row'])
    if action:
        rows = [row for row in rows if row['action'] == action]
    return {'items': rows[page.offset:page.offset + page.limit], 'total': len(rows)}


@router.post('/report-imports/{identifier}/confirm')
def confirm(identifier: str, payload: Confirmation, db: DB, user: Writer):
    return confirm_import(db, user, identifier, payload.verification_token)


def records_query(model, user, store_id, start_date, end_date, q):
    query = scope(select(model), model, user, store_id)
    if start_date and end_date and start_date > end_date:
        fail(422, 'invalid_period', '开始日期不能晚于结束日期')
    if model is SalesRecord:
        if start_date:
            query = query.where(model.purchase_date >= datetime.combine(start_date, time.min, timezone.utc))
        if end_date:
            if end_date == date.max:
                fail(422, 'invalid_period', '结束日期超出范围')
            query = query.where(model.purchase_date < datetime.combine(end_date + timedelta(days=1), time.min, timezone.utc))
        columns = [model.amazon_order_id, model.sku, model.asin, model.product_name]
    else:
        if start_date:
            query = query.where(model.start_date >= start_date)
        if end_date:
            query = query.where(model.end_date <= end_date)
        columns = [model.campaign, model.ad_group, model.sku, model.asin]
    if q:
        if len(q) > 200:
            fail(422, 'invalid_query', '搜索内容过长')
        query = query.where(or_(*(col.icontains(q, autoescape=True) for col in columns)))
    return query


def record_out(record):
    result = {'id': record.id, 'store_id': record.store_id, 'store_name': record.store.name,
            'import_id': record.import_id, 'source_row': record.source_row, **record.data}
    if isinstance(record, AdRecord):
        result['report_date'] = record.report_date.isoformat() if record.report_date else None
    return result


@router.get('/sales-records')
def sales(db: DB, user: Reader, page: Page, store_id: str | None = None, start_date: date | None = None,
          end_date: date | None = None, q: str = '', status: str = ''):
    query = records_query(SalesRecord, user, store_id, start_date, end_date, q)
    if status:
        query = query.where(SalesRecord.order_status == status)
    return paginated(db, query.order_by(SalesRecord.purchase_date.desc(), SalesRecord.id), page, record_out)


@router.get('/ad-records')
def ads(db: DB, user: Reader, page: Page, store_id: str | None = None, start_date: date | None = None,
        end_date: date | None = None, q: str = '', granularity: Literal['daily', 'period'] = 'daily'):
    query = records_query(AdRecord, user, store_id, start_date, end_date, q)
    query = query.where(AdRecord.report_date.is_not(None) if granularity == 'daily' else AdRecord.report_date.is_(None))
    return paginated(db, query.order_by(AdRecord.start_date.desc(), AdRecord.id), page, record_out)


@router.get('/sales-records/summary')
def sales_summary(db: DB, user: Reader, store_id: str | None = None, start_date: date | None = None,
                  end_date: date | None = None, q: str = '', status: str = ''):
    query = records_query(SalesRecord, user, store_id, start_date, end_date, q)
    if status:
        query = query.where(SalesRecord.order_status == status)
    source = query.subquery()
    result = db.execute(select(source.c.currency, source.c.order_status, source.c.item_status, func.count(),
        func.sum(source.c.quantity), func.sum(source.c.net_amount), func.count(source.c.net_amount))
        .group_by(source.c.currency, source.c.order_status, source.c.item_status))
    return {'groups': [{'currency': currency, 'order_status': status, 'item_status': item_status, 'rows': rows,
        'quantity': int(quantity), 'net_amount': format(amount, '.4f') if amount is not None else None,
        'missing_amount_rows': rows - amounts} for currency, status, item_status, rows, quantity, amount, amounts in result]}


def ratio(numerator, denominator):
    return format(Decimal(numerator) / Decimal(denominator), '.6f') if denominator else None


@router.get('/ad-records/summary')
def ad_summary(db: DB, user: Reader, store_id: str | None = None, start_date: date | None = None,
               end_date: date | None = None, q: str = '', granularity: Literal['daily', 'period'] = 'daily'):
    query = records_query(AdRecord, user, store_id, start_date, end_date, q)
    source = query.where(AdRecord.report_date.is_not(None) if granularity == 'daily' else AdRecord.report_date.is_(None)).subquery()
    fields = ['impressions', 'clicks', 'spend', 'attributed_sales', 'orders', 'units']
    result = db.execute(select(source.c.currency, func.count(), *(func.sum(source.c[field]) for field in fields)).group_by(source.c.currency))
    groups = []
    for currency, count, impressions, clicks, spend, sales, orders, units in result:
        groups.append({'currency': currency, 'rows': count, 'impressions': int(impressions), 'clicks': int(clicks),
            'spend': format(spend, '.4f'), 'attributed_sales': format(sales, '.4f'), 'orders': int(orders), 'units': int(units),
            'ctr': ratio(clicks, impressions), 'cpc': ratio(spend, clicks), 'acos': ratio(spend, sales), 'roas': ratio(sales, spend)})
    return {'groups': groups}
