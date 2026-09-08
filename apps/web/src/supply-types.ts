export interface Warehouse { id: string; code: string; name: string; kind: 'domestic' | 'overseas' | 'fba'; address: string; is_active: boolean }
export interface PurchaseLine { id: string; product_id: string; product_name: string; internal_sku: string; quantity: number; received_quantity: number; cancelled_quantity: number; unit_price?: string; allocated_quantity?: number; unallocated_quantity?: number }
export interface PurchaseOrder {
  id: string; number: string; store_id: string; store_name: string; supplier_id: string; supplier_name: string;
  status: string; order_date: string; expected_date: string | null; currency?: string; total_amount?: string;
  payment_terms?: string; notes: string; overdue: boolean; created_at: string; lines: PurchaseLine[];
}
export interface ShipmentLine { id: string; product_id: string; product_name: string; internal_sku: string; quantity: number; received_quantity: number }
export interface Shipment {
  id: string; number: string; store_id: string; store_name: string; purchase_order_id: string | null;
  source_warehouse_id: string | null; destination_warehouse_id: string; source_name: string; destination_name: string;
  destination_kind: string; status: string; stage: string; carrier: string; tracking_number: string; amazon_shipment_id: string;
  expected_date: string | null; notes: string; overdue: boolean; shipped_at: string | null; received_at: string | null;
  lines: ShipmentLine[]; events?: { id: string; stage: string; notes: string; actor_name: string; created_at: string }[];
}
export interface InventoryBalance { id: string; store_id: string; store_name: string; warehouse_id: string; warehouse_name: string; warehouse_kind: string; product_id: string; internal_sku: string; product_name: string; quantity: number; reserved: number; available: number; updated_at: string }
export interface Movement { id: string; store_name: string; warehouse_name: string; product_name: string; internal_sku: string; kind: string; quantity: number; reserved_delta: number; balance_after: number; reserved_after: number; reference_id: string; reference_number: string; reason: string; actor_name: string; created_at: string }
export interface StockSummary { quantity: number; reserved: number; available: number; in_transit: number }
