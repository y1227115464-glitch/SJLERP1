import type { ReportDateRange } from './report-date-ranges';

const STORE_KEY = 'sjlerp:selected-store';
const SALES_DATES_KEY = 'sjlerp:sales-analysis:dates';

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function write(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* Filtering still works when storage is unavailable. */ }
}

export function readSelectedStore(): string | null {
  return read(STORE_KEY)?.trim() || null;
}

export function saveSelectedStore(store: string) {
  write(STORE_KEY, store);
}

function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function readSalesDates(): ReportDateRange | null {
  try {
    const value = JSON.parse(read(SALES_DATES_KEY) || 'null');
    if (!value || typeof value !== 'object') return null;
    if (value.start === '' && value.end === '') return { start: '', end: '' };
    if (!validDate(value.start) || !validDate(value.end) || value.start > value.end) return null;
    const presets = ['last7', 'last3', 'today', 'last30', 'thisWeek', 'lastWeek', 'thisMonth', 'lastMonth', 'thisYear'];
    return { start: value.start, end: value.end, ...(presets.includes(value.preset) ? { preset: value.preset } : {}) };
  } catch { return null; }
}

export function saveSalesDates(dates: ReportDateRange) {
  write(SALES_DATES_KEY, JSON.stringify(dates));
}
