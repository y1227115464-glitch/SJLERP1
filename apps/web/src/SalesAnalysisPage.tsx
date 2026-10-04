import { useEffect, useState } from 'react';
import { Alert, Button, Card, Checkbox, Col, InputNumber, Row, Segmented, Select, Statistic, Table, Tabs, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ImportOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import { ErrorNotice, PAGE_SIZE, PageHeading, useResource } from './common';
import { queryPath } from './CatalogShared';
import { ReportRecordsPage } from './ReportRecords';
import { ReportDateFilter } from './ReportDateFilter';
import { SALES_UTC_OFFSET_MINUTES } from './sales-report-time';
import { ReportSearch } from './ReportSearch';
import { SalesCosts } from './SalesCosts';
import type { ReportSearchValue } from './ReportSearch';
import { reportDateRange, type ReportDateRange } from './report-date-ranges';
import type { SalesAnalysis, SalesAnalysisRow, SalesAnalysisPeriod, SalesAnalysisPeriods } from './sales-analysis-types';
import { defaultSalesGranularity, type SalesGranularity } from './sales-analysis-periods';
import type { Store, User } from './types';
import { readSalesDates, saveSalesDates } from './filter-preferences';

const money = (value: string | null | undefined) => value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));
const percent = (value: string | null | undefined) => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
const colored = (value: string | null, format = money) => <span className={value != null && Number(value) < 0 ? 'analysis-negative' : undefined}>{format(value)}</span>;

function SkuPeriods({ row, dates, orderScope, cad, mxn, columns, onCosts }: {
  row: SalesAnalysisRow; dates: ReportDateRange; orderScope: string; cad: number; mxn: number;
  columns: ColumnsType<SalesAnalysisRow>; onCosts: () => void;
}) {
  const [granularity, setGranularity] = useState<SalesGranularity>(() => defaultSalesGranularity(dates.start, dates.end));
  const path = queryPath('/sales-analysis/periods', { store_id: row.store_id, sku: row.sku,
    start_date: dates.start, end_date: dates.end, order_scope: orderScope,
    cad_per_usd: String(cad), mxn_per_usd: String(mxn), granularity });
  const [cursor, setCursor] = useState({ path, page: 1 });
  const page = cursor.path === path ? cursor.page : 1;
  const resource = useResource<SalesAnalysisPeriods>(`${path}&limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`);
  const periodColumns: ColumnsType<SalesAnalysisPeriod> = [
    { title: '统计期间', key: 'period', fixed: 'left', width: 220, render: (_, item) => <>
      <span>{item.period_start === item.period_end ? item.period_start : `${item.period_start} ～ ${item.period_end}`}</span>
      {!!item.issues.length && <Tooltip title={item.issues.join('；')}><Tag color="warning">资料待补充</Tag></Tooltip>}
    </> },
    ...columns.slice(1) as ColumnsType<SalesAnalysisPeriod>,
  ];
  return <div className="analysis-periods">
    <div className="analysis-period-toolbar"><strong>{row.store_name} · {row.sku}</strong>
      <Segmented<SalesGranularity> aria-label="SKU 明细聚合方式" value={granularity} onChange={setGranularity} options={[
        { value: 'day', label: '按天' }, { value: 'week', label: '按周' }, { value: 'month', label: '按月' }, { value: 'year', label: '按年' },
      ]} />
    </div>
    <p className="table-subtext">周按周一至周日，月和年按自然月、自然年汇总；首尾仅统计所选日期。各期间利润率按利润 ÷ 销售额重算，未导入广告日报的期间显示待确认。</p>
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <Table<SalesAnalysisPeriod> rowKey="key" size="small" loading={resource.loading} columns={periodColumns}
      dataSource={resource.data?.items ?? []} scroll={{ x: 1655 }} pagination={{ current: page, pageSize: PAGE_SIZE,
        total: resource.data?.total ?? 0, showSizeChanger: false, hideOnSinglePage: true,
        showTotal: total => `共 ${total} 个期间`, onChange: page => setCursor({ path, page }) }} />
    <div className="analysis-row-note"><span>订单来源 {row.sales_rows} 行 · 广告日报 {row.ad_rows} 行 · 使用 {row.cost_versions} 个费用版本</span>
      <span>来源 SKU：{row.source_skus.join('、')}</span>{row.issues.map(issue => <Tag key={issue} color="warning">{issue}</Tag>)}
      <Button size="small" onClick={onCosts}>查看 SKU 费用</Button></div>
  </div>;
}

