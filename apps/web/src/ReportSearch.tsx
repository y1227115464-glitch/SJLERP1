import { useState } from 'react';
import { AutoComplete, Button, Space } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useResource } from './common';
import { queryPath, useDebouncedValue } from './CatalogShared';

export type ReportSearchValue = { q: string; sku: string };
type Suggestions = { items: string[]; has_more: boolean };

export function ReportSearch({ route, context, value, onSearch }: {
  route: string;
  context: Record<string, string | undefined>;
  value: ReportSearchValue;
  onSearch: (value: ReportSearchValue) => void;
}) {
  const [draft, setDraft] = useState(value.sku || value.q);
  const [open, setOpen] = useState(false);
  const term = useDebouncedValue(draft.trim());
  const suggestions = useResource<Suggestions>(open ? queryPath(`${route}/suggestions`, { ...context, q: term }) : null);
  const loading = draft.trim() !== term || suggestions.loading;
  const items = loading ? [] : suggestions.data?.items ?? [];
  const emptyMessage = loading ? '正在加载 SKU…' : suggestions.error ? '候选加载失败，可直接确认关键词搜索' : '没有匹配的 SKU，可直接确认关键词搜索';
  const options = items.length ? items.map(sku => ({ value: sku, label: sku })) : [{ value: '', label: emptyMessage, disabled: true }];
  const submit = () => {
    const text = draft.trim();
    setDraft(text);
    setOpen(false);
    onSearch(text && text === value.sku ? { q: '', sku: text } : { q: text, sku: '' });
  };
  return <div className="report-search" onKeyDownCapture={event => { if (event.key === 'Enter' && event.nativeEvent.isComposing) event.stopPropagation(); }}>
    <Space.Compact block><AutoComplete aria-label="搜索报表 SKU 或关键词" placeholder="选择 SKU，或输入关键词后搜索"
      style={{ width: '100%' }} value={draft} open={open} options={options} allowClear maxLength={200}
      defaultActiveFirstOption={false} showSearch={{ filterOption: false }} onOpenChange={setOpen}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onChange={text => { setDraft(text); setOpen(true); }}
      onClear={() => { setDraft(''); onSearch({ q: '', sku: '' }); }}
      onSelect={sku => { setDraft(sku); setOpen(false); onSearch({ q: '', sku }); }}
      onKeyDown={event => { if (event.key === 'Enter' && !event.defaultPrevented && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }}
      popupRender={menu => <>{menu}{!loading && suggestions.data?.has_more && <div className="report-search-hint">仅显示前 50 个 SKU，请继续输入缩小范围</div>}</>} />
      <Button aria-label="确认搜索" icon={<SearchOutlined />} onClick={submit} />
    </Space.Compact>
  </div>;
}
