import { useState } from 'react';
import { Alert, Button, Card, Descriptions, Drawer, Input, Select, Table, Tag } from 'antd';
import { ImportOutlined, ReloadOutlined } from '@ant-design/icons';
import { ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath } from './CatalogShared';
import { ReportBatchDrawer, reportMoney } from './ReportImports';
import { ReportSearch } from './ReportSearch';
import type { ReportSearchValue } from './ReportSearch';
import type { ReportData, ReportKind, SummaryGroup } from './report-types';
import type { User } from './types';

const statusLabels: Record<string, string> = { Pending: '待处理', Shipped: '已发货', Cancelled: '已取消', Unshipped: '未发货', 'Partially Shipped': '部分发货' };
const percent = (value: unknown) => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
const labels: Record<string, string> = { amazon_order_id: '亚马逊订单号', merchant_order_id: '商家订单号', sales_channel: '销售站点', sku: 'Seller SKU', asin: 'ASIN',
  product_name: '商品名称', order_status: '订单状态', item_status: '商品状态', fulfillment_channel: '配送渠道', purchase_date: '下单时间（UTC）', last_updated_date: '来源更新时间（UTC）',
  quantity: '数量', currency: '币种', item_price: '商品金额', item_tax: '商品税', shipping_price: '运费', shipping_tax: '运费税', gift_wrap_price: '礼品包装费', gift_wrap_tax: '礼品税',
  item_promotion_discount: '商品优惠', ship_promotion_discount: '运费优惠', net_amount: '不含税订单净额', report_date: '广告日期', start_date: '开始日期', end_date: '结束日期',
  portfolio: '广告组合', campaign: '广告活动', ad_group: '广告组', retailer: '零售商', country: '国家 / 地区', impressions: '展示量', clicks: '点击量', spend: '花费',
  attributed_sales: '7 天归因销售额', orders: '7 天归因订单数', units: '7 天归因销售量', advertised_units: '广告 SKU 销量', other_units: '其他 SKU 销量',
  advertised_sales: '广告 SKU 销售额', other_sales: '其他 SKU 销售额', attribution_days: '归因窗口（天）' };

