export type SalesGranularity = 'day' | 'week' | 'month' | 'year' | 'range';

export function defaultSalesGranularity(start: string, end: string): SalesGranularity {
  if (!start || !end) return 'year';
  const days = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000 + 1;
  if (!Number.isFinite(days) || days < 1) return 'year';
  if (days <= 14) return 'day';
  if (days <= 30) return 'week';
  if (days <= 180) return 'month';
  return 'year';
}
