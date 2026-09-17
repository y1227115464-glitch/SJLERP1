import type { ReportData } from './report-types';

export function ReportProducts({ data }: { data: ReportData | null }) {
  if (data?.ad_type !== 'sponsored_brands') return <>{data?.sku || '—'}<div className="table-subtext">{data?.asin}</div></>;
  if (!data.allocation_products?.length) return <span className="table-subtext">未配置商品分摊</span>;
  return <>{data.allocation_products.map(item => <div key={item.sku} title={item.name || undefined} style={{ marginBottom: 8 }}>
    <div>{item.sku} · {Number(item.percentage)}%</div>
    <div className="table-subtext">{item.asins.length ? item.asins.join(' / ') : 'ASIN 未匹配'}</div>
  </div>)}</>;
}
