export type SalesAnalysisRow = {
  key: string; store_id: string; store_name: string; sku: string; quantity: number;
  product_cost: string | null; fba_fee: string | null; commission: string | null;
  sales_profit: string | null; sales: string | null; sales_profit_rate: string | null;
  ad_spend: string | null; actual_profit: string | null; actual_profit_rate: string | null;
  issues: string[]; source_skus: string[]; sales_rows: number; ad_rows: number; cost_versions: number;
};
export type SalesAnalysisPeriod = SalesAnalysisRow & { period_start: string; period_end: string };
export type SalesAnalysisPeriods = { items: SalesAnalysisPeriod[]; total: number };
export type AnalysisTotals = Omit<SalesAnalysisRow, 'key' | 'store_id' | 'store_name' | 'issues' | 'source_skus' | 'sales_rows' | 'ad_rows' | 'cost_versions'> & { incomplete_rows: number };
export type SalesAnalysis = { items: SalesAnalysisRow[]; total: number; totals: AnalysisTotals;
  excluded: { unsupported_sales_rows: number; unsupported_ad_rows: number;
    unallocated_brand_campaigns: { store_id: string; campaign: string; currency: string; spend: string }[] }; currency: string };
export type SalesCostRate = { id: string; store_id: string | null; sku: string; effective_from: string;
  product_cost: string | null; inbound_fee: string | null; fba_fee: string | null;
  commission_rate: string; source: string; revision: number };
