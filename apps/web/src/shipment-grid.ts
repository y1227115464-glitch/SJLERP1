interface SourceQuantity { product_id: string; quantity: number; supplier_stock_id?: string | null }

export function groupShipmentRows<T extends SourceQuantity>(lines: T[]) {
  const groups = new Map<string, { productId: string; indices: number[]; total: number; stockTotal: number }>();
  lines.forEach((line, index) => {
    const key = line.product_id || `empty-${index}`;
    const group = groups.get(key) || { productId: key, indices: [], total: 0, stockTotal: 0 };
    group.indices.push(index);
    group.total += Number(line.quantity) || 0;
    if (line.supplier_stock_id) group.stockTotal += Number(line.quantity) || 0;
    groups.set(key, group);
  });
  return [...groups.values()];
}

// Zero clears a source cell; the API still receives only positive source allocations.
export function allocatedShipmentRows<T extends SourceQuantity>(lines: T[]) {
  return lines.filter(line => line.quantity > 0);
}
