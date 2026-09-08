export interface Product {
  id: string;
  internal_sku: string;
  name: string;
  name_zh: string;
  brand: string;
  category: string;
  specifications: string;
  material: string;
  title: string;
  description: string;
  asin: string;
  fnsku: string;
  image_url: string;
  image_urls: string[];
  bullet_points: string[];
  amazon_url: string;
  sale_price: string | null;
  original_sale_price: string | null;
  currency: string;
  is_active: boolean;
  notes: string;
  review_notes: string[];
  source_data: Record<string, unknown> | null;
  source_filename: string;
  source_row: number | null;
  created_at: string;
  updated_at: string;
}
export interface ProductMeta { brands: string[]; total: number; active: number; needs_review: number }
export interface ProductImportPreview {
  token: string;
  filename: string;
  total: number;
  create_count: number;
  skip_count: number;
  rows: { row: number; internal_sku: string; name: string; action: 'create' | 'skip' | 'error'; review_notes: string[] }[];
  errors: string[];
  warnings: string[];
}
export interface ProductImportResult { created: number; skipped: number; needs_review: number }
export type PriceUnit = 'unknown' | 'cents' | 'dollars';
export interface Supplier {
  id: string; code: string; name: string; contact_name: string; phone: string; email: string;
  address: string; payment_terms: string; notes: string; is_active: boolean;
  created_at: string; updated_at: string;
}
export interface QuoteTier {
  min_quantity: number | null;
  unit_price: string | null;
  tax_inclusive_price: string | null;
  unit: string;
  notes: string;
}
export type TaxStatus = 'unknown' | 'included' | 'excluded' | 'mixed';
export interface SupplierQuote {
  id: string;
  supplier_id: string;
  supplier_name: string;
  product_ids: string[];
  product_names: string[];
  label: string;
  packaging: string;
  currency: string;
  tax_status: TaxStatus;
  includes_shipping: boolean | null;
  includes_labeling: boolean | null;
  labeling_fee: string | null;
  review_status: 'confirmed' | 'needs_review';
  review_notes: string;
  notes: string;
  source_text: string;
  source_reference: string;
  is_active: boolean;
  tiers: QuoteTier[];
  created_at: string;
  updated_at: string;
}
