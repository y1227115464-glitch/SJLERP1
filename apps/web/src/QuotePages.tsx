import { useState } from 'react';
import { Alert, App as AntApp, Button, Card, Col, Descriptions, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Spin, Switch, Table, Tabs, Tag } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { ActiveTag, dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { amountRule, canManageQuotes, canViewQuotes, inclusionLabel, money, queryPath, ReviewTag, SharedCatalogNotice, taxLabels, useCatalogOptions, useDebouncedValue } from './CatalogShared';
import type { Product, QuoteTier, Supplier, SupplierQuote, TaxStatus } from './catalog-types';
import type { User } from './types';

export function QuotesPage({ user }: { user: User }) {
  if (!canViewQuotes(user)) return <Alert type="warning" showIcon title="暂无采购报价查看权限" description="采购报价需要报价查看权限和成本查看权限。" />;
  return <><PageHeading eyebrow="SUPPLIER QUOTATIONS" title="采购报价" description="独立保存供应商报价、阶梯单价与来源原文，确认后再用于采购参考。" /><SharedCatalogNotice description="采购报价为公司共享参考资料，不受店铺或经营日期筛选影响；不会自动写入商品售价或正式核算成本。" /><QuoteCollection user={user} /></>;
}

export function QuoteCollection({ user, supplierId, supplierName }: { user: User; supplierId?: string; supplierName?: string }) {
  // The child is not mounted at all without both permissions; no quote request or source text is loaded.
  return canViewQuotes(user) ? <AuthorizedQuoteCollection user={user} supplierId={supplierId} supplierName={supplierName} /> : <Alert type="info" showIcon title="当前角色可查看供应商档案" description="采购报价及来源原文需报价与成本查看权限。" />;
}

function AuthorizedQuoteCollection({ user, supplierId, supplierName }: { user: User; supplierId?: string; supplierName?: string }) {
  const [query, setQuery] = useState('');
  const [supplierFilter, setSupplierFilter] = useState<string>();
  const [productFilter, setProductFilter] = useState<string>();
  const [review, setReview] = useState<string>();
  const [active, setActive] = useState<string>();
  const [unmatched, setUnmatched] = useState<string>();
  const [referenceVersion, setReferenceVersion] = useState(0);
  const q = useDebouncedValue(query);
  const resource = usePagedList<SupplierQuote>(queryPath('/supplier-quotes', { q, supplier_id: supplierId ?? supplierFilter, product_id: productFilter, review_status: review, is_active: active, unmatched }));
  const suppliers = useCatalogOptions<Supplier>('/suppliers', referenceVersion);
  const products = useCatalogOptions<Product>('/products', referenceVersion);
  const [editing, setEditing] = useState<SupplierQuote | null | undefined>(undefined);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);
  const canManage = canManageQuotes(user);
  const refresh = () => { resource.reload(); setReferenceVersion(value => value + 1); setDetailVersion(value => value + 1); };
  const productOptions = products.data.map(product => ({ value: product.id, label: `${product.internal_sku} · ${product.name_zh || product.name}` }));
  const supplierOptions = suppliers.data.map(supplier => ({ value: supplier.id, label: `${supplier.name}${supplier.is_active ? '' : '（停用）'}` }));
  return <>
    <ErrorNotice error={resource.error} retry={resource.reload} /><ErrorNotice error={suppliers.error || products.error} retry={refresh} />
    <Card className="section-card quote-card" title={supplierName ? `${supplierName} · 采购报价` : '供应商报价档案'} extra={<Space><Button icon={<ReloadOutlined />} onClick={refresh} loading={resource.loading}>刷新</Button>{canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新增报价</Button>}</Space>}>
      <div className="catalog-filter-bar"><Input prefix={<SearchOutlined />} aria-label="搜索采购报价" allowClear value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索报价项目、供应商或商品" className="catalog-search" />{!supplierId && <Select aria-label="筛选供应商" showSearch optionFilterProp="label" allowClear value={supplierFilter} onChange={setSupplierFilter} placeholder="全部供应商" loading={suppliers.loading} options={supplierOptions} style={{ width: 180 }} />}<Select aria-label="筛选关联商品" showSearch optionFilterProp="label" allowClear value={productFilter} onChange={value => { setProductFilter(value); if (value) setUnmatched(undefined); }} placeholder="全部关联商品" loading={products.loading} options={productOptions} style={{ width: 245 }} /><Select aria-label="筛选报价核对状态" allowClear value={review} onChange={setReview} placeholder="全部核对状态" options={[{ value: 'needs_review', label: '待核对' }, { value: 'confirmed', label: '已核对' }]} style={{ width: 145 }} /><Select aria-label="筛选商品匹配状态" allowClear value={unmatched} onChange={value => { setUnmatched(value); if (value === 'true') setProductFilter(undefined); }} placeholder="全部匹配状态" options={[{ value: 'true', label: '未关联商品' }, { value: 'false', label: '已关联商品' }]} style={{ width: 145 }} /><Select aria-label="筛选报价启停状态" allowClear value={active} onChange={setActive} placeholder="全部启停状态" options={[{ value: 'true', label: '启用中' }, { value: 'false', label: '已停用' }]} style={{ width: 145 }} /></div>
      <Table<SupplierQuote> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1320 }} locale={{ emptyText: <EmptyState text="当前筛选下暂无采购报价。未匹配商品的来源报价可先独立保存。" /> }} columns={[
        { title: '报价项目 / 供应商', dataIndex: 'label', width: 260, render: (value: string, quote) => <div className="catalog-wrap"><button className="catalog-title-link" onClick={() => setDetailId(quote.id)}>{value || '未命名报价'}</button><small className="cell-secondary">{quote.supplier_name}</small>{quote.packaging && <small className="cell-secondary">包装：{quote.packaging}</small>}</div> },
        { title: '关联商品', dataIndex: 'product_names', width: 260, render: (names: string[], quote) => names.length ? <div className="quote-linked-products">{names.map((name, index) => <span key={quote.product_ids[index] ?? index}>{name}</span>)}</div> : <Tag color="warning" bordered={false}>未关联商品</Tag> },
        { title: '阶梯报价', dataIndex: 'tiers', width: 300, render: (tiers: QuoteTier[], quote) => <div className="quote-tier-summary">{tiers.map((tier, index) => <div key={index}><span>{tier.min_quantity === null ? '起订量未提供' : `≥ ${tier.min_quantity} ${tier.unit || '单位待确认'}`}</span><strong>{money(tier.unit_price, quote.currency)}{tier.unit_price !== null && tier.unit ? ` / ${tier.unit}` : ''}</strong>{tier.tax_inclusive_price !== null && <small>含税价：{money(tier.tax_inclusive_price, quote.currency)}</small>}</div>)}</div> },
        { title: '税费与服务', dataIndex: 'tax_status', width: 185, render: (status: TaxStatus, quote) => <div className="quote-condition-summary"><span>{taxLabels[status]}</span><small>运费：{inclusionLabel(quote.includes_shipping)}</small><small>贴标：{inclusionLabel(quote.includes_labeling)}</small>{quote.labeling_fee !== null && <small>独立贴标费：{money(quote.labeling_fee, quote.currency)}</small>}</div> },
        { title: '状态', dataIndex: 'review_status', width: 115, render: (value: SupplierQuote['review_status'], quote) => <Space direction="vertical" size={5}><ReviewTag needsReview={value === 'needs_review'} /><ActiveTag active={quote.is_active} /></Space> },
        { title: '操作', key: 'actions', width: 130, render: (_: unknown, quote) => <Space size={0}><Button type="link" onClick={() => setDetailId(quote.id)}>详情</Button>{canManage && <Button type="link" onClick={() => setEditing(quote)}>编辑</Button>}</Space> },
      ]} />
    </Card>
    {detailId && <QuoteDetails key={`${detailId}:${detailVersion}`} id={detailId} canManage={canManage} onClose={() => setDetailId(null)} onEdit={setEditing} />}
    {editing !== undefined && <QuoteEditor quote={editing} defaultSupplierId={supplierId} suppliers={suppliers.data} products={products.data} referencesLoading={suppliers.loading || products.loading} referencesError={suppliers.error || products.error} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); resource.reload(); setDetailVersion(value => value + 1); }} />}
  </>;
}

