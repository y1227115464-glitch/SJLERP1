export type ReportKind = 'sales' | 'ads';
export type ImportResult = { created: number; updated: number; skipped: number; file_duplicates: number };
export type ReportBatch = { id: string; store_id: string; store_name: string; kind: ReportKind; filename: string;
  source_total: number; unique_rows: number; duplicate_count: number; error_count: number; created_at: string;
  confirmed_at: string | null; result: ImportResult | null; counts?: Record<string, number>; verification_token?: string; can_confirm?: boolean };
export type ReportData = { id: string; store_id: string; store_name: string; import_id: string; source_row: number;
  sku: string; asin: string; currency: string | null; [key: string]: string | number | null };
export type PreviewRow = { row: number; action: string; message: string; data: ReportData | null };
export type SummaryGroup = { currency: string | null; rows: number; [key: string]: string | number | null };
