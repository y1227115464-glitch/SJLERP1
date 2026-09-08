import csv
import io
import zipfile
from xml.sax.saxutils import escape

import pytest


SALES_HEADERS = ['amazon-order-id', 'purchase-date', 'last-updated-date', 'order-status', 'fulfillment-channel',
                 'sales-channel', 'product-name', 'sku', 'asin', 'item-status', 'quantity', 'currency', 'item-price']
AD_HEADERS = ['开始日期', '结束日期', '广告组合名称', '货币', '广告活动名称', '广告组名称', '零售商', '国家/地区',
              '广告SKU', '广告ASIN', '展示量', '点击量', '点击率 (CTR)', '单次点击成本 (CPC)', '花费', '7天总销售额',
              '广告投入产出比 (ACOS) 总计', '总广告投资回报率 (ROAS)', '7天总订单数(#)', '7天总销售量(#)',
              '7天的转化率', '7天内广告SKU销售量(#)', '7天内其他SKU销售量(#)', '7天内广告SKU销售额', '7天内其他SKU销售额']


def sale(**changes):
    return {'amazon-order-id': '111-1234567-1234567', 'purchase-date': '2025-09-26T07:00:21+00:00',
            'last-updated-date': '2025-09-27T08:00:00+00:00', 'order-status': 'Shipped', 'fulfillment-channel': 'Amazon',
            'sales-channel': 'Amazon.com', 'product-name': '测试商品', 'sku': 'SKU-A', 'asin': 'B012345678',
            'item-status': 'Shipped', 'quantity': '2', 'currency': 'USD', 'item-price': '19.98', **changes}


def sales_file(rows):
    out = io.StringIO()
    columns = list(dict.fromkeys(SALES_HEADERS + [key for row in rows for key in row]))
    writer = csv.DictWriter(out, fieldnames=columns, delimiter='\t')
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')


def ad(**changes):
    return dict(zip(AD_HEADERS, ['2026-06-01', '2026-06-30', '组合', 'USD', '活动', '组', 'Amazon', '美国',
        'SKU-A', 'B012345678', 1000, 10, .01, .3, 3.000000000000004, 20.00, .15, 6.666666, 2, 3, .2, 2, 1, 15, 5])) | changes


def ads_file(rows, formula=False, headers=None):
    # Minimal source fixture intentionally has Amazon's incorrect A1 dimension.
    headers = headers or AD_HEADERS
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="广告报告" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1"/><sheetData>'
        for i, values in enumerate([headers] + [[r.get(k, '') for k in headers] for r in rows], 1):
            xml += f'<row r="{i}">'
            for j, value in enumerate(values):
                col = chr(65+j)
                if formula and i == 2 and headers[j] == '花费':
                    xml += f'<c r="{col}{i}"><f>1+2</f><v>3</v></c>'
                elif isinstance(value, (int, float)):
                    xml += f'<c r="{col}{i}"><v>{value}</v></c>'
                else:
                    xml += f'<c r="{col}{i}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
            xml += '</row>'
        z.writestr('xl/worksheets/sheet1.xml', xml + '</sheetData></worksheet>')
    return output.getvalue()


def test_sales_parser_preserves_line_amount_and_deduplicates():
    from app.reports.parsers import parse_report
    result = parse_report('sales', sales_file([sale(), sale()]))
    assert len(result['rows']) == 1
    assert result['duplicate_count'] == 1
    assert result['rows'][0]['data']['net_amount'] == '19.9800'
    assert result['rows'][0]['data']['quantity'] == 2


def test_sales_invalid_conflicting_keys_and_cancelled_blank_amount():
    from app.reports.parsers import parse_report
    assert parse_report('sales', sales_file([sale(), sale(quantity='3')]))['errors']
    assert parse_report('sales', sales_file([sale(quantity='-1')]))['errors']
    assert parse_report('sales', sales_file([sale(**{'purchase-date': '2025-01-01'})]))['errors']
    row = parse_report('sales', sales_file([sale(currency='', **{'order-status': 'Cancelled', 'item-status': 'Cancelled', 'item-price': ''})]))['rows'][0]
    assert row['data']['currency'] is None and row['data']['net_amount'] is None


def test_ad_parser_reads_beyond_bad_dimension_and_normalizes_money():
    from app.reports.parsers import parse_report
    result = parse_report('ads', ads_file([ad(), ad(广告SKU='SKU-B')]))
    assert len(result['rows']) == 2 and not result['errors']
    assert result['rows'][0]['data']['spend'] == '3.0000'
    assert result['rows'][0]['data']['end_date'] == '2026-06-30'
    assert parse_report('ads', ads_file([ad()], formula=True))['errors']


def test_parser_encoding_headers_bad_files_and_nonfinite_values():
    from fastapi import HTTPException
    from app.reports.parsers import parse_report
    utf16 = sales_file([sale()]).decode('utf-8-sig').encode('utf-16')
    assert len(parse_report('sales', utf16)['rows']) == 1
    for content, kind in [(b'', 'sales'), (b'not-a-report', 'sales'), (b'not-a-zip', 'ads')]:
        with pytest.raises(HTTPException) as error:
            parse_report(kind, content)
        assert error.value.status_code == 422
    assert parse_report('sales', sales_file([sale(**{'item-price': 'NaN'})]))['errors']
    assert parse_report('ads', ads_file([ad(点击量=1.5)]))['errors']
    assert parse_report('ads', ads_file([ad(开始日期='2026-07-01')]))['errors']


def test_xlsx_invalid_shared_string_index_is_validation_error():
    from fastapi import HTTPException
    from app.reports.parsers import parse_report
    import re
    source = io.BytesIO(ads_file([ad()]))
    altered = io.BytesIO()
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(altered, 'w') as zout:
        for name in zin.namelist():
            value = zin.read(name)
            if name.endswith('sheet1.xml'):
                value = re.sub(rb'<c r="A2".*?</c>', b'<c r="A2" t="s"><v>99999</v></c>', value)
            zout.writestr(name, value)
    with pytest.raises(HTTPException) as error:
        parse_report('ads', altered.getvalue())
    assert error.value.status_code == 422