function QuoteDetails({ id, canManage, onClose, onEdit }: { id: string; canManage: boolean; onClose: () => void; onEdit: (quote: SupplierQuote) => void }) {
  const resource = useResource<SupplierQuote>(`/supplier-quotes/${id}`);
  const quote = resource.data;
  return <Drawer title="采购报价详情" open onClose={onClose} size={920} extra={canManage && quote && <Button icon={<EditOutlined />} onClick={() => onEdit(quote)}>编辑报价</Button>}><ErrorNotice error={resource.error} retry={resource.reload} />{resource.loading && !quote ? <div className="page-loading"><Spin /></div> : quote && <>
    <div className="quote-detail-heading"><Tag>{quote.supplier_name}</Tag><h2>{quote.label || '未命名报价'}</h2><Space><ReviewTag needsReview={quote.review_status === 'needs_review'} /><ActiveTag active={quote.is_active} />{quote.product_ids.length === 0 && <Tag color="warning" bordered={false}>未关联商品</Tag>}</Space></div>
    {quote.review_status === 'needs_review' && <Alert className="page-notice" type="warning" showIcon title="报价需要核对" description={<span className="catalog-prewrap">{quote.review_notes || '请核对商品匹配、数量单位、税况及来源报价。'}</span>} />}
    <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
      { key: 'supplier', label: '供应商', children: quote.supplier_name }, { key: 'currency', label: '报价币种', children: quote.currency },
      { key: 'products', label: '关联商品', span: 2, children: quote.product_names.length ? <div className="quote-linked-products">{quote.product_names.map((name, index) => <span key={index}>{name}</span>)}</div> : '未匹配，待人工确认' },
      { key: 'packaging', label: '包装说明', span: 2, children: <span className="catalog-prewrap">{quote.packaging || '未提供'}</span> },
      { key: 'tax', label: '税况', children: taxLabels[quote.tax_status] }, { key: 'shipping', label: '运费', children: inclusionLabel(quote.includes_shipping) },
      { key: 'label', label: '贴标服务', children: inclusionLabel(quote.includes_labeling) }, { key: 'labelFee', label: '独立贴标费', children: money(quote.labeling_fee, quote.currency) },
    ]} />
    <h3 className="catalog-section-title">阶梯价格</h3><Table<QuoteTier> rowKey={(_, index) => String(index)} size="small" pagination={false} dataSource={quote.tiers} scroll={{ x: 700 }} columns={[
      { title: '起订量', dataIndex: 'min_quantity', render: (value: number | null) => value === null ? '未提供' : value }, { title: '计价单位', dataIndex: 'unit', render: (value: string) => value || '待确认' }, { title: '来源单价', dataIndex: 'unit_price', render: (value: string | null) => money(value, quote.currency) }, { title: '来源含税价', dataIndex: 'tax_inclusive_price', render: (value: string | null) => money(value, quote.currency) }, { title: '档位备注', dataIndex: 'notes', width: 260, render: (value: string) => <span className="catalog-prewrap">{value || '—'}</span> },
    ]} />
    <p className="catalog-field-help">含税价和贴标费按来源独立保留，不自动推算税率，也不叠加到已包含服务的单价中。</p>
    <Tabs items={[
      { key: 'source', label: '来源原文', children: <><Descriptions column={1} size="small" items={[{ key: 'ref', label: '来源编号', children: quote.source_reference || '未填写' }]} /><pre className="quote-source-text">{quote.source_text || '未提供来源原文'}</pre></> },
      { key: 'notes', label: '核对与备注', children: <Descriptions column={1} size="small" items={[{ key: 'review', label: '核对说明', children: <span className="catalog-prewrap">{quote.review_notes || '—'}</span> }, { key: 'notes', label: '内部备注', children: <span className="catalog-prewrap">{quote.notes || '—'}</span> }, { key: 'create', label: '建立时间', children: dateTime(quote.created_at) }, { key: 'update', label: '更新时间', children: dateTime(quote.updated_at) }]} /> },
    ]} />
  </>}</Drawer>;
}