export function SalesAnalysisPage({ user, stores, selectedStore, onImport }: {
  user: User; stores: Store[]; selectedStore: string; onImport: () => void;
}) {
  const canAnalyze = user.permissions.includes('costs.view');
  return <><PageHeading eyebrow="AMAZON SALES ANALYSIS" title="销售数据分析"
    description="按店铺 SKU 查看销量、销售额和推广前后利润，核对成本与广告投入。"
    extra={user.permissions.includes('reports.import') && <Button type="primary" icon={<ImportOutlined />} onClick={onImport}>前往导入</Button>} />
    <Tabs defaultActiveKey={canAnalyze ? 'analysis' : 'records'} items={[
      { key: 'analysis', label: '销售数据分析', children: canAnalyze ? <Analysis user={user} stores={stores} selectedStore={selectedStore} />
        : <Alert showIcon type="info" title="当前账号可查看订单明细" description="成本及利润分析需要成本查看权限。" /> },
      { key: 'records', label: '订单明细', children: <ReportRecordsPage kind="sales" embedded user={user} selectedStore={selectedStore} onImport={onImport} /> },
    ]} />
  </>;
}

function Analysis({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const [search, setSearch] = useState<ReportSearchValue>({ q: '', sku: '' });
  const [dates, setDates] = useState<ReportDateRange>(() => readSalesDates() ?? ({
    ...reportDateRange('last7', new Date(), false, SALES_UTC_OFFSET_MINUTES), preset: 'last7',
  }));
  useEffect(() => { saveSalesDates(dates); }, [dates]);
  const [orderScope, setOrderScope] = useState('non_cancelled');
  const [sort, setSort] = useState('sku');
  const [cad, setCad] = useState(1.36);
  const [mxn, setMxn] = useState(17.66);
  const [costs, setCosts] = useState<{ sku?: string; tab?: 'costs' | 'fba' } | null>(null);
  const context = { store_id: selectedStore === 'all' ? undefined : selectedStore, start_date: dates.start, end_date: dates.end, order_scope: orderScope };
  const selectionScope = queryPath('/sales-analysis', { ...context, ...search, cad_per_usd: String(cad), mxn_per_usd: String(mxn) });
  const [selection, setSelection] = useState<{ scope: string; overrides: Map<string, boolean> }>(() => ({ scope: selectionScope, overrides: new Map() }));
  useEffect(() => { setSelection({ scope: selectionScope, overrides: new Map() }); }, [selectionScope]);
  const overrides = selection.scope === selectionScope ? selection.overrides : new Map<string, boolean>();
  const toggleIncluded = (key: string, included: boolean) => setSelection(previous => {
    const overrides = new Map(previous.scope === selectionScope ? previous.overrides : []);
    overrides.set(key, included);
    return { scope: selectionScope, overrides };
  });
  const path = queryPath('/sales-analysis', { ...context, ...search, cad_per_usd: String(cad), mxn_per_usd: String(mxn), sort_by: sort, descending: sort === 'sku' ? 'false' : 'true' });
  const [cursor, setCursor] = useState({ path, page: 1 });
  const page = cursor.path === path ? cursor.page : 1;
  const resource = useResource<SalesAnalysis>(`${path}&exclude_incomplete=true&limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`);
  const exclusions = new URLSearchParams();
  [...overrides].sort(([a], [b]) => a.localeCompare(b)).forEach(([key, included]) => exclusions.append(included ? 'included_keys' : 'excluded_keys', key));
  const selectedTotals = useResource<SalesAnalysis>(overrides.size ? `${selectionScope}&exclude_incomplete=true&limit=1&${exclusions}` : null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const reload = () => { resource.reload(); selectedTotals.reload(); setRefreshVersion(value => value + 1); };
  const data = resource.data;
  const totals = overrides.size ? selectedTotals.data?.totals : data?.totals;
  const costCell = (value: string | null, row: SalesAnalysisRow) => value == null
    ? <Button type="link" size="small" onClick={() => setCosts({ sku: row.sku })}>待补充</Button> : money(value);
  const columns: ColumnsType<SalesAnalysisRow> = [
    { title: '店铺 SKU', dataIndex: 'sku', fixed: 'left', width: 200, render: (value, row) => <div className="analysis-sku-cell">
      <Tooltip title="勾选后计入合计"><Checkbox aria-label={`${row.store_name} ${row.sku} 计入合计`} checked={overrides.get(row.key) ?? row.issues.length === 0}
        onChange={event => toggleIncluded(row.key, event.target.checked)} /></Tooltip>
      <div><strong>{value}</strong>
        {row.issues.length > 0 && <Tooltip title={row.issues.join('；')}><Tag color="warning">资料待补充</Tag></Tooltip>}</div>
    </div> },
    { title: '销量', dataIndex: 'quantity', fixed: 'left', width: 80, align: 'right' },
    { title: <span>产品成本、头程<br />及入库配置费 USD</span>, dataIndex: 'product_cost', width: 165, align: 'right', render: costCell },
    { title: <span>FBA 派送费<br />USD</span>, dataIndex: 'fba_fee', width: 130, align: 'right', render: (value, row) => value == null
      ? <Button type="link" size="small" onClick={() => setCosts({ sku: row.sku, tab: 'fba' })}>待补充</Button> : money(value) },
    { title: <span>亚马逊佣金<br />USD</span>, dataIndex: 'commission', width: 130, align: 'right', render: money },
    { title: <span>销售利润<br />USD</span>, dataIndex: 'sales_profit', width: 130, align: 'right', render: value => colored(value) },
    { title: <span>亚马逊销售额<br />USD</span>, dataIndex: 'sales', width: 145, align: 'right', render: money },
    { title: <span>销售利润比<br />未扣除推广费用</span>, dataIndex: 'sales_profit_rate', width: 145, align: 'right', render: value => colored(value, percent) },
    { title: <span>实际广告费<br />USD</span>, dataIndex: 'ad_spend', width: 135, align: 'right', render: value => value == null ? <Tooltip title="请检查广告日报及品牌广告商品分摊">待确认</Tooltip> : money(value) },
    { title: <span>扣除推广实际利润<br />USD</span>, dataIndex: 'actual_profit', width: 155, align: 'right', render: value => colored(value) },
    { title: '实际利润率', dataIndex: 'actual_profit_rate', width: 120, align: 'right', render: value => colored(value, percent) },
  ];
  return <>
    <Card className="section-card"><div className="report-filters">
      <ReportSearch route="/sales-analysis" context={context} value={search} onSearch={setSearch} />
      <ReportDateFilter value={dates} onChange={setDates} utcOffsetMinutes={SALES_UTC_OFFSET_MINUTES} defaultIncludeToday={false} />
      <Select aria-label="销售分析订单范围" value={orderScope} onChange={setOrderScope} options={[{ value: 'shipped', label: '已发货商品' }, { value: 'non_cancelled', label: '全部未取消商品' }]} style={{ width: 165 }} />
      <Button onClick={() => setDates({ start: '', end: '' })}>全部日期</Button>
      <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
      <Button icon={<SettingOutlined />} onClick={() => setCosts({})}>费用设置</Button>
    </div><div className="analysis-exchange"><span>美元折算：1 USD =</span>
      <InputNumber aria-label="每美元兑换加元" min={0.000001} max={100000} precision={6} value={cad} onChange={value => { if (value && value > 0) setCad(value); }} /><span>CAD，</span>
      <InputNumber aria-label="每美元兑换墨西哥比索" min={0.000001} max={100000} precision={6} value={mxn} onChange={value => { if (value && value > 0) setMxn(value); }} /><span>MXN（固定分析汇率，可调整）</span>
    </div><p className="table-subtext">订单按 PDT（全年固定 UTC−7）下单日期筛选，广告按日报日期筛选。CMBQ 尺寸别名沿用周利润规则归并，其他 SKU 精确关联。</p></Card>
    <Alert showIcon type="info" title="利润分析口径" description="销售额 = 商品金额 − 商品优惠；成本与 FBA 费用按销量计算，佣金默认按销售额的 15% 预估。实际广告费取已导入日报，不叠加广告归因销售额。此处利润仍基于预估费用，不是结算净利润；请确认所选期间的销售与广告报告已完整导入。" />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <ErrorNotice error={selectedTotals.error} retry={selectedTotals.reload} />
    {!!totals?.incomplete_rows && <Alert className="analysis-alert" showIcon type="warning" title={`${totals.incomplete_rows} 个店铺 SKU 的资料待补充`} description="缺失费用、广告来源或品牌广告分摊的利润留空。请在费用设置或广告数据中补齐。" />}
    {!!data?.excluded.unallocated_brand_campaigns?.length && <Alert className="analysis-alert" showIcon type="warning" title="品牌广告尚未分摊，实际广告费与利润待确认" description={<><p>请到「广告数据 → 品牌广告分摊」维护商品与比例。以下花费属于所选期间，尚未归属到 SKU：</p>{data.excluded.unallocated_brand_campaigns.map(item => <div key={`${item.store_id}:${item.campaign}:${item.currency}`}>{stores.find(store => store.id === item.store_id)?.name || item.store_id} · {item.campaign} · {item.currency} {item.spend}</div>)}</>} />}
    {!!data && (data.excluded.unsupported_sales_rows > 0 || data.excluded.unsupported_ad_rows > 0) && <Alert className="analysis-alert" showIcon type="warning" title="部分币种尚未参与折算" description={`所选店铺和期间内有 ${data.excluded.unsupported_sales_rows} 条缺少币种或不支持币种的订单、${data.excluded.unsupported_ad_rows} 条不支持币种的广告未计入；当前支持 USD、CAD、MXN。`} />}
    <Row gutter={[16, 16]} className="analysis-metrics">
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="销量" value={totals?.quantity ?? '—'} suffix="件" /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="亚马逊销售额" value={money(totals?.sales)} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="扣除推广实际利润" value={money(totals?.actual_profit)} styles={{ content: { color: Number(totals?.actual_profit) < 0 ? '#cf1322' : undefined } }} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="实际利润率" value={percent(totals?.actual_profit_rate)} /></Card></Col>
    </Row>
    <Card className="section-card" title="SKU 销售与利润" extra={<Select aria-label="销售分析排序" value={sort} onChange={setSort} style={{ width: 180 }} options={[
      { value: 'sku', label: 'SKU 字母升序（A–Z）' },
      { value: 'sales', label: '销售额从高到低' }, { value: 'quantity', label: '销量从高到低' }, { value: 'actual_profit', label: '实际利润从高到低' },
      { value: 'actual_profit_rate', label: '实际利润率从高到低' }, { value: 'ad_spend', label: '广告费从高到低' },
    ]} />}>
      <Table<SalesAnalysisRow> rowKey="key" className="sales-analysis-table" loading={resource.loading} dataSource={data?.items ?? []} columns={columns}
        scroll={{ x: 1683, y: 'min(60vh, 640px)' }} pagination={{ current: page, pageSize: PAGE_SIZE, total: data?.total ?? 0, showSizeChanger: false,
          showTotal: total => `共 ${total} 个店铺 SKU`, onChange: page => setCursor({ path, page }) }}
        expandable={{ fixed: 'left', columnWidth: 48, expandedRowRender: row => <SkuPeriods key={`${row.key}:${dates.start}:${dates.end}:${refreshVersion}`}
          row={row} dates={dates} orderScope={orderScope} cad={cad} mxn={mxn} columns={columns}
          onCosts={() => setCosts({ sku: row.sku })} /> }}
        summary={() => totals && <Table.Summary fixed><Table.Summary.Row>
          <Table.Summary.Cell index={0} />
          <Table.Summary.Cell index={1}><strong>勾选数据合计</strong></Table.Summary.Cell>
          {(['quantity', 'product_cost', 'fba_fee', 'commission', 'sales_profit', 'sales', 'sales_profit_rate', 'ad_spend', 'actual_profit', 'actual_profit_rate'] as const).map((field, i) =>
            <Table.Summary.Cell index={i + 2} key={field} align="right"><strong>{field === 'quantity' ? totals[field] : field.endsWith('_rate') ? percent(totals[field]) : money(totals[field])}</strong></Table.Summary.Cell>)}
        </Table.Summary.Row></Table.Summary>} />
      <p className="table-subtext">资料完整的 SKU 默认勾选，资料待补充的默认不勾选，可手动调整。合计及上方统计只计入勾选的 SKU，包含全部分页。翻页和排序保留勾选状态，切换筛选条件后恢复默认勾选。利润率按合计利润 ÷ 合计销售额重算，销售额为 0 时显示 0.00%。同名 SKU 在不同店铺分别核算。</p>
    </Card>
    {costs && <SalesCosts user={user} stores={stores} selectedStore={selectedStore} sku={costs.sku} initialTab={costs.tab} onClose={() => setCosts(null)} onChanged={reload} />}
  </>;
}
