import { useState } from 'react';
import { Alert, App as AntApp, Button, Card, Col, Descriptions, Drawer, Form, Input, Modal, Row, Select, Space, Spin, Switch, Table, Tabs, Tag, Upload } from 'antd';
import { CheckCircleOutlined, EditOutlined, FileTextOutlined, ImportOutlined, LinkOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons';
import { api, errorText } from './api';
import { ActiveTag, dateTime, EmptyState, ErrorNotice, PageHeading, usePagedList, useResource } from './common';
import { amountRule, money, multilineRule, multilineToArray, ProductImage, queryPath, ReviewTag, safeSourceUrl, SharedCatalogNotice, urlRule, useDebouncedValue } from './CatalogShared';
import type { Product, ProductImportPreview, ProductImportResult, ProductMeta, PriceUnit } from './catalog-types';
import type { User } from './types';

export function ProductsPage({ user }: { user: User }) {
  const canManage = user.permissions.includes('products.manage');
  const [query, setQuery] = useState('');
  const [brand, setBrand] = useState<string>();
  const [active, setActive] = useState<string>();
  const [review, setReview] = useState<string>();
  const q = useDebouncedValue(query);
  const resource = usePagedList<Product>(queryPath('/products', { q, brand, is_active: active, needs_review: review }));
  const meta = useResource<ProductMeta>('/products/meta');
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Product | null | undefined>(undefined);
  const [importOpen, setImportOpen] = useState(false);
  const [detailVersion, setDetailVersion] = useState(0);
  const refresh = () => { resource.reload(); meta.reload(); setDetailVersion(version => version + 1); };
  return <>
    <PageHeading eyebrow="PRODUCT CATALOG" title="商品管理" description="维护公司商品档案、参考标识与图片，逐项核对来源资料。" extra={canManage && <Space wrap><Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入商品 CSV</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing(null)}>新增商品</Button></Space>} />
    <SharedCatalogNotice description="商品为公司共享档案，不按店铺或经营日期筛选。ASIN / FNSKU 暂作来源参考，尚未建立店铺 Seller SKU 映射。" />
    <ErrorNotice error={meta.error} retry={meta.reload} />
    <div className="summary-strip catalog-summary"><div><span>全部商品</span><strong>{meta.data?.total ?? '—'}</strong><small>项</small></div><div><span>启用中</span><strong>{meta.data?.active ?? '—'}</strong><small>项</small></div><div><span>待核对</span><strong>{meta.data?.needs_review ?? '—'}</strong><small>项</small></div><p>售价与采购报价、核算成本分别维护。</p></div>
    <ErrorNotice error={resource.error} retry={resource.reload} />
    <Card className="section-card" title="公司商品档案" extra={<Button icon={<ReloadOutlined />} onClick={refresh} loading={resource.loading}>刷新</Button>}>
      <div className="catalog-filter-bar"><Input allowClear prefix={<SearchOutlined />} aria-label="搜索商品" placeholder="搜索品名、内部 SKU、ASIN 或 FNSKU" value={query} onChange={event => setQuery(event.target.value)} className="catalog-search" /><Select aria-label="筛选品牌" allowClear placeholder="全部品牌" value={brand} onChange={setBrand} loading={meta.loading} options={(meta.data?.brands ?? []).map(value => ({ value, label: value }))} style={{ minWidth: 160 }} /><Select aria-label="筛选商品启停状态" allowClear placeholder="全部状态" value={active} onChange={setActive} options={[{ value: 'true', label: '启用中' }, { value: 'false', label: '已停用' }]} style={{ minWidth: 125 }} /><Select aria-label="筛选商品核对状态" allowClear placeholder="全部核对状态" value={review} onChange={setReview} options={[{ value: 'true', label: '待核对' }, { value: 'false', label: '已核对' }]} style={{ minWidth: 145 }} /></div>
      <Table<Product> rowKey="id" dataSource={resource.data?.items ?? []} loading={resource.loading} pagination={resource.pagination} scroll={{ x: 1350 }} locale={{ emptyText: <EmptyState text={q || brand || active || review ? '没有匹配的商品，请调整筛选条件。' : '还没有商品档案，可新增或导入商品 CSV。'} /> }} columns={[
        { title: '商品 / 内部 SKU', dataIndex: 'name', width: 390, render: (_: string, product) => <div className="catalog-product-cell"><ProductImage url={product.image_url} name={product.name} /><div><button className="catalog-title-link" onClick={() => setDetailId(product.id)}>{product.name_zh || product.name}</button>{product.name_zh && <div className="product-name-en">{product.name}</div>}<small className="cell-secondary mono">{product.internal_sku}</small></div></div> },
        { title: '品牌 / 分类', dataIndex: 'brand', width: 150, render: (value: string, product) => <div>{value || '—'}<small className="cell-secondary">{product.category || '未分类'}</small></div> },
        { title: '规格 / 材质', dataIndex: 'specifications', width: 190, render: (value: string, product) => <div className="catalog-wrap">{value || '—'}<small className="cell-secondary">{product.material || '材质未填写'}</small></div> },
        { title: '来源参考标识', dataIndex: 'asin', width: 165, render: (value: string, product) => <div className="identifier-cell"><span><b>ASIN</b>{value || '—'}</span><span><b>FNSKU</b>{product.fnsku || '—'}</span></div> },
        { title: '参考售价', dataIndex: 'sale_price', width: 145, render: (value: string | null, product) => <div>{money(value, product.currency)}<small className="cell-secondary">非采购成本</small></div> },
        { title: '状态', dataIndex: 'is_active', width: 110, render: (value: boolean, product) => <Space direction="vertical" size={5}><ActiveTag active={value} /><ReviewTag needsReview={product.review_notes.length > 0} /></Space> },
        { title: '操作', key: 'actions', width: 140, render: (_: unknown, product) => <Space size={0}><Button type="link" onClick={() => setDetailId(product.id)}>详情</Button>{canManage && <Button type="link" onClick={() => setEditing(product)}>编辑</Button>}</Space> },
      ]} />
    </Card>
    {detailId && <ProductDetails key={`${detailId}:${detailVersion}`} id={detailId} canManage={canManage} onClose={() => setDetailId(null)} onEdit={setEditing} />}
    {editing !== undefined && <ProductEditor product={editing} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); refresh(); }} />}
    {importOpen && <ProductImportModal onClose={() => setImportOpen(false)} onImported={refresh} />}
  </>;
}