type Inclusion = 'unknown' | 'included' | 'excluded';
const inclusionValue = (value: boolean | null | undefined): Inclusion => value == null ? 'unknown' : value ? 'included' : 'excluded';
const inclusionBoolean = (value: Inclusion): boolean | null => value === 'unknown' ? null : value === 'included';
interface QuoteValues {
  supplier_id: string; product_ids: string[]; label: string; packaging: string; currency: string; tax_status: TaxStatus;
  shipping_selection: Inclusion; labeling_selection: Inclusion; labeling_fee: string | null;
  review_status: SupplierQuote['review_status']; review_notes: string; notes: string; source_text: string; source_reference: string; is_active: boolean; tiers: QuoteTier[];
}
function QuoteEditor({ quote, defaultSupplierId, suppliers, products, referencesLoading, referencesError, onClose, onSaved }: { quote: SupplierQuote | null; defaultSupplierId?: string; suppliers: Supplier[]; products: Product[]; referencesLoading: boolean; referencesError: string; onClose: () => void; onSaved: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('basics');
  const [form] = Form.useForm<QuoteValues>();
  const selectedProducts = Form.useWatch('product_ids', form) as string[] | undefined;
  const reviewStatus = Form.useWatch('review_status', form) as SupplierQuote['review_status'] | undefined;
  const { message } = AntApp.useApp();
  const initial: Partial<QuoteValues> = quote ? { supplier_id: quote.supplier_id, product_ids: quote.product_ids, label: quote.label, packaging: quote.packaging, currency: quote.currency, tax_status: quote.tax_status, shipping_selection: inclusionValue(quote.includes_shipping), labeling_selection: inclusionValue(quote.includes_labeling), labeling_fee: quote.labeling_fee, review_status: quote.review_status, review_notes: quote.review_notes, notes: quote.notes, source_text: quote.source_text, source_reference: quote.source_reference, is_active: quote.is_active, tiers: quote.tiers } : { supplier_id: defaultSupplierId, product_ids: [], currency: 'CNY', tax_status: 'unknown', shipping_selection: 'unknown', labeling_selection: 'unknown', review_status: 'needs_review', is_active: true, tiers: [{ min_quantity: null, unit_price: null, tax_inclusive_price: null, unit: '', notes: '' }] };
  const productOptions = new Map(products.map(product => [product.id, { value: product.id, label: `${product.internal_sku} · ${product.name_zh || product.name}${product.is_active ? '' : '（停用）'}` }]));
  quote?.product_ids.forEach((id, index) => { if (!productOptions.has(id)) productOptions.set(id, { value: id, label: quote.product_names[index] ?? id }); });
  const supplierOptions = new Map(suppliers.map(supplier => [supplier.id, { value: supplier.id, label: `${supplier.name}${supplier.is_active ? '' : '（停用）'}` }]));
  if (quote && !supplierOptions.has(quote.supplier_id)) supplierOptions.set(quote.supplier_id, { value: quote.supplier_id, label: quote.supplier_name });
  const save = async (values: QuoteValues) => {
    const body = { supplier_id: values.supplier_id, product_ids: values.product_ids ?? [], label: values.label?.trim() ?? '', packaging: values.packaging ?? '', currency: values.currency, tax_status: values.tax_status, includes_shipping: inclusionBoolean(values.shipping_selection), includes_labeling: inclusionBoolean(values.labeling_selection), labeling_fee: values.labeling_fee || null, review_status: values.review_status, review_notes: values.review_notes ?? '', notes: values.notes ?? '', source_text: values.source_text ?? '', source_reference: values.source_reference ?? '', is_active: values.is_active, tiers: values.tiers.map(tier => ({ min_quantity: tier.min_quantity ?? null, unit_price: tier.unit_price || null, tax_inclusive_price: tier.tax_inclusive_price || null, unit: tier.unit ?? '', notes: tier.notes ?? '' })) };
    setSaving(true); setError('');
    try { await api(quote ? `/supplier-quotes/${quote.id}` : '/supplier-quotes', { method: quote ? 'PATCH' : 'POST', body }); message.success(quote ? '采购报价已更新' : '采购报价已创建'); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  const inclusionOptions = [{ value: 'unknown', label: '待确认' }, { value: 'included', label: '已包含' }, { value: 'excluded', label: '未包含' }];
  return <Modal title={quote ? '编辑采购报价' : '新增采购报价'} open onCancel={() => { if (!saving) onClose(); }} footer={null} width={1120} styles={{ body: { maxHeight: '78vh', overflowY: 'auto' } }}>
    <ErrorNotice error={error || referencesError} /><Form form={form} layout="vertical" initialValues={initial} onFinish={save} requiredMark="optional" onFinishFailed={({ errorFields }) => { const field = String(errorFields[0]?.name[0]); setTab(field === 'tiers' || ['currency', 'tax_status', 'shipping_selection', 'labeling_selection', 'labeling_fee'].includes(field) ? 'pricing' : ['review_status', 'review_notes', 'notes', 'source_text', 'source_reference'].includes(field) ? 'source' : 'basics'); }}>
      <Tabs activeKey={tab} onChange={setTab} items={[
        { key: 'basics', label: '供应商与商品', forceRender: true, children: <><Row gutter={20}><Col xs={24} sm={12}><Form.Item name="supplier_id" label="供应商" rules={[{ required: true, message: '请选择供应商' }]}><Select showSearch optionFilterProp="label" placeholder="选择供应商" loading={referencesLoading} options={[...supplierOptions.values()]} /></Form.Item></Col><Col xs={24} sm={12}><Form.Item name="label" label="报价项目名称" rules={[{ required: true, whitespace: true, message: '请填写报价项目名称' }, { max: 200, message: '最多 200 字符' }]}><Input maxLength={200} placeholder="来源报价中的商品或包装名称" /></Form.Item></Col></Row><Form.Item name="product_ids" label="关联公司商品" rules={[{ type: 'array', max: 200, message: '最多关联 200 个商品' }]} extra="可关联多个商品。没有确定匹配关系时保留为空，不凭名称猜测。"><Select mode="multiple" showSearch optionFilterProp="label" loading={referencesLoading} options={[...productOptions.values()]} placeholder="搜索内部 SKU 或商品名称，可多选" className="quote-product-select" /></Form.Item>{!selectedProducts?.length && <Alert className="page-notice" type="warning" showIcon title="此报价尚未关联商品" description="可以先独立保存，之后在未关联商品筛选中补充匹配。" />}<Form.Item name="packaging" label="包装说明" rules={[{ max: 500, message: '最多 500 字符' }]}><Input.TextArea rows={3} placeholder="例如：每包数量、外箱装箱数及包装方式" maxLength={500} /></Form.Item><Form.Item name="is_active" label="报价状态" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item></> },
        { key: 'pricing', label: '阶梯价格与服务', forceRender: true, children: <><Alert className="page-notice" type="info" showIcon title="按来源逐档记录，不自动计算缺失价格" description="起订量未提供时留空；来源单价与来源含税价分别保存。独立贴标费不自动叠加至已含贴标的单价。" /><Row gutter={20}><Col xs={24} sm={6}><Form.Item name="currency" label="报价币种" rules={[{ required: true, message: '请选择币种' }]}><Select options={[{ value: 'CNY', label: 'CNY 人民币' }, { value: 'USD', label: 'USD 美元' }]} /></Form.Item></Col><Col xs={24} sm={6}><Form.Item name="tax_status" label="税况"><Select options={Object.entries(taxLabels).map(([value, label]) => ({ value, label }))} /></Form.Item></Col><Col xs={12} sm={6}><Form.Item name="shipping_selection" label="是否包含运费"><Select options={inclusionOptions} /></Form.Item></Col><Col xs={12} sm={6}><Form.Item name="labeling_selection" label="是否包含贴标"><Select options={inclusionOptions} /></Form.Item></Col></Row><Form.Item name="labeling_fee" label="独立贴标费" rules={[amountRule]} extra="仅填写来源单独列出的费用；未明确金额时留空。"><Input inputMode="decimal" placeholder="未提供时留空" style={{ maxWidth: 260 }} /></Form.Item>
          <Form.List name="tiers" rules={[{ validator: async (_, tiers) => { if (!tiers?.length) throw new Error('至少保留一个报价档位，未知金额可留空'); if (tiers.length > 30) throw new Error('最多 30 个报价档位'); const quantities = tiers.map((tier: QuoteTier) => tier.min_quantity).filter((value: number | null) => value != null); if (new Set(quantities).size !== quantities.length) throw new Error('各档位的起订量不能重复'); } }]}>{(fields, { add, remove }, { errors }) => <><div className="quote-tiers-editor">{fields.map((field, index) => <div className="quote-tier-editor" key={field.key}><div className="quote-tier-heading"><strong>第 {index + 1} 档</strong>{fields.length > 1 && <Popconfirm title="移除此报价档位？" okText="移除" cancelText="取消" onConfirm={() => remove(field.name)}><Button danger type="text" aria-label={`移除第 ${index + 1} 档`} icon={<DeleteOutlined />}>移除</Button></Popconfirm>}</div><Row gutter={16}><Col xs={12} sm={6}><Form.Item name={[field.name, 'min_quantity']} label="起订量" rules={[{ type: 'number', min: 1, max: 2147483647, message: '请输入 1–2147483647 的整数或留空' }, { validator: (_: unknown, value: number | null) => value == null || Number.isInteger(value) ? Promise.resolve() : Promise.reject(new Error('起订量必须为整数')) }]}><InputNumber min={1} max={2147483647} controls={false} placeholder="未提供" style={{ width: '100%' }} /></Form.Item></Col><Col xs={12} sm={6}><Form.Item name={[field.name, 'unit']} label="计价单位" rules={[{ max: 40, message: '最多 40 字符' }]}><Input placeholder="包 / 套 / 件" maxLength={40} /></Form.Item></Col><Col xs={12} sm={6}><Form.Item name={[field.name, 'unit_price']} label="来源单价" rules={[amountRule]}><Input inputMode="decimal" placeholder="未知时留空" /></Form.Item></Col><Col xs={12} sm={6}><Form.Item name={[field.name, 'tax_inclusive_price']} label="来源含税价" rules={[amountRule]}><Input inputMode="decimal" placeholder="未提供时留空" /></Form.Item></Col></Row><Form.Item name={[field.name, 'notes']} label="档位备注" rules={[{ max: 2000, message: '最多 2000 字符' }]}><Input.TextArea autoSize={{ minRows: 1, maxRows: 3 }} placeholder="保留该档位的差异、适用规格及核对说明" /></Form.Item></div>)}</div><Form.ErrorList errors={errors} /><Button type="dashed" block icon={<PlusOutlined />} disabled={fields.length >= 30} onClick={() => add({ min_quantity: null, unit_price: null, tax_inclusive_price: null, unit: '', notes: '' })}>添加报价档位（{fields.length} / 30）</Button></>}</Form.List>
        </> },
        { key: 'source', label: '来源原文与核对', forceRender: true, children: <><Form.Item name="source_reference" label="来源编号" rules={[{ max: 2000, message: '最多 2000 字符' }]}><Input.TextArea rows={2} placeholder="原始供货表或报价记录的定位编号" /></Form.Item><Form.Item name="source_text" label="来源原文" rules={[{ max: 20000, message: '最多 20000 字符' }]} extra="保留原始报价文字，后续可对照阶梯、包装、税费与服务条款。"><Input.TextArea rows={7} /></Form.Item><Form.Item name="review_status" label="核对状态" rules={[{ required: true, message: '请选择核对状态' }]}><Select options={[{ value: 'needs_review', label: '待核对' }, { value: 'confirmed', label: '已核对' }]} style={{ maxWidth: 250 }} /></Form.Item>{reviewStatus === 'confirmed' && <p className="catalog-field-help">标为已核对表示已人工确认当前来源与字段；不会生成正式采购成本。</p>}<Form.Item name="review_notes" label="核对说明" rules={[{ max: 20000, message: '最多 20000 字符' }]}><Input.TextArea rows={4} placeholder="待确认的价格、计价单位、税况或商品匹配关系" /></Form.Item><Form.Item name="notes" label="内部备注" rules={[{ max: 20000, message: '最多 20000 字符' }]}><Input.TextArea rows={3} /></Form.Item></> },
      ]} />
      <div className="form-footer"><Button disabled={saving} onClick={onClose}>取消</Button><Button type="primary" htmlType="submit" loading={saving} disabled={referencesLoading || !!referencesError}>保存报价</Button></div>
    </Form>
  </Modal>;
}
