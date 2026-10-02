import { useState } from 'react';
import { Alert, App, Button, Card, DatePicker, Drawer, Form, Input, InputNumber, Modal, Select, Space, Table, Tag } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { api, errorText } from './api';
import { ErrorNotice, PageHeading, usePagedList } from './common';
import { queryPath } from './CatalogShared';
import type { Store, User } from './types';

type Fee = { id: string; store_id: string | null; sku: string; effective_from: string; effective_until: string | null;
  low_price_fee: string; high_price_fee: string; source: string; revision: number };
type FeeProduct = { sku: string; current: Fee | null; legacy_fee: string | null; version_count: number; scheduled_count: number;
  deletable_versions: Record<string, number> };
type FeeForm = { store_id: string; sku: string; effective_from: Dayjs; low_price_fee: string; high_price_fee: string; source: string };
type Editor = { original?: Fee; sku?: string; copy?: Fee };
type Props = { user: User; stores: Store[]; selectedStore: string; sku?: string; onChanged?: () => void };
const usd = (value: string) => `$${Number(value).toLocaleString('en-US', { maximumFractionDigits: 9 })}`;
const period = (fee: Fee) => `${fee.effective_from} 至 ${fee.effective_until || '下次调价前'}`;

export function FbaFeesPage(props: Props) {
  return <><PageHeading eyebrow="AMAZON FULFILLMENT FEES" title="亚马逊物流费"
    description="逐个 SKU 维护两档单件物流费，保留每次调价的生效期间。" /><FbaFees {...props} /></>;
}

