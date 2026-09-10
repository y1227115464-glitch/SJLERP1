export function cartonText(quantity: number, size?: number | null): string {
  if (!size) return '箱规未维护';
  const boxes = Math.floor(quantity / size);
  const remainder = quantity % size;
  return `${boxes} 箱${remainder ? ` + ${remainder} 件` : ''}`;
}

export function totalWeight(quantity: number, weight?: string | null): string {
  if (!weight) return '重量未维护';
  // Decimal kg × integer pieces, without floating point rounding or overflow.
  const [whole, fraction = ''] = weight.split('.');
  const scaled = BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'));
  const total = scaled * BigInt(quantity || 0);
  return `${total / 10000n}.${String(total % 10000n).padStart(4, '0')} kg`;
}
