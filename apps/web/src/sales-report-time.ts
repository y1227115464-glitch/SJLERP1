// Agreed reporting convention: fixed PDT (UTC-7), with no winter offset change.
export const SALES_UTC_OFFSET_MINUTES = -7 * 60;

export function salesReportTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—';
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return '—';
  return new Date(timestamp + SALES_UTC_OFFSET_MINUTES * 60_000).toISOString().slice(0, 19).replace('T', ' ');
}
