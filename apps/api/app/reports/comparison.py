from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select

from app.core.security import aware
from app.reports.models import AdRecord, SalesRecord
from app.reports.parsers import AD_PARSER_VERSION, fingerprint


def chunks(values, size=300):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def overlapping_keys(intervals):
    conflicts = set()
    for entries in intervals.values():
        latest_end, latest_key = '', ''
        for key, start, end in sorted(set(entries), key=lambda item: (item[1], item[2], item[0])):
            if start <= latest_end:
                conflicts.update([key, latest_key])
            if end > latest_end:
                latest_end, latest_key = end, key
    return conflicts


def compare(db, batch):
    model = SalesRecord if batch.kind == 'sales' else AdRecord
    existing, intervals = {}, defaultdict(list)
    for keys in chunks(row['key'] for row in batch.parsed_rows):
        columns = [model.id, model.natural_key, model.value_hash, model.import_id]
        columns.append(SalesRecord.last_updated_date if batch.kind == 'sales' else AdRecord.latest_report_at)
        existing.update({row.natural_key: row for row in db.execute(select(*columns).where(model.store_id == batch.store_id, model.natural_key.in_(keys)))})
    if batch.kind == 'ads' and batch.parsed_rows:
        periods = [row for row in batch.parsed_rows if not row['data'].get('report_date')]
        lower = min((row['data']['start_date'] for row in periods), default='')
        upper = max((row['data']['end_date'] for row in periods), default='')
        for keys in chunks({row['identity'] for row in periods}):
            query = select(AdRecord.identity_key, AdRecord.natural_key, AdRecord.start_date, AdRecord.end_date).where(
                AdRecord.store_id == batch.store_id, AdRecord.identity_key.in_(keys), AdRecord.report_date.is_(None),
                AdRecord.start_date <= date.fromisoformat(upper), AdRecord.end_date >= date.fromisoformat(lower))
            for identity, key, start, end in db.execute(query):
                intervals[identity].append((key, start.isoformat(), end.isoformat()))
        for row in periods:
            intervals[row['identity']].append((row['key'], row['data']['start_date'], row['data']['end_date']))
    overlaps = overlapping_keys(intervals)
    results, counts, signature = [], dict.fromkeys(['create', 'update', 'skip', 'conflict'], 0), []
    for row in batch.parsed_rows:
        old = existing.get(row['key'])
        action, message = 'create', '新增记录'
        data = row['data']
        if batch.kind == 'ads' and batch.parser_version != AD_PARSER_VERSION:
            action, message = 'conflict', '广告去重规则已更新，请重新上传文件后确认'
        elif row['key'] in overlaps:
            action, message = 'conflict', '与同一广告商品的已有或本批统计区间重叠，请使用一致的日期粒度'
        elif old:
            if old.value_hash == row['hash']:
                action, message = 'skip', '该记录已存在且内容相同'
            elif batch.kind == 'sales':
                incoming = datetime.fromisoformat(data['last_updated_date'])
                previous = aware(old.last_updated_date)
                if incoming > previous:
                    action, message = 'update', '来源更新时间更新，替换原订单明细'
                elif incoming < previous:
                    action, message = 'skip', '来源版本较旧，保留现有较新订单'
                else:
                    action, message = 'conflict', '同一订单明细的更新时间相同但内容不同，请核对来源'
            elif aware(old.latest_report_at) > aware(batch.created_at):
                action, message = 'conflict', '已有更晚上传并确认的广告版本，请重新上传最新报告'
            else:
                action, message = 'update', ('同一天的 SKU、广告活动和广告组相同，新导入覆盖原记录' if data.get('report_date')
                                             else '相同广告商品和统计区间，替换指标而非累加')
        counts[action] += 1
        watermark = aware(old.latest_report_at) if old and batch.kind == 'ads' else None
        signature.append([row['key'], row['hash'], action, old.value_hash if old else '', old.import_id if old else '', watermark.isoformat() if watermark else ''])
        results.append({'row': row['row'], 'key': row['key'], 'existing_id': old.id if old else None,
                        'advance_watermark': bool(watermark and aware(batch.created_at) > watermark),
                        'action': action, 'message': message, 'data': data})
    return {'rows': results, 'counts': counts, 'verification_token': fingerprint([batch.id, signature, batch.errors])}
