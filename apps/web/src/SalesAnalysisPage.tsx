import { useState } from 'react';
import { Alert, Button, Card, Col, InputNumber, Row, Select, Statistic, Table, Tabs, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ImportOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import { ErrorNotice, PAGE_SIZE, PageHeading, useResource } from './common';
import { queryPath } from './CatalogShared';
import { ReportRecordsPage } from './ReportRecords';
import { ReportDateFilter } from './ReportDateFilter';
import { ReportSearch } from './ReportSearch';
import { SalesCosts } from './SalesCosts';
import type { ReportSearchValue } from './ReportSearch';
import type { ReportDateRange } from './report-date-ranges';
import type { SalesAnalysis, SalesAnalysisRow } from './sales-analysis-types';
import type { Store, User } from './types';

const money = (value: string | null | undefined) => value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));
const percent = (value: string | null | undefined) => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
const colored = (value: string | null, format = money) => <span className={value != null && Number(value) < 0 ? 'analysis-negative' : undefined}>{format(value)}</span>;

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
  const [dates, setDates] = useState<ReportDateRange>({ start: '', end: '' });
  const [orderScope, setOrderScope] = useState('shipped');
  const [sort, setSort] = useState('sales');
  const [cad, setCad] = useState(1.36);
  const [mxn, setMxn] = useState(17.66);
  const [costs, setCosts] = useState<{ sku?: string } | null>(null);
  const context = { store_id: selectedStore === 'all' ? undefined : selectedStore, start_date: dates.start, end_date: dates.end, order_scope: orderScope };
  const path = queryPath('/sales-analysis', { ...context, ...search, cad_per_usd: String(cad), mxn_per_usd: String(mxn), sort_by: sort, descending: sort === 'sku' ? 'false' : 'true' });
  const [cursor, setCursor] = useState({ path, page: 1 });
  const page = cursor.path === path ? cursor.page : 1;
  const resource = useResource<SalesAnalysis>(`${path}&limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`);
  const data = resource.data;
  const totals = data?.totals;
  const costCell = (value: string | null, row: SalesAnalysisRow) => value == null
    ? <Button type="link" size="small" onClick={() => setCosts({ sku: row.sku })}>待补充</Button> : money(value);
  const columns: ColumnsType<SalesAnalysisRow> = [
    { title: '店铺 SKU', dataIndex: 'sku', fixed: 'left', width: 220, render: (value, row) => <><strong>{value}</strong>
      <div className="table-subtext">{row.store_name}</div>{row.issues.length > 0 && <Tooltip title={row.issues.join('；')}><Tag color="warning">资料待补充</Tag></Tooltip>}</> },
    { title: '销量', dataIndex: 'quantity', width: 80, align: 'right' },
    { title: <span>产品成本、头程<br />及入库配置费 USD</span>, dataIndex: 'product_cost', width: 165, align: 'right', render: costCell },
    { title: <span>FBA 派送费<br />USD</span>, dataIndex: 'fba_fee', width: 130, align: 'right', render: costCell },
    { title: <span>亚马逊佣金<br />USD</span>, dataIndex: 'commission', width: 130, align: 'right', render: money },
    { title: <span>销售利润<br />USD</span>, dataIndex: 'sales_profit', width: 130, align: 'right', render: value => colored(value) },
    { title: <span>亚马逊销售额<br />USD</span>, dataIndex: 'sales', width: 145, align: 'right', render: money },
    { title: <span>销售利润比<br />未扣除推广费用</span>, dataIndex: 'sales_profit_rate', width: 145, align: 'right', render: value => colored(value, percent) },
    { title: <span>实际广告费<br />USD</span>, dataIndex: 'ad_spend', width: 135, align: 'right', render: value => value == null ? <Tooltip title="所选期间未导入该店铺的广告日报">待导入</Tooltip> : money(value) },
    { title: <span>扣除推广实际利润<br />USD</span>, dataIndex: 'actual_profit', width: 155, align: 'right', render: value => colored(value) },
    { title: '实际利润率', dataIndex: 'actual_profit_rate', width: 120, align: 'right', render: value => colored(value, percent) },
  ];
  return <>
    <Card className="section-card"><div className="report-filters">
      <ReportSearch route="/sales-analysis" context={context} value={search} onSearch={setSearch} />
      <ReportDateFilter value={dates} onChange={setDates} />
      <Select aria-label="销售分析订单范围" value={orderScope} onChange={setOrderScope} options={[{ value: 'shipped', label: '已发货商品' }, { value: 'non_cancelled', label: '全部未取消商品' }]} style={{ width: 165 }} />
      <Button onClick={() => setDates({ start: '', end: '' })}>全部日期</Button>
      <Button icon={<ReloadOutlined />} onClick={resource.reload}>刷新</Button>
      <Button icon={<SettingOutlined />} onClick={() => setCosts({})}>费用设置</Button>
    </div><div className="analysis-exchange"><span>美元折算：1 USD =</span>
      <InputNumber aria-label="每美元兑换加元" min={0.000001} max={100000} precision={6} value={cad} onChange={value => { if (value && value > 0) setCad(value); }} /><span>CAD，</span>
      <InputNumber aria-label="每美元兑换墨西哥比索" min={0.000001} max={100000} precision={6} value={mxn} onChange={value => { if (value && value > 0) setMxn(value); }} /><span>MXN（固定分析汇率，可调整）</span>
    </div><p className="table-subtext">订单按 UTC 下单日期，广告按日报日期筛选。CMBQ 尺寸别名沿用周利润规则归并，其他 SKU 精确关联。</p></Card>
    <Alert showIcon type="info" title="利润分析口径" description="销售额 = 商品金额 − 商品优惠；成本与 FBA 费用按销量计算，佣金默认按销售额的 15% 预估。实际广告费取已导入日报，不叠加广告归因销售额。此处利润仍基于预估费用，不是结算净利润；请确认所选期间的销售与广告报告已完整导入。" />
    <ErrorNotice error={resource.error} retry={resource.reload} />
    {!!totals?.incomplete_rows && <Alert className="analysis-alert" showIcon type="warning" title={`${totals.incomplete_rows} 个店铺 SKU 的资料待补充`} description="缺失费用或广告来源的利润留空；合计中受影响的金额也留空，避免高估利润。可在费用设置中补齐。" />}
    {!!data && (data.excluded.unsupported_sales_rows > 0 || data.excluded.unsupported_ad_rows > 0) && <Alert className="analysis-alert" showIcon type="warning" title="部分币种尚未参与折算" description={`所选店铺和期间内有 ${data.excluded.unsupported_sales_rows} 条缺少币种或不支持币种的订单、${data.excluded.unsupported_ad_rows} 条不支持币种的广告未计入；当前支持 USD、CAD、MXN。`} />}
    <Row gutter={[16, 16]} className="analysis-metrics">
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="销量" value={totals?.quantity ?? '—'} suffix="件" /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="亚马逊销售额" value={money(totals?.sales)} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="扣除推广实际利润" value={money(totals?.actual_profit)} styles={{ content: { color: Number(totals?.actual_profit) < 0 ? '#cf1322' : undefined } }} /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="实际利润率" value={percent(totals?.actual_profit_rate)} /></Card></Col>
    </Row>
    <Card className="section-card" title="SKU 销售与利润" extra={<Select aria-label="销售分析排序" value={sort} onChange={setSort} style={{ width: 180 }} options={[
      { value: 'sales', label: '销售额从高到低' }, { value: 'quantity', label: '销量从高到低' }, { value: 'actual_profit', label: '实际利润从高到低' },
      { value: 'actual_profit_rate', label: '实际利润率从高到低' }, { value: 'ad_spend', label: '广告费从高到低' }, { value: 'sku', label: 'SKU 名称' },
    ]} />}>
      <Table<SalesAnalysisRow> rowKey="key" className="sales-analysis-table" loading={resource.loading} dataSource={data?.items ?? []} columns={columns}
        scroll={{ x: 1655 }} pagination={{ current: page, pageSize: PAGE_SIZE, total: data?.total ?? 0, showSizeChanger: false,
          showTotal: total => `共 ${total} 个店铺 SKU`, onChange: page => setCursor({ path, page }) }}
        expandable={{ expandedRowRender: row => <div className="analysis-row-note"><span>订单来源 {row.sales_rows} 行 · 广告日报 {row.ad_rows} 行 · 使用 {row.cost_versions} 个费用版本</span>
          <span>来源 SKU：{row.source_skus.join('、')}</span>{row.issues.map(issue => <Tag key={issue} color="warning">{issue}</Tag>)}<Button size="small" onClick={() => setCosts({ sku: row.sku })}>查看 SKU 费用</Button></div> }}
        summary={() => totals && <Table.Summary fixed><Table.Summary.Row>
          <Table.Summary.Cell index={0} />
          <Table.Summary.Cell index={1}><strong>全部筛选结果合计</strong></Table.Summary.Cell>
          {(['quantity', 'product_cost', 'fba_fee', 'commission', 'sales_profit', 'sales', 'sales_profit_rate', 'ad_spend', 'actual_profit', 'actual_profit_rate'] as const).map((field, i) =>
            <Table.Summary.Cell index={i + 2} key={field} align="right"><strong>{field === 'quantity' ? totals[field] : field.endsWith('_rate') ? percent(totals[field]) : money(totals[field])}</strong></Table.Summary.Cell>)}
        </Table.Summary.Row></Table.Summary>} />
      <p className="table-subtext">合计包含全部筛选结果，不只当前页；利润率按合计利润 ÷ 合计销售额重算。销售额为 0 时利润率显示 0.00%。同名 SKU 在不同店铺分别核算。</p>
    </Card>
    {costs && <SalesCosts user={user} stores={stores} selectedStore={selectedStore} sku={costs.sku} onClose={() => setCosts(null)} onChanged={resource.reload} />}
  </>;
}
