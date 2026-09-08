import { useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Drawer, Form, Input, Modal, Select, Space, Statistic, Table, Tag } from 'antd';
import { CloudUploadOutlined, ReloadOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { dateTime, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { queryPath } from './CatalogShared';
import type { Store, User } from './types';
import type { PreviewRow, ReportBatch, ReportKind } from './report-types';

export const reportNames = { sales: '销售数据', ads: '广告数据' };
const actionLabels: Record<string, string> = { create: '新增', update: '更新', skip: '跳过', conflict: '冲突', error: '错误', source: '来源记录' };
const actionColors: Record<string, string> = { create: 'success', update: 'processing', skip: 'default', conflict: 'warning', error: 'error' };
export const reportMoney = (value: unknown, currency: unknown) => value == null ? '未提供' : `${currency || '币种未提供'} ${value}`;
export function ReportImportsPage({ user, stores, selectedStore }: { user: User; stores: Store[]; selectedStore: string }) {
  const [kind, setKind] = useState<ReportKind | undefined>();
  const [upload, setUpload] = useState<ReportKind | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const list = usePagedList<ReportBatch>(queryPath('/report-imports', { kind, store_id: selectedStore === 'all' ? undefined : selectedStore }));
  return <><PageHeading eyebrow="AMAZON REPORT IMPORT" title="数据导入中心" description="按店铺上传亚马逊原始销售与广告报告，先核对预览，再确认写入。" />
    {user.permissions.includes('reports.import') && <div className="report-import-options">{(['sales', 'ads'] as ReportKind[]).map(item => <Card key={item} title={item === 'sales' ? '销售订单报告' : '商品推广报告'}>
      <p>{item === 'sales' ? 'TXT / TSV 制表符格式。按订单与 SKU 去重，较新的订单状态覆盖旧版本。' : 'XLSX 格式，7 天归因指标。同一天的 SKU、广告活动和广告组相同，新导入覆盖旧记录。'}</p>
      <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setUpload(item)}>导入{reportNames[item]}</Button></Card>)}</div>}
    <Alert type="info" showIcon title="重复导入不会重复累计" description="销售按店铺、销售站点、订单号和 SKU 识别重复；旧版本跳过，同更新时间内容冲突时暂停导入。广告在同店铺按日期、SKU、广告活动名称和广告组名称去重，新记录覆盖旧记录。" />
    <ErrorNotice error={list.error} retry={list.reload} /><Card className="section-card" title="导入批次" extra={<Space><Select aria-label="筛选报告类型" placeholder="全部报告" allowClear value={kind} onChange={setKind} options={Object.entries(reportNames).map(([value, label]) => ({ value, label }))} style={{ width: 140 }} /><Button icon={<ReloadOutlined />} onClick={list.reload}>刷新</Button></Space>}>
      <Table rowKey="id" loading={list.loading} dataSource={list.data?.items ?? []} pagination={list.pagination} scroll={{ x: 950 }} columns={[
        { title: '文件 / 店铺', render: (_, row) => <><Button type="link" onClick={() => setDetail(row.id)}>{row.filename}</Button><div className="table-subtext">{row.store_name}</div></> },
        { title: '类型', dataIndex: 'kind', render: (value: ReportKind) => reportNames[value] },
        { title: '源数据行', dataIndex: 'source_total' }, { title: '状态', render: (_, row) => <Tag color={row.result ? 'success' : row.error_count ? 'error' : 'processing'}>{row.result ? '已确认' : row.error_count ? '校验有误' : '待确认'}</Tag> },
        { title: '确认结果', render: (_, row) => row.result ? `新增 ${row.result.created} / 更新 ${row.result.updated} / 跳过 ${row.result.skipped}` : '查看预览' },
        { title: '上传时间', dataIndex: 'created_at', render: dateTime }, { title: '操作', render: (_, row) => <Button onClick={() => setDetail(row.id)}>查看批次</Button> },
      ]} /></Card>
    {upload && <ReportUpload kind={upload} stores={stores} selectedStore={selectedStore} onClose={() => setUpload(null)} onSaved={id => { setUpload(null); list.reload(); setDetail(id); }} />}
    {detail && <ReportBatchDrawer id={detail} user={user} onClose={() => setDetail(null)} onChanged={list.reload} />}</>;
}

function ReportUpload({ kind, stores, selectedStore, onClose, onSaved }: { kind: ReportKind; stores: Store[]; selectedStore: string; onClose: () => void; onSaved: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async ({ store_id }: { store_id: string }) => {
    if (!file) { setError('请选择要导入的文件'); return; }
    if (file.size > 20 * 1024 * 1024) { setError('文件不能超过 20 MB'); return; }
    setBusy(true); setError('');
    try { const form = new FormData(); form.append('kind', kind); form.append('store_id', store_id); form.append('file', file);
      const result = await api<ReportBatch>('/report-imports/preview', { method: 'POST', body: form }); onSaved(result.id);
    } catch (cause) { setError(errorText(cause)); } finally { setBusy(false); }
  };
  return <Modal open title={`导入${reportNames[kind]}`} footer={null} onCancel={onClose} closable={!busy} maskClosable={!busy}>
    <ErrorNotice error={error} /><Form layout="vertical" onFinish={submit} initialValues={{ store_id: selectedStore === 'all' ? undefined : selectedStore }}>
      <Form.Item name="store_id" label="数据所属店铺" rules={[{ required: true, message: '请选择实际所属店铺' }]}><Select disabled={busy} placeholder="请选择实际所属店铺" options={stores.filter(store => store.is_active).map(store => ({ value: store.id, label: store.name }))} /></Form.Item>
      <Form.Item label={kind === 'sales' ? '销售 TXT / TSV 文件' : '广告 XLSX 文件'} required><Input type="file" aria-label="选择导入文件" accept={kind === 'sales' ? '.txt,.tsv' : '.xlsx'} disabled={busy} onChange={event => setFile(event.target.files?.[0] ?? null)} /></Form.Item>
      <p className="table-subtext">最多 20 MB、10000 行。下一步显示新增、更新、跳过与错误明细，尚不写入业务记录。</p>
      {kind === 'ads' && <p className="table-subtext">日报支持「日期」列或相同的起止日期。同日同 SKU、活动和广告组在文件内重复时保留最后一行；旧版多日汇总在「历史区间」查看。</p>}
      <Space><Button onClick={onClose} disabled={busy}>取消</Button><Button type="primary" htmlType="submit" loading={busy}>{busy ? '正在读取和校验' : '上传并预览'}</Button></Space>
    </Form></Modal>;
}

export function ReportBatchDrawer({ id, user, onClose, onChanged }: { id: string; user: User; onClose: () => void; onChanged?: () => void }) {
  const detail = useResource<ReportBatch>(`/report-imports/${id}`);
  const [action, setAction] = useState<string | undefined>();
  const rows = usePagedList<PreviewRow>(queryPath(`/report-imports/${id}/rows`, { action }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const { message } = App.useApp();
  const batch = detail.data;
  const refresh = () => { detail.reload(); rows.reload(); };
  const confirm = async () => {
    if (!batch?.verification_token) return;
    setBusy(true); setError('');
    try { await api(`/report-imports/${id}/confirm`, { method: 'POST', body: { verification_token: batch.verification_token } });
      message.success('导入已确认，销售或广告记录已更新'); setAction(undefined); refresh(); onChanged?.();
    } catch (cause) { setError(errorText(cause)); refresh(); } finally { setBusy(false); }
  };
  return <Drawer open width={1050} title="导入批次与预览" onClose={onClose} loading={detail.loading && !batch}>
    <ErrorNotice error={detail.error || error} retry={refresh} />{batch && <>
      <Descriptions column={2} items={[{ key: 'file', label: '源文件', children: batch.filename }, { key: 'store', label: '店铺', children: batch.store_name }, { key: 'kind', label: '类型', children: reportNames[batch.kind] },
        { key: 'total', label: '源数据行', children: batch.source_total }, { key: 'duplicates', label: '文件内合并重复行', children: batch.duplicate_count }, { key: 'errors', label: '错误行', children: batch.error_count }]} />
      {batch.result ? <Alert showIcon type="success" title="此批次已确认" description={`新增 ${batch.result.created} 条，更新 ${batch.result.updated} 条，跳过已有 ${batch.result.skipped} 条，合并文件内重复 ${batch.result.file_duplicates} 行。再次确认不会重复入库。`} /> : <>
        <div className="report-counts">{Object.entries(batch.counts ?? {}).map(([key, count]) => <Statistic key={key} title={actionLabels[key]} value={count} />)}</div>
        <Alert showIcon type={batch.error_count || batch.counts?.conflict ? 'error' : 'info'} title={batch.error_count || batch.counts?.conflict ? '请处理错误或冲突后重新上传' : '核对预览后确认导入'} description="确认时会重新检查重复与版本；若数据已变化，需要刷新预览并再次确认。任何错误或冲突都会阻止整批写入。" />
        <Space className="report-actions"><Button onClick={refresh} icon={<ReloadOutlined />}>刷新预览</Button>{batch.can_confirm && user.permissions.includes('reports.import') && <Button type="primary" onClick={confirm} loading={busy} disabled={!!batch.error_count || !!batch.counts?.conflict}>确认导入</Button>}</Space>
      </>}
      {!batch.result && <Select aria-label="筛选预览结果" placeholder="全部预览结果" value={action} onChange={setAction} allowClear style={{ width: 180, marginBottom: 16 }} options={['create', 'update', 'skip', 'conflict', 'error'].map(value => ({ value, label: actionLabels[value] }))} />}
      <ErrorNotice error={rows.error} retry={rows.reload} /><Table rowKey="row" dataSource={rows.data?.items ?? []} loading={rows.loading} pagination={rows.pagination} scroll={{ x: 900 }} columns={[
        { title: '源行', dataIndex: 'row', width: 70 }, { title: '处理', dataIndex: 'action', width: 85, render: value => <Tag color={actionColors[value]}>{actionLabels[value]}</Tag> },
        { title: '订单 / 广告活动', render: (_, row) => row.data?.amazon_order_id || row.data?.campaign || '—' },
        ...(batch.kind === 'ads' ? [{ title: '日期 / 广告组', render: (_: unknown, row: PreviewRow) => <>{row.data?.report_date || (row.data ? `${row.data.start_date} — ${row.data.end_date}` : '—')}<div className="table-subtext">{row.data?.ad_group}</div></> }] : []),
        { title: 'SKU / ASIN', render: (_, row) => <>{row.data?.sku || '—'}<div className="table-subtext">{row.data?.asin}</div></> },
        { title: '数量 / 点击', render: (_, row) => row.data?.quantity ?? row.data?.clicks ?? '—' },
        { title: '订单净额 / 广告花费', render: (_, row) => row.data ? reportMoney(row.data.net_amount ?? row.data.spend, row.data.currency) : '—' },
        { title: '说明', dataIndex: 'message', width: 240 },
      ]} />
    </>}</Drawer>;
}