export function FbaFees({ user, stores, selectedStore, sku, onChanged }: Props) {
  const { message } = App.useApp();
  const [search, setSearch] = useState(sku || '');
  const [active, setActive] = useState('true');
  const [asOf, setAsOf] = useState(dayjs());
  const [historySku, setHistorySku] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<FeeProduct | null>(null);
  const [deletingBusy, setDeletingBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [form] = Form.useForm<FeeForm>();
  const scope = selectedStore === 'all' ? undefined : selectedStore;
  const list = usePagedList<FeeProduct>(queryPath('/sales-analysis/fba-fees/catalog', {
    store_id: scope, q: search, as_of: asOf.format('YYYY-MM-DD'), is_active: active === 'all' ? undefined : active,
  }));
  const canManage = user.permissions.includes('quotes.manage');
  const scopeName = (store: string | null) => store ? stores.find(item => item.id === store)?.name || '授权店铺' : '通用 · 所有店铺';
  const openEditor = (next: Editor) => {
    const base = next.original || next.copy;
    form.resetFields();
    form.setFieldsValue({ sku: next.sku || base?.sku || '',
      store_id: next.original ? next.original.store_id || '*' : next.copy?.store_id || scope || (user.role === 'admin' ? '*' : undefined),
      effective_from: next.original ? dayjs(next.original.effective_from) :
        base && !dayjs(base.effective_from).isBefore(dayjs(), 'day') ? dayjs(base.effective_from).add(1, 'day') : dayjs(),
      low_price_fee: base?.low_price_fee, high_price_fee: base?.high_price_fee, source: base?.source || '',
    });
    setEditor(next);
  };
  const save = async (values: FeeForm) => {
    setSaving(true);
    try {
      await api('/sales-analysis/fba-fees', { method: 'POST', body: { ...values,
        store_id: values.store_id === '*' ? null : values.store_id, sku: values.sku.trim(),
        effective_from: values.effective_from.format('YYYY-MM-DD'), revision: editor?.original?.revision || 0,
      } });
      setEditor(null); setRevision(value => value + 1); list.reload(); onChanged?.();
      message.success('物流费已保存，适用期间的销售分析已更新');
    } catch (error) { message.error(errorText(error)); } finally { setSaving(false); }
  };
  const removeSku = async () => {
    if (!deleting) return;
    setDeletingBusy(true);
    try {
      await api('/sales-analysis/fba-fees/catalog', { method: 'DELETE', body: {
        sku: deleting.sku, store_id: scope || null, versions: deleting.deletable_versions,
      } });
      setDeleting(null); setRevision(value => value + 1);
      if (list.data?.items.length === 1 && list.pagination.current > 1) list.pagination.onChange(list.pagination.current - 1);
      else list.reload();
      onChanged?.();
      message.success('该 SKU 已从物流费列表删除');
    } catch (error) { message.error(errorText(error)); setDeleting(null); list.reload(); }
    finally { setDeletingBusy(false); }
  };
  return <>
    <Alert showIcon type="info" title="售价 ≤ $9.99 和售价 > $9.99，各维护一个单件费用"
      description="售价按订单商品金额 ÷ 数量计算，优惠前、不含税和运费；非美元订单按销售分析汇率折算。按 UTC 下单日期选取生效版本。同范围、同 SKU 的新版本生效后，旧版本自动截至前一天。物流费按原始 SKU 精确匹配。" />
    <Card className="section-card" style={{ marginTop: 16 }}>
      <Space wrap className="analysis-cost-toolbar">
        <Input.Search aria-label="搜索物流费 SKU" placeholder="搜索商品或订单 SKU" defaultValue={search} allowClear onSearch={setSearch} style={{ width: 280 }} />
        <span>商品状态</span><Select aria-label="筛选物流费商品状态" value={active} onChange={setActive} style={{ width: 130 }}
          options={[{ value: 'all', label: '全部' }, { value: 'true', label: '启用中' }, { value: 'false', label: '已停用' }]} />
        <span>查看日期</span><DatePicker aria-label="查看物流费生效日期" value={asOf} allowClear={false} onChange={value => value && setAsOf(value)} />
        <Button icon={<ReloadOutlined />} onClick={list.reload}>刷新</Button>
        {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor({})}>新增物流费</Button>}
      </Space>
      <p className="table-subtext">{scope ? '显示所选店铺在查看日期适用的费用，店铺专用版本优先于通用版本。' : '当前显示通用费用；选择顶部店铺可查看专用费用。'} 商品状态按精确 SKU 匹配商品档案；未建档的 SKU 可切换至“全部”查看。未录入双档费用的历史日期仍沿用原单档费用。</p>
      <ErrorNotice error={list.error} retry={list.reload} />
      <Table<FeeProduct> rowKey="sku" loading={list.loading} dataSource={list.data?.items ?? []} pagination={list.pagination} scroll={{ x: 1100 }} columns={[
        { title: 'SKU', dataIndex: 'sku', width: 210, fixed: 'left' },
        { title: '售价 ≤ $9.99 / 件', width: 145, render: (_, row) => row.current ? usd(row.current.low_price_fee) : <Tag color="warning">待维护</Tag> },
        { title: '售价 > $9.99 / 件', width: 145, render: (_, row) => row.current ? usd(row.current.high_price_fee) : <Tag color="warning">待维护</Tag> },
        { title: '适用范围 / 生效期间', width: 255, render: (_, row) => row.current ? <>{scopeName(row.current.store_id)}<div className="table-subtext">{period(row.current)}</div></> :
          <>{row.legacy_fee !== null ? <>历史单档：{usd(row.legacy_fee)} / 件<div className="table-subtext">尚未维护双档费用</div></> : '尚无适用费用'}</> },
        { title: '调价记录', width: 125, render: (_, row) => <>{row.version_count} 个版本{row.scheduled_count > 0 && <div className="table-subtext">{row.scheduled_count} 个后续版本</div>}</> },
        { title: '操作', width: 270, fixed: 'right', render: (_, row) => <Space>
          {canManage && <Button type="link" onClick={() => openEditor({ sku: row.sku, copy: row.current || undefined })}>{row.current ? '新增调价' : '维护费用'}</Button>}
          <Button type="link" onClick={() => setHistorySku(row.sku)}>历史版本</Button>
          {canManage && <Button type="link" danger
            onClick={() => setDeleting(row)}>删除</Button>}
        </Space> },
      ]} />
    </Card>
    <Modal open={!!deleting} title="删除物流费 SKU 数据" onCancel={() => !deletingBusy && setDeleting(null)}
      closable={!deletingBusy} maskClosable={!deletingBusy} keyboard={!deletingBusy} okText="确认删除" cancelText="取消"
      okButtonProps={{ danger: true }} confirmLoading={deletingBusy} cancelButtonProps={{ disabled: deletingBusy }} onOk={removeSku}>
      {deleting && <><p>SKU：{deleting.sku}</p><p>将从当前范围的物流费列表中删除整行数据，并清除 {Object.keys(deleting.deletable_versions).length} 个可管理的费用版本（含历史和未来版本）。没有费用版本也可以删除。</p>
        <p>范围：{scope ? scopeName(scope) : '全部授权店铺'}{user.role === 'admin' ? '及通用费用' : '的店铺专用费用（通用费用保留）'}。</p>
        {user.role === 'admin' && <p>清除通用费用也会影响其他使用该通用费用的店铺。</p>}
        <Alert showIcon type="warning" title="删除后该 SKU 不再显示在当前范围的物流费列表中"
          description="刷新或重新导入订单不会使该行重新出现。已有费用版本清除后将重新计算物流费和利润。需要重新维护时，可通过“新增物流费”添加该 SKU。" /></>}
    </Modal>
    {historySku && <FeeHistory key={`${historySku}-${revision}`} sku={historySku} storeId={scope}
      user={user} scopeName={scopeName} onClose={() => setHistorySku(null)} onEdit={original => openEditor({ original })}
      onCopy={copy => openEditor({ copy })} onDeleted={() => { list.reload(); onChanged?.(); }} />}
    <Modal open={editor !== null} title={editor?.original ? '修正物流费版本' : '新增物流费版本'} onCancel={() => !saving && setEditor(null)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={save}>
        <Form.Item label="适用范围" name="store_id" rules={[{ required: true }]}><Select disabled={!!editor?.original} options={[
          ...(user.role === 'admin' ? [{ value: '*', label: '通用 · 所有店铺' }] : []), ...stores.map(store => ({ value: store.id, label: store.name })),
        ]} /></Form.Item>
        <Form.Item label="SKU（精确匹配）" name="sku" rules={[{ required: true, whitespace: true }]}><Input maxLength={120} disabled={!!(editor?.original || editor?.sku || editor?.copy)} /></Form.Item>
        <Form.Item label="生效日期" name="effective_from" rules={[{ required: true }]} extra={editor?.original ? '修正将重算该版本适用期间；新的调价请使用“新增调价”。' : '包含当天，旧版本自动截至前一天；可提前录入未来生效的价格。'}>
          <DatePicker aria-label="物流费版本生效日期" allowClear={false} disabled={!!editor?.original} />
        </Form.Item>
        <Form.Item label="售价 ≤ $9.99：单件物流费 USD" name="low_price_fee" rules={[{ required: true, message: '请填写低价档单件费用' }]}><InputNumber aria-label="低价档单件物流费" stringMode min="0" max="999999999" precision={9} style={{ width: '100%' }} /></Form.Item>
        <Form.Item label="售价 > $9.99：单件物流费 USD" name="high_price_fee" rules={[{ required: true, message: '请填写高价档单件费用' }]}><InputNumber aria-label="高价档单件物流费" stringMode min="0" max="999999999" precision={9} style={{ width: '100%' }} /></Form.Item>
        <Form.Item label="来源 / 备注" name="source"><Input.TextArea maxLength={500} rows={2} /></Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>保存物流费</Button>
      </Form>
    </Modal>
  </>;
}

function FeeHistory({ sku, storeId, user, scopeName, onClose, onEdit, onCopy, onDeleted }: {
  sku: string; storeId?: string; user: User; scopeName: (store: string | null) => string;
  onClose: () => void; onEdit: (fee: Fee) => void; onCopy: (fee: Fee) => void; onDeleted: () => void;
}) {
  const list = usePagedList<Fee>(queryPath('/sales-analysis/fba-fees', { sku, store_id: storeId }));
  const canManage = user.permissions.includes('quotes.manage');
  const [deleting, setDeleting] = useState<Fee | null>(null);
  const [busy, setBusy] = useState(false);
  const { message } = App.useApp();
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api(`/sales-analysis/fba-fees/${deleting.id}`, { method: 'DELETE', body: { revision: deleting.revision } });
      setDeleting(null);
      if (list.data?.items.length === 1 && list.pagination.current > 1) list.pagination.onChange(list.pagination.current - 1);
      else list.reload();
      onDeleted();
      message.success('物流费版本已删除，生效期间和销售分析已更新');
    } catch (cause) { message.error(errorText(cause)); setDeleting(null); list.reload(); }
    finally { setBusy(false); }
  };
  return <Drawer open title={`${sku} · 物流费历史版本`} width={1050} onClose={onClose}>
    <Alert showIcon type="info" title="调价时新增版本，录入错误时修正已有版本" description="生效期间按各适用范围分别计算，包含开始和结束日期。相同日期只能有一个版本；店铺专用版本优先于通用版本。" />
    <ErrorNotice error={list.error} retry={list.reload} />
    <Table<Fee> rowKey="id" loading={list.loading} dataSource={list.data?.items ?? []} pagination={list.pagination} scroll={{ x: 950 }} columns={[
      { title: '适用范围', dataIndex: 'store_id', width: 150, render: scopeName },
      { title: '生效期间', width: 245, render: (_, row) => period(row) },
      { title: '售价 ≤ $9.99 / 件', dataIndex: 'low_price_fee', width: 140, render: usd },
      { title: '售价 > $9.99 / 件', dataIndex: 'high_price_fee', width: 140, render: usd },
      { title: '来源 / 备注', dataIndex: 'source', width: 175 },
      { title: '操作', width: 250, render: (_, row) => canManage && <Space>
        <Button type="link" onClick={() => onCopy(row)}>新增调价</Button>
        {(row.store_id || user.role === 'admin') && <><Button type="link" onClick={() => onEdit(row)}>修正</Button>
          <Button type="link" danger onClick={() => setDeleting(row)}>删除</Button></>}
      </Space> },
    ]} />
    <Modal open={!!deleting} title="删除物流费版本" onCancel={() => !busy && setDeleting(null)}
      closable={!busy} maskClosable={!busy} keyboard={!busy} okText="确认删除" cancelText="取消"
      okButtonProps={{ danger: true }} confirmLoading={busy} cancelButtonProps={{ disabled: busy }} onOk={remove}>
      {deleting && <><p>{deleting.sku} · {scopeName(deleting.store_id)}</p><p>{period(deleting)}</p>
        <p>售价 ≤ $9.99：{usd(deleting.low_price_fee)} / 件；售价 &gt; $9.99：{usd(deleting.high_price_fee)} / 件</p>
        <Alert showIcon type="warning" title="删除后将重新计算适用期间的物流费和利润"
          description="同范围的前一个版本将延续至下一版本生效前；没有前一个版本时，按店铺专用、通用、历史单档的顺序查找适用费用。均无适用费用时将提示缺少物流费。需要恢复时，请重新新增该版本。" /></>}
    </Modal>
  </Drawer>;
}
