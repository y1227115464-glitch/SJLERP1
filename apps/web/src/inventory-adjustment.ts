export function productBelongsToStore(product: { brand: string; is_active: boolean } | null | undefined, storeBrand: string | undefined): boolean {
  return !!storeBrand?.trim() && !!product?.is_active && product.brand === storeBrand;
}

export function adjustmentQuantity(magnitude: number | null | undefined, sign: 1 | -1, kind: string): number {
  if (typeof magnitude !== 'number' || !Number.isInteger(magnitude) || magnitude < 1 || magnitude > 1000000000) {
    throw new Error('请输入大于等于 1 且不超过 1000000000 的整数');
  }
  if (kind === 'opening' && sign === -1) throw new Error('期初库存仅支持增加');
  return magnitude * sign;
}
