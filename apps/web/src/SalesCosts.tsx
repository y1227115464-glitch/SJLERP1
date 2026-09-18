import { useState } from 'react';
import { App, Alert, Button, DatePicker, Drawer, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { api, errorText } from './api';
import { ErrorNotice, usePagedList } from './common';
import { queryPath } from './CatalogShared';
import type { SalesCostRate } from './sales-analysis-types';
import type { Store, User } from './types';
import { FbaFees } from './FbaFees';

type CostForm = Omit<SalesCostRate, 'id' | 'effective_from' | 'commission_rate' | 'revision'> & {
  effective_from: Dayjs; commission_percent: number;
};

export function SalesCosts({ user, stores, selectedStore, sku, initialTab = 'costs', onClose, onChanged }: {
  user: User; stores: Store[]; selectedStore: string; sku?: string; initialTab?: 'costs' | 'fba'; onClose: () => void; onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [search, setSearch] = useState(sku || '');
  const [editor, setEditor] = useState<SalesCostRate | 'new' | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<SalesCostRate | null>(null);
  const [removing, setRemoving] = useState(false);
  const [costRevision, setCostRevision] = useState(0);
  const [form] = Form.useForm<CostForm>();
  const list = usePagedList<SalesCostRate>(queryPath('/sales-analysis/costs', {
    store_id: selectedStore === 'all' ? undefined : selectedStore, q: search,
  }));
  const canManage = user.permissions.includes('quotes.manage');
  const openEditor = (row: SalesCostRate | 'new') => {
    form.resetFields();
    form.setFieldsValue(row === 'new' ? { sku: sku || '', store_id: selectedStore === 'all' ? (user.role === 'admin' ? '*' : undefined) : selectedStore,
      effective_from: dayjs(), product_cost: null, inbound_fee: null, fba_fee: null, commission_percent: 15, source: '' }
      : { ...row, store_id: row.store_id || '*', effective_from: dayjs(row.effective_from), commission_percent: Number(row.commission_rate) * 100 });
    setEditor(row);
  };
  const save = async (values: CostForm) => {
    setSaving(true);
    try {
      const { commission_percent, ...rest } = values;
      await api('/sales-analysis/costs', { method: 'POST', body: { ...rest,
        fba_fee: editor && editor !== 'new' ? editor.fba_fee : null,
        store_id: values.store_id === '*' ? null : values.store_id,
        effective_from: values.effective_from.format('YYYY-MM-DD'),
        commission_rate: (commission_percent / 100).toFixed(6), revision: editor && editor !== 'new' ? editor.revision : 0,
      } });
      setEditor(null); list.reload(); setCostRevision(value => value + 1); onChanged(); message.success('成本已保存，销售分析已更新');
    } catch (error) { message.error(errorText(error)); } finally { setSaving(false); }
  };
  const remove = async () => {
    if (!deleting) return;
    setRemoving(true);
    try {
      await api(`/sales-analysis/costs/${deleting.id}`, { method: 'DELETE', body: { revision: deleting.revision } });
      setDeleting(null);
      if (list.data?.items.length === 1 && list.pagination.current > 1) list.pagination.onChange(list.pagination.current - 1);
      else list.reload();
      setCostRevision(value => value + 1); onChanged();
      message.success('成本与佣金版本已删除，销售分析已更新');
    } catch (cause) { message.error(errorText(cause)); setDeleting(null); list.reload(); }
    finally { setRemoving(false); }
  };
  const unit = (value: string | null) => value == null ? <Tag color="warning">待补充</Tag> : `$${Number(value).toLocaleString('en-US', { maximumFractionDigits: 9 })}`;
  return <Drawer open title="销售分析费用" width={1080} onClose={onClose}>
    <Tabs defaultActiveKey={initialTab} items={[
      { key: 'costs', label: '产品成本与佣金', children: <>
    <Alert showIcon type="info" title="按订单日期使用当时生效的费用" description="店铺专用版本优先于通用版本；CMBQ 尺寸别名统一在 CMBQ-L-250S 维护费用。新增生效日期可保留历史口径，编辑已有版本会重算其适用期间。单件费用单位为 USD；留空表示未知，明确无费用时填 0。" />
    <Space className="analysis-cost-toolbar" wrap><Input.Search aria-label="搜索成本 SKU" placeholder="搜索成本 SKU" defaultValue={search} allowClear onSearch={setSearch} style={{ width: 300 }} />
      {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor('new')}>新增费用版本</Button>}</Space>
    <ErrorNotice error={list.error} retry={list.reload} />
    <Table<SalesCostRate> rowKey="id" dataSource={list.data?.items ?? []} loading={list.loading} pagination={list.pagination} scroll={{ x: 1150 }} columns={[
      { title: 'SKU / 适用范围', width: 210, render: (_, row) => <>{row.sku}<div className="table-subtext">{row.store_id ? stores.find(store => store.id === row.store_id)?.name || '授权店铺' : '通用 · 所有店铺'}</div></> },
      { title: '生效日期', dataIndex: 'effective_from', width: 115 },
      { title: '产品成本及头程 / 件', dataIndex: 'product_cost', render: unit, width: 145 },
      { title: '另计入库费 / 件', dataIndex: 'inbound_fee', render: unit, width: 130 },
      { title: '历史单档 FBA / 件', dataIndex: 'fba_fee', render: unit, width: 150 },
      { title: '佣金率', dataIndex: 'commission_rate', render: value => `${(Number(value) * 100).toFixed(2)}%`, width: 90 },
      { title: '费用来源', dataIndex: 'source', width: 230 },
      { title: '操作', width: 145, fixed: 'right', render: (_, row) => canManage && (row.store_id || user.role === 'admin') && <Space>
        <Button type="link" onClick={() => openEditor(row)}>编辑</Button><Button type="link" danger onClick={() => setDeleting(row)}>删除</Button></Space> },
    ]} />
    <Modal open={!!editor} title={editor === 'new' ? '新增费用版本' : '编辑费用版本'} onCancel={() => !saving && setEditor(null)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={save}>
        <Form.Item label="适用范围" name="store_id" rules={[{ required: true }]}><Select disabled={editor !== 'new'} options={[
          ...(user.role === 'admin' ? [{ value: '*', label: '通用 · 所有店铺' }] : []), ...stores.map(store => ({ value: store.id, label: store.name })),
        ]} /></Form.Item>
        <Form.Item label="店铺 SKU（精确匹配）" name="sku" rules={[{ required: true, whitespace: true }]}><Input maxLength={120} disabled={editor !== 'new'} /></Form.Item>
        <Form.Item label="生效日期" name="effective_from" rules={[{ required: true }]}><DatePicker disabled={editor !== 'new'} allowClear={false} /></Form.Item>
        <Form.Item label="单件产品成本及头程 USD" name="product_cost"><InputNumber stringMode min="0" max="999999999" precision={9} style={{ width: '100%' }} /></Form.Item>
        <Form.Item label="单件另计入库配置费 USD" name="inbound_fee" extra="产品成本已含入库费时填 0，尚未确认时留空。"><InputNumber stringMode min="0" max="999999999" precision={9} style={{ width: '100%' }} /></Form.Item>
        <Form.Item label="历史单档 FBA 派送费 USD" name="fba_fee" extra="新的物流费请在“亚马逊物流费”页签按售价分档维护，此处保留历史值。"><InputNumber disabled stringMode style={{ width: '100%' }} /></Form.Item>
        <Form.Item label="预估佣金率 %" name="commission_percent" rules={[{ required: true }]}><InputNumber min={0} max={100} precision={4} /></Form.Item>
        <Form.Item label="费用来源 / 备注" name="source"><Input.TextArea maxLength={500} rows={2} /></Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>保存费用</Button>
      </Form>
    </Modal>
    <Modal open={!!deleting} title="删除产品成本与佣金版本" onCancel={() => !removing && setDeleting(null)}
      closable={!removing} maskClosable={!removing} keyboard={!removing} okText="确认删除" cancelText="取消"
      okButtonProps={{ danger: true }} confirmLoading={removing} cancelButtonProps={{ disabled: removing }} onOk={remove}>
      {deleting && <><p>{deleting.sku} · {deleting.store_id ? stores.find(store => store.id === deleting.store_id)?.name || '授权店铺' : '通用 · 所有店铺'}</p>
        <p>生效日期：{deleting.effective_from}</p>
        <p>产品成本及头程 / 件：{unit(deleting.product_cost)}；另计入库费 / 件：{unit(deleting.inbound_fee)}</p>
        <p>历史单档 FBA / 件：{unit(deleting.fba_fee)}；佣金率：{(Number(deleting.commission_rate) * 100).toFixed(2)}%</p>
        <Alert showIcon type="warning" title="将删除此版本的全部成本与佣金配置，并重算利润"
          description="删除后按订单日期使用更早的适用版本或通用配置；没有适用成本时，相关成本和利润显示待补充。此版本中保留的历史单档 FBA 费用也会移除，独立维护的亚马逊物流费版本仍保留。需要恢复时，请重新新增该费用版本。" /></>}
    </Modal>
      </> },
      { key: 'fba', label: '亚马逊物流费', children: <FbaFees key={costRevision} user={user} stores={stores} selectedStore={selectedStore} sku={sku} onChanged={onChanged} /> },
    ]} />
  </Drawer>;
}