function ProductDetails({ id, canManage, onClose, onEdit }: { id: string; canManage: boolean; onClose: () => void; onEdit: (product: Product) => void }) {
  const resource = useResource<Product>(`/products/${id}`);
  const product = resource.data;
  const urls = product ? Array.from(new Set([product.image_url, ...product.image_urls])).filter(url => safeSourceUrl(url)) : [];
  return <Drawer title="商品详情" open onClose={onClose} size={940} extra={canManage && product && <Button icon={<EditOutlined />} onClick={() => onEdit(product)}>编辑商品</Button>}>
    <ErrorNotice error={resource.error} retry={resource.reload} />{resource.loading && !product ? <div className="page-loading"><Spin /></div> : product && <>
      <div className="product-detail-heading"><ProductImage url={product.image_url} name={product.name} size={112} preview /><div><Tag>{product.brand || '未填写品牌'}</Tag><h2>{product.name_zh || product.name}</h2>{product.name_zh && <p>{product.name}</p>}<span className="mono">{product.internal_sku}</span><Space size={4} wrap className="product-detail-tags"><ActiveTag active={product.is_active} /><ReviewTag needsReview={product.review_notes.length > 0} /></Space></div></div>
      {product.review_notes.length > 0 && <Alert className="page-notice" type="warning" showIcon title="这份商品资料仍有待核对项" description={<ul className="catalog-note-list">{product.review_notes.map((note, index) => <li key={index}>{note}</li>)}</ul>} />}
      <Tabs items={[
        { key: 'overview', label: '档案与规格', children: <><Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
          { key: 'name', label: '原商品名称', children: <span className="catalog-wrap">{product.name}</span>, span: 2 },
          { key: 'name_zh', label: '中文名称', children: product.name_zh || '—', span: 2 },
          { key: 'category', label: '分类', children: product.category || '—' }, { key: 'material', label: '材质', children: product.material || '—' },
          { key: 'spec', label: '规格', children: <span className="catalog-prewrap">{product.specifications || '—'}</span>, span: 2 },
          { key: 'asin', label: 'ASIN（参考）', children: product.asin || '—' }, { key: 'fnsku', label: 'FNSKU（参考）', children: product.fnsku || '—' },
          { key: 'price', label: '参考售价', children: money(product.sale_price, product.currency) }, { key: 'original_price', label: '参考原价', children: money(product.original_sale_price, product.currency) },
          { key: 'amazon', label: '亚马逊链接', span: 2, children: safeSourceUrl(product.amazon_url) ? <a href={product.amazon_url} target="_blank" rel="noopener noreferrer">打开来源商品页面 <LinkOutlined /></a> : '未填写' },
          { key: 'notes', label: '内部备注', children: <span className="catalog-prewrap">{product.notes || '—'}</span>, span: 2 },
        ]} /><p className="catalog-field-help">售价仅用于商品参考；采购报价与核算成本单独管理。参考标识尚未绑定店铺 Seller SKU。</p>{urls.length > 0 && <div className="product-gallery">{urls.map(url => <ProductImage key={url} url={url} name={product.name} size={140} preview />)}</div>}</> },
        { key: 'listing', label: '标题与描述', children: <div className="catalog-copy"><h3>商品标题</h3><p>{product.title || '未填写'}</p><h3>卖点</h3>{product.bullet_points.length ? <ul>{product.bullet_points.map((point, index) => <li key={index}>{point}</li>)}</ul> : <p className="subtle-text">未填写卖点</p>}<h3>商品描述</h3><p className="catalog-prewrap">{product.description || '未填写'}</p></div> },
        { key: 'source', label: '导入来源与原值', children: <><Alert className="page-notice" type="info" showIcon title="以下为来源文件原始字段" description="stock、monthly_sales 等字段仅为历史来源值，不代表 ERP 当前库存或指定期间销量。价格原值的单位以导入时选项及核对记录为准。" /><Descriptions size="small" column={1} items={[{ key: 'source', label: '来源文件', children: product.source_filename || '手工建立' }, { key: 'row', label: '文件行号', children: product.source_row ?? '—' }, { key: 'created', label: '建立时间', children: dateTime(product.created_at) }, { key: 'updated', label: '最后更新', children: dateTime(product.updated_at) }]} />{product.source_data ? <div className="source-data-table">{Object.entries(product.source_data).map(([key, value]) => <div className="source-data-row" key={key}><strong>{key}</strong><span className="catalog-prewrap">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</span></div>)}</div> : <EmptyState text="此商品为手工建立，暂无原始导入字段。" />}</> },
      ]} />
    </>}
  </Drawer>;
}

