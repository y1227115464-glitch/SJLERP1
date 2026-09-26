import type { SummaryGroup } from './report-types';

// The API returns amounts with four decimal places. Sum before rounding for display.
export function salesCurrencySummary(groups: SummaryGroup[]): SummaryGroup[] {
  const currencies = new Map<string | null, { rows: number; quantity: number; amount: bigint | null; missing: number }>();
  for (const group of groups) {
    const currency = group.currency || null;
    const total = currencies.get(currency) ?? { rows: 0, quantity: 0, amount: null, missing: 0 };
    total.rows += group.rows;
    total.quantity += Number(group.quantity ?? 0);
    total.missing += Number(group.missing_amount_rows ?? 0);
    if (group.net_amount != null) {
      const text = String(group.net_amount);
      const [whole, fraction = ''] = text.replace(/^-/, '').split('.');
      const amount = (BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))) * (text.startsWith('-') ? -1n : 1n);
      total.amount = (total.amount ?? 0n) + amount;
    }
    currencies.set(currency, total);
  }
  return [...currencies].sort(([a], [b]) => {
    if (a === null) return 1;
    if (b === null) return -1;
    if (a === 'USD') return -1;
    if (b === 'USD') return 1;
    return a.localeCompare(b);
  }).map(([currency, total]) => {
    let amount: string | null = null;
    if (total.amount !== null) {
      const cents = ((total.amount < 0n ? -total.amount : total.amount) + 50n) / 100n;
      const whole = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      amount = `${total.amount < 0n && cents > 0n ? '-' : ''}${whole}.${(cents % 100n).toString().padStart(2, '0')}`;
    }
    return { currency, rows: total.rows, quantity: total.quantity, net_amount: amount, missing_amount_rows: total.missing };
  });
}
