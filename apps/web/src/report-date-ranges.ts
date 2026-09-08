export const reportDatePresets = [
  { value: 'last7', label: '最近7天' }, { value: 'last3', label: '最近3天' }, { value: 'today', label: '今天' },
  { value: 'last30', label: '最近30天' }, { value: 'thisWeek', label: '本周' }, { value: 'lastWeek', label: '上周' },
  { value: 'thisMonth', label: '本月' }, { value: 'lastMonth', label: '上月' }, { value: 'thisYear', label: '今年以来' },
] as const;

export type ReportDatePreset = typeof reportDatePresets[number]['value'];
export type ReportDateRange = { start: string; end: string; preset?: ReportDatePreset };

export function isRollingReportPreset(preset?: ReportDatePreset) {
  return preset === 'last3' || preset === 'last7' || preset === 'last30';
}

function calendarDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
}

export function reportDateRange(preset: ReportDatePreset, now = new Date(), includeToday = true): ReportDateRange {
  const year = now.getFullYear();
  const month = now.getMonth();
  const day = now.getDate();
  const start = new Date(year, month, day);
  const end = new Date(year, month, day);
  const daysSinceMonday = (now.getDay() + 6) % 7;
  switch (preset) {
    case 'last7': start.setDate(day - 6); break;
    case 'last3': start.setDate(day - 2); break;
    case 'last30': start.setDate(day - 29); break;
    case 'thisWeek': start.setDate(day - daysSinceMonday); break;
    case 'lastWeek': start.setDate(day - daysSinceMonday - 7); end.setDate(day - daysSinceMonday - 1); break;
    case 'thisMonth': start.setDate(1); break;
    case 'lastMonth': start.setFullYear(year, month - 1, 1); end.setDate(0); break;
    case 'thisYear': start.setFullYear(year, 0, 1); break;
    case 'today': break;
  }
  if (!includeToday && isRollingReportPreset(preset)) {
    start.setDate(start.getDate() - 1);
    end.setDate(end.getDate() - 1);
  }
  return { start: calendarDate(start), end: calendarDate(end) };
}
