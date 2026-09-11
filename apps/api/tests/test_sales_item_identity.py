from decimal import Decimal

from sqlalchemy import select

from app.reports.models import ReportImport, SalesRecord
from app.reports.parsers import fingerprint, sales_legacy_key
from test_report_parsers import sale, sales_file
from test_reports import confirm, preview


def legacy_import(system, rows):
    """Simulate v1's ignored IDs and collapsed rows, retaining the original archive."""
    p, h = preview(system, sales_file(rows))
    assert confirm(system['client'], p, h).status_code == 200
    with system['app'].state.database.session() as db:
        records = list(db.scalars(select(SalesRecord)))
        seen = set()
        for record in records:
            data = {k: v for k, v in record.data.items() if k != 'order_item_id'}
            key = sales_legacy_key(data)
            if key in seen:
                db.delete(record)
                continue
            seen.add(key)
            record.data, record.natural_key, record.value_hash = data, key, fingerprint(data)
        batch = db.get(ReportImport, p['id'])
        batch.parser_version = 'amazon-v1'
        db.commit()
    return p, h


def facts(system):
    with system['app'].state.database.session() as db:
        return list(db.scalars(select(SalesRecord).order_by(SalesRecord.source_row)))


def test_split_items_import_repeat_and_update_independently(system):
    rows = [sale(quantity='3', **{'order-item-id': '001', 'item-price': '26.97'}),
            sale(quantity='1', **{'order-item-id': '002', 'item-price': '8.99'}),
            sale(quantity='0', currency='', **{'order-item-id': '003', 'item-status': 'Cancelled', 'item-price': ''})]
    c = system['client']
    p, h = preview(system, sales_file(rows))
    assert p['error_count'] == 0 and p['counts']['create'] == 3
    assert confirm(c, p, h).status_code == 200
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts']['skip'] == 3 and confirm(c, p, h).status_code == 200
    records = facts(system)
    assert sum(r.quantity for r in records) == 4
    assert sum((r.net_amount or 0 for r in records), Decimal(0)) == Decimal('35.96')
    changed = dict(rows[1], **{'last-updated-date': '2025-09-28T08:00:00Z', 'item-price': '7.99'})
    p, _ = preview(system, sales_file([changed]), headers=h)
    assert p['counts']['update'] == 1 and confirm(c, p, h).status_code == 200
    assert len(facts(system)) == 3
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts']['skip'] == 3
    p, _ = preview(system, sales_file([dict(changed, quantity='2')]), headers=h)
    assert p['counts']['conflict'] == 1 and confirm(c, p, h).status_code == 409


def test_legacy_source_recovers_identical_split_ids_without_double_count(system):
    rows = [sale(**{'order-item-id': '001'}), sale(**{'order-item-id': '002'})]
    old, h = legacy_import(system, rows)
    old_id = facts(system)[0].id
    c = system['client']
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts'] == {'create': 1, 'update': 0, 'skip': 1, 'conflict': 0}
    assert len(facts(system)) == 1 and 'order_item_id' not in facts(system)[0].data
    assert confirm(c, p, h).status_code == 200
    records = facts(system)
    assert len(records) == 2 and sum(r.quantity for r in records) == 4
    migrated = next(r for r in records if r.id == old_id)
    assert migrated.import_id == old['id']  # Identity-only repair keeps provenance.
    assert {r.data['order_item_id'] for r in records} == {'001', '002'}
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts']['skip'] == 2 and confirm(c, p, h).status_code == 200


def test_recovered_legacy_newer_fact_is_not_downgraded(system):
    current = sale(**{'order-item-id': '001', 'last-updated-date': '2025-09-28T08:00:00Z', 'item-price': '7.99'})
    old, h = legacy_import(system, [current])
    p, _ = preview(system, sales_file([sale(**{'order-item-id': '001'})]), headers=h)
    assert p['counts']['skip'] == 1
    assert confirm(system['client'], p, h).status_code == 200
    record = facts(system)[0]
    assert record.data['order_item_id'] == '001' and record.net_amount == Decimal('7.99')
    assert record.import_id == old['id']


def test_recovered_legacy_updates_and_other_item_can_arrive_first(system):
    first = sale(**{'order-item-id': '001'})
    _, h = legacy_import(system, [first])
    second = sale(**{'order-item-id': '002'})
    p, _ = preview(system, sales_file([second]), headers=h)
    assert p['counts']['create'] == 1 and confirm(system['client'], p, h).status_code == 200
    changed = dict(first, quantity='3', **{'last-updated-date': '2025-09-28T08:00:00Z'})
    p, _ = preview(system, sales_file([changed, second]), headers=h)
    assert p['counts']['update'] == 1 and p['counts']['skip'] == 1
    assert confirm(system['client'], p, h).status_code == 200
    assert len(facts(system)) == 2 and sum(r.quantity for r in facts(system)) == 5


def test_legacy_exact_match_without_ids_can_upgrade_but_ambiguity_blocks(system):
    old, h = legacy_import(system, [sale()])
    rows = [sale(**{'order-item-id': '001'}), sale(**{'order-item-id': '002'})]
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts']['conflict'] == 2
    assert confirm(system['client'], p, h).status_code == 409 and len(facts(system)) == 1
    p, _ = preview(system, sales_file(rows[:1]), headers=h)
    assert p['counts']['skip'] == 1 and confirm(system['client'], p, h).status_code == 200
    assert len(facts(system)) == 1 and facts(system)[0].data['order_item_id'] == '001'
    p, _ = preview(system, sales_file([sale()]), headers=h)
    assert p['counts']['conflict'] == 1 and confirm(system['client'], p, h).status_code == 409


def test_missing_or_tampered_archive_does_not_guess_identical_splits(system):
    rows = [sale(**{'order-item-id': '001'}), sale(**{'order-item-id': '002'})]
    old, h = legacy_import(system, rows)
    with system['app'].state.database.session() as db:
        storage_key = db.get(ReportImport, old['id']).storage_key
    path = system['settings'].storage_path / storage_key
    path.write_bytes(sales_file([sale(**{'order-item-id': '999'})]))
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts']['conflict'] == 2
    path.unlink()
    p, _ = preview(system, sales_file(rows), headers=h)
    assert p['counts']['conflict'] == 2
    assert confirm(system['client'], p, h).status_code == 409 and len(facts(system)) == 1


def test_old_pending_preview_requires_reupload(system):
    p, h = preview(system, sales_file([sale()]))
    with system['app'].state.database.session() as db:
        db.get(ReportImport, p['id']).parser_version = 'amazon-v1'
        db.commit()
    response = confirm(system['client'], p, h)
    assert response.status_code == 409 and not facts(system)


def test_concurrent_legacy_identity_upgrade_invalidates_preview(system):
    rows = [sale(**{'order-item-id': '001'})]
    _, h = legacy_import(system, rows)
    first, _ = preview(system, sales_file(rows), headers=h)
    second, _ = preview(system, sales_file(rows), headers=h)
    assert confirm(system['client'], first, h).status_code == 200
    response = confirm(system['client'], second, h)
    assert response.status_code == 409 and response.json()['error']['code'] == 'preview_changed'
    assert len(facts(system)) == 1