export function ReportRecordsPage({ kind, user, selectedStore, onImport }: { kind: ReportKind; user: User; selectedStore: string; onImport: () => void }) {
  const [search, setSearch] = useState<ReportSearchValue>({ q: '', sku: '' });
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [granularity, setGranularity] = useState<'daily' | 'period'>('daily');
  const [record, setRecord] = useState<ReportData | null>(null);
  const [batch, setBatch] = useState<string | null>(null);
  const route = kind === 'sales' ? '/sales-records' : '/ad-records';
  const context = { store_id: selectedStore === 'all' ? undefined : selectedStore, start_date: start, end_date: end, status: kind === 'sales' ? status : undefined, granularity: kind === 'ads' ? granularity : undefined };
  const filters = { ...context, ...search };
  const list = usePagedList<ReportData>(queryPath(route, filters));
  const summary = useResource<{ groups: SummaryGroup[] }>(queryPath(`${route}/summary`, filters));
  const refresh = () => { list.reload(); summary.reload(); };
  const isSales = kind === 'sales';
  return <><PageHeading eyebrow={isSales ? 'AMAZON SALES RECORDS' : 'SPONSORED PRODUCTS'} title={isSales ? '销售记录' : '广告数据'}
    description={isSales ? '查看导入后的订单明细、数量和金额，重叠报告按业务键合并并保留来源。' : '按天查看商品推广数据与 7 天归因指标，同日同 SKU、活动和广告组保留最新导入记录。'}
    extra={user.permissions.includes('reports.import') && <Button type="primary" icon={<ImportOutlined />} onClick={onImport}>前往导入</Button>} />
    <Alert type="info" showIcon title={isSales ? '订单金额口径' : '按天覆盖与统计口径'} description={isSales ? '净额 = 商品金额 + 运费 + 礼品包装费 − 商品优惠 − 运费优惠，不含税、不乘数量。待处理与取消订单分组展示，缺失金额保留为空；不代表结算收入或利润。' : '同店铺按日期、SKU、广告活动名称和广告组名称去重，新导入覆盖之前的数据。日报与历史区间分别汇总；比率重新计算，广告销售额不叠加到订单销售额。'} />
    <Card className="section-card"><div className="report-filters"><ReportSearch route={route} context={context} value={search} onSearch={setSearch} />
      <label>开始日期<Input aria-label="报表开始日期" type="date" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>结束日期<Input aria-label="报表结束日期" type="date" value={end} onChange={event => setEnd(event.target.value)} /></label>
      {isSales && <Select aria-label="筛选订单状态" placeholder="全部状态" allowClear value={status} onChange={setStatus} options={['Pending', 'Shipped', 'Cancelled', 'Partially Shipped', 'Unshipped'].map(value => ({ value, label: statusLabels[value] }))} style={{ width: 130 }} />}
      {!isSales && <Select aria-label="广告数据粒度" value={granularity} onChange={setGranularity} options={[{ value: 'daily', label: '日报' }, { value: 'period', label: '历史区间' }]} style={{ width: 130 }} />}
      <Button onClick={() => { setStart(''); setEnd(''); }}>全部日期</Button><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button></div>
      <p className="table-subtext">{isSales ? '按 UTC 下单日期筛选，默认显示全部日期。' : granularity === 'daily' ? '按源报告日期筛选，缺失日期不视为零。旧版多日汇总可切换「历史区间」查看。' : '仅查看旧版多日汇总，筛选需完整包含报告区间；不与日报合计。'}</p>
    </Card>
    <ErrorNotice error={summary.error} retry={summary.reload} /><Card className="section-card" title={isSales ? '按币种和状态核对' : '按币种汇总'}>
      <Table rowKey={row => `${row.currency}-${row.order_status}-${row.item_status}`} dataSource={summary.data?.groups ?? []} loading={summary.loading} pagination={false} scroll={{ x: isSales ? 720 : 1100 }} columns={isSales ? [
        { title: '币种', dataIndex: 'currency', render: value => value || '未提供' }, { title: '订单 / 商品状态', render: (_, row) => `${statusLabels[String(row.order_status)] || row.order_status} / ${statusLabels[String(row.item_status)] || row.item_status}` },
        { title: '明细行', dataIndex: 'rows' }, { title: '数量', dataIndex: 'quantity' }, { title: '不含税净额', dataIndex: 'net_amount', render: value => value ?? '未提供' }, { title: '缺少金额行', dataIndex: 'missing_amount_rows' },
      ] : [
        { title: '币种', dataIndex: 'currency' }, { title: '展示', dataIndex: 'impressions' }, { title: '点击', dataIndex: 'clicks' }, { title: '花费', dataIndex: 'spend' },
        { title: '7 天销售额', dataIndex: 'attributed_sales' }, { title: '7 天订单', dataIndex: 'orders' }, { title: '7 天销量', dataIndex: 'units' },
        { title: 'CTR', dataIndex: 'ctr', render: percent }, { title: 'CPC', dataIndex: 'cpc', render: value => value ?? '—' }, { title: 'ACOS', dataIndex: 'acos', render: percent }, { title: 'ROAS', dataIndex: 'roas', render: value => value ?? '—' },
      ]} /></Card>
    <ErrorNotice error={list.error} retry={list.reload} /><Card className="section-card" title={isSales ? '订单商品明细' : '广告商品明细'}>
      <Table rowKey="id" loading={list.loading} dataSource={list.data?.items ?? []} pagination={list.pagination} scroll={{ x: isSales ? 1250 : 1500 }} columns={[
        { title: isSales ? '订单 / 店铺' : '活动 / 店铺', width: 240, render: (_, row) => <><Button type="link" onClick={() => setRecord(row)}>{String(isSales ? row.amazon_order_id : row.campaign)}</Button><div className="table-subtext">{row.store_name}{!isSales && ` · ${row.ad_group}`}</div></> },
        { title: 'SKU / ASIN', width: 200, render: (_, row) => <>{row.sku}<div className="table-subtext">{row.asin}</div></> },
        { title: isSales ? '站点' : '国家 / 地区', render: (_, row) => isSales ? row.sales_channel : row.country },
        { title: isSales ? '下单时间（UTC）' : granularity === 'daily' ? '日期' : '统计区间', render: (_, row) => isSales ? String(row.purchase_date).replace('T', ' ').replace('+00:00', '') : row.report_date || `${row.start_date} — ${row.end_date}` },
        ...(isSales ? [{ title: '状态', dataIndex: 'order_status', render: (value: string) => <Tag>{statusLabels[value] || value}</Tag> }, { title: '数量', dataIndex: 'quantity' }] : [{ title: '展示 / 点击', render: (_: unknown, row: ReportData) => `${row.impressions} / ${row.clicks}` }]),
        { title: isSales ? '不含税净额' : '广告花费', render: (_, row) => reportMoney(isSales ? row.net_amount : row.spend, row.currency) },
        ...(!isSales ? [{ title: '7 天销售额', render: (_: unknown, row: ReportData) => reportMoney(row.attributed_sales, row.currency) }] : []),
        { title: '来源', render: (_, row) => <Button onClick={() => setBatch(row.import_id)}>批次 · 行 {row.source_row}</Button> },
      ]} /></Card>
    {record && <Drawer open title={isSales ? '销售明细' : '广告明细'} width={780} onClose={() => setRecord(null)}><Descriptions column={1} bordered items={Object.entries(record).filter(([field]) => field in labels).map(([field, value]) => ({ key: field, label: labels[field], children: value == null || value === '' ? '未提供' : String(value) }))} /></Drawer>}
    {batch && <ReportBatchDrawer id={batch} user={user} onClose={() => setBatch(null)} onChanged={refresh} />}</>;
}