interface ProductValues extends Omit<Product, 'id' | 'created_at' | 'updated_at' | 'source_data' | 'source_filename' | 'source_row' | 'image_urls' | 'bullet_points' | 'review_notes'> {
  image_urls_text: string; bullet_points_text: string; review_notes_text: string;
}
function ProductEditor({ product, onClose, onSaved }: { product: Product | null; onClose: () => void; onSaved: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('basics');
  const [form] = Form.useForm<ProductValues>();
  const { message } = AntApp.useApp();
  const save = async (values: ProductValues) => {
    const { image_urls_text, bullet_points_text, review_notes_text } = values;
    const fields = Object.fromEntries(['internal_sku', 'name', 'name_zh', 'brand', 'category', 'specifications', 'material', 'title', 'description', 'asin', 'fnsku', 'image_url', 'amazon_url', 'currency', 'is_active', 'notes'].map(key => [key, values[key as keyof ProductValues]]));
    const body = { ...fields, internal_sku: values.internal_sku.trim(), name: values.name.trim(), image_urls: multilineToArray(image_urls_text), bullet_points: multilineToArray(bullet_points_text), review_notes: multilineToArray(review_notes_text), sale_price: values.sale_price || null, original_sale_price: values.original_sale_price || null };
    setSaving(true); setError('');
    try { await api(product ? `/products/${product.id}` : '/products', { method: product ? 'PATCH' : 'POST', body }); message.success(product ? '商品档案已更新' : '商品已创建'); onSaved(); }
    catch (cause) { setError(errorText(cause)); } finally { setSaving(false); }
  };
  const initial = product ? { ...product, image_urls_text: product.image_urls.join('\n'), bullet_points_text: product.bullet_points.join('\n'), review_notes_text: product.review_notes.join('\n') } : { currency: 'USD', is_active: true, image_urls_text: '', bullet_points_text: '', review_notes_text: '' };
  const textField = (name: keyof ProductValues, label: string, max: number, placeholder?: string) => <Form.Item name={name} label={label} rules={[{ max, message: `最多 ${max} 字符` }]}><Input placeholder={placeholder} maxLength={max} /></Form.Item>;
  return <Modal title={product ? '编辑商品档案' : '新增商品档案'} open onCancel={() => { if (!saving) onClose(); }} footer={null} width={990} styles={{ body: { maxHeight: '76vh', overflowY: 'auto' } }}>
    <ErrorNotice error={error} /><Form form={form} layout="vertical" initialValues={initial} onFinish={save} requiredMark="optional" onFinishFailed={({ errorFields }) => {
      const field = errorFields[0]?.name[0];
      setTab(['title', 'description', 'bullet_points_text', 'image_url', 'image_urls_text', 'amazon_url'].includes(String(field)) ? 'listing' : ['sale_price', 'original_sale_price', 'currency', 'review_notes_text', 'notes'].includes(String(field)) ? 'review' : 'basics');
    }}>
      <Tabs activeKey={tab} onChange={setTab} items={[
        { key: 'basics', label: '基本信息', forceRender: true, children: <><Row gutter={20}><Col xs={24} sm={12}><Form.Item name="internal_sku" label="内部 SKU" rules={[{ required: true, whitespace: true, message: '请输入内部 SKU' }, { max: 120, message: '最多 120 字符' }]}><Input maxLength={120} placeholder="公司内部唯一商品编码" /></Form.Item></Col><Col xs={24} sm={12}>{textField('brand', '品牌', 120)}</Col></Row><Form.Item name="name" label="商品名称" rules={[{ required: true, whitespace: true, message: '请输入商品名称' }, { max: 500, message: '最多 500 字符' }]}><Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={500} placeholder="保留完整英文或原商品名称" /></Form.Item>{textField('name_zh', '中文名称', 200)}<Row gutter={20}><Col xs={24} sm={12}>{textField('category', '分类', 120)}</Col><Col xs={24} sm={12}>{textField('material', '材质', 120)}</Col></Row><Form.Item name="specifications" label="规格" rules={[{ max: 2000, message: '最多 2000 字符' }]}><Input.TextArea rows={3} maxLength={2000} placeholder="尺寸、组合数量、颜色或包装规格" /></Form.Item><Row gutter={20}><Col xs={24} sm={12}>{textField('asin', 'ASIN（来源参考）', 40)}</Col><Col xs={24} sm={12}>{textField('fnsku', 'FNSKU（来源参考）', 40)}</Col></Row><p className="catalog-field-help">参考标识不会自动建立店铺商品映射。同一品牌也可能由多个店铺经营。</p><Form.Item name="is_active" label="商品状态" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item></> },
        { key: 'listing', label: '图片与文案', forceRender: true, children: <><Form.Item name="image_url" label="主图链接" rules={[urlRule, { max: 2000, message: '链接最多 2000 字符' }]}><Input placeholder="https://…" /></Form.Item><Form.Item name="image_urls_text" label="其他图片链接" extra="每行一条 http 或 https 链接，仅引用来源图片。" rules={[multilineRule(200, 2000), { validator: (_: unknown, value: string) => multilineToArray(value).every(url => url.length <= 2000 && safeSourceUrl(url)) ? Promise.resolve() : Promise.reject(new Error('请检查图片链接：每行一条有效 http/https URL，最多 2000 字符')) }]}><Input.TextArea rows={3} /></Form.Item><Form.Item name="amazon_url" label="亚马逊商品链接" rules={[urlRule, { max: 2000, message: '链接最多 2000 字符' }]}><Input placeholder="https://www.amazon.com/…" /></Form.Item><Form.Item name="title" label="Listing 标题" rules={[{ max: 20000, message: '最多 20000 字符' }]}><Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} /></Form.Item><Form.Item name="bullet_points_text" label="卖点" rules={[multilineRule(100, 20000)]} extra="每行一条卖点，保存后按条目保留。"><Input.TextArea rows={5} /></Form.Item><Form.Item name="description" label="商品描述" rules={[{ max: 20000, message: '最多 20000 字符' }]}><Input.TextArea rows={5} /></Form.Item></> },
        { key: 'review', label: '售价与核对', forceRender: true, children: <><Alert className="page-notice" type="info" showIcon title="这里维护商品参考售价" description="采购报价和核算成本独立维护。来源价格单位未确认时，请留空并保留待核对说明。" /><Row gutter={20}><Col xs={24} sm={8}><Form.Item name="currency" label="售价币种" rules={[{ required: true, message: '请选择币种' }]}><Select options={[{ value: 'USD', label: 'USD 美元' }, { value: 'CNY', label: 'CNY 人民币' }]} /></Form.Item></Col><Col xs={24} sm={8}><Form.Item name="sale_price" label="参考售价" rules={[amountRule]}><Input inputMode="decimal" placeholder="未确认时留空" /></Form.Item></Col><Col xs={24} sm={8}><Form.Item name="original_sale_price" label="参考原价" rules={[amountRule]}><Input inputMode="decimal" placeholder="未提供时留空" /></Form.Item></Col></Row><Form.Item name="review_notes_text" label="待核对说明" rules={[multilineRule(100, 2000)]} extra="每行一项。完成核对后移除对应项；全部清空表示该商品已人工核对。"><Input.TextArea rows={5} placeholder="例如：规格与标题不一致，需要核对原始资料" /></Form.Item><Form.Item name="notes" label="内部备注" rules={[{ max: 20000, message: '最多 20000 字符' }]}><Input.TextArea rows={4} /></Form.Item></> },
      ]} />
      <div className="form-footer"><Button onClick={onClose} disabled={saving}>取消</Button><Button type="primary" htmlType="submit" loading={saving}>保存商品</Button></div>
    </Form>
  </Modal>;
}

function ProductImportModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [unit, setUnit] = useState<PriceUnit>('unknown');
  const [preview, setPreview] = useState<ProductImportPreview | null>(null);
  const [result, setResult] = useState<ProductImportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState('');
  const { message } = AntApp.useApp();
  const runPreview = async () => {
    if (!file) return;
    setLoading(true); setError(''); setPreview(null);
    const body = new FormData(); body.append('file', file); body.append('price_unit', unit);
    try { setPreview(await api<ProductImportPreview>('/products/import/preview', { method: 'POST', body })); }
    catch (cause) { setError(errorText(cause)); } finally { setLoading(false); }
  };
  const confirm = async () => {
    if (!preview || preview.create_count === 0) return;
    setConfirming(true); setError('');
    try { setResult(await api<ProductImportResult>('/products/import/confirm', { method: 'POST', body: { token: preview.token } })); onImported(); message.success('商品导入已完成'); }
    catch (cause) { setError(errorText(cause)); } finally { setConfirming(false); }
  };
  const blocked = !!preview && (preview.errors.length > 0 || preview.rows.some(row => row.action === 'error'));
  const alreadyExists = !!preview && !blocked && preview.create_count === 0;
  return <Modal title="导入商品 CSV" open onCancel={() => { if (!loading && !confirming) onClose(); }} footer={null} width={1000} styles={{ body: { maxHeight: '76vh', overflowY: 'auto' } }}>
    <ErrorNotice error={error} />
    {result ? <div className="import-result"><CheckCircleOutlined /><h2>商品资料已归档</h2><p>新增 {result.created} 项 · 跳过 {result.skipped} 项 · 待核对 {result.needs_review} 项</p><p className="subtle-text">请从商品列表的「待核对」筛选继续核对规格、价格单位与参考标识。</p><Button type="primary" onClick={onClose}>返回商品档案</Button></div> : <>
      <Alert className="page-notice" type="info" showIcon title="先预览，再确认导入" description="支持当前商品 CSV 格式（UTF-8 编码，最多 2000 行）。已有内部 SKU 会跳过，不覆盖已维护资料。原始字段与待核对事项会保留。" />
      <div className="import-controls"><Upload accept=".csv,text/csv" beforeUpload={value => { setFile(value); setPreview(null); setError(''); return false; }} maxCount={1} fileList={file ? [{ uid: 'product-csv', name: file.name, status: 'done' }] : []} onRemove={() => { setFile(null); setPreview(null); return true; }} disabled={loading || confirming}><Button icon={<UploadOutlined />}>选择商品 CSV</Button></Upload><div><label htmlFor="product-price-unit">来源价格单位</label><Select id="product-price-unit" value={unit} onChange={value => { setUnit(value); setPreview(null); }} disabled={loading || confirming} style={{ width: 260 }} options={[{ value: 'unknown', label: '单位未确认 · 仅保留来源原值' }, { value: 'cents', label: '分 · 100 分 = 1 美元' }, { value: 'dollars', label: '美元 · 直接保留为售价' }]} /></div><Button icon={<FileTextOutlined />} type="primary" loading={loading} disabled={!file || confirming} onClick={runPreview}>预览导入</Button></div>
      {unit === 'unknown' && <p className="catalog-field-help">价格单位未知时，参考售价留空并标记待核对，原始价格值仍会归档。</p>}
      {alreadyExists && <Alert className="page-notice" type="success" showIcon title="全部商品已存在，无需再次导入" description="原有商品与人工编辑保持不变，可关闭预览后查看商品档案。" />}
      {preview && <><div className="summary-strip catalog-summary"><div><span>文件行数</span><strong>{preview.total}</strong></div><div><span>预计新增</span><strong>{preview.create_count}</strong></div><div><span>已存在跳过</span><strong>{preview.skip_count}</strong></div></div>{preview.errors.length > 0 && <Alert className="page-notice" type="error" showIcon title="请先修正以下错误再重新预览" description={<ul className="catalog-note-list">{preview.errors.map((item, index) => <li key={index}>{item}</li>)}</ul>} />}{preview.warnings.length > 0 && <Alert className="page-notice" type="warning" showIcon title="导入提醒" description={<ul className="catalog-note-list">{preview.warnings.map((item, index) => <li key={index}>{item}</li>)}</ul>} />}
        <Table<ProductImportPreview['rows'][number]> size="small" rowKey="row" dataSource={preview.rows} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: total => `共 ${total} 行` }} scroll={{ x: 750 }} columns={[
          { title: '行号', dataIndex: 'row', width: 65 }, { title: '内部 SKU', dataIndex: 'internal_sku', width: 145 }, { title: '商品名称', dataIndex: 'name', width: 280, render: (value: string) => <span className="catalog-wrap">{value}</span> }, { title: '处理方式', dataIndex: 'action', width: 100, render: (value: 'create' | 'skip' | 'error') => <Tag color={value === 'create' ? 'success' : value === 'error' ? 'error' : 'default'}>{value === 'create' ? '新增' : value === 'skip' ? '跳过' : '错误'}</Tag> }, { title: '待核对事项', dataIndex: 'review_notes', render: (notes: string[]) => notes.length ? <ul className="catalog-note-list">{notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : '—' },
        ]} />
      </>}
      <div className="form-footer"><Button disabled={loading || confirming} onClick={onClose}>取消</Button><Button type="primary" disabled={!preview || blocked || alreadyExists || loading} loading={confirming} onClick={confirm}>确认导入{preview ? `（新增 ${preview.create_count} 项）` : ''}</Button></div>
    </>}
  </Modal>;
}
