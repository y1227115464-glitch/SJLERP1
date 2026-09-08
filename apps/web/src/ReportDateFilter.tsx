import { useRef, useState } from 'react';
import { Button, Checkbox, DatePicker } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { isRollingReportPreset, reportDatePresets, reportDateRange } from './report-date-ranges';
import type { ReportDateRange } from './report-date-ranges';

export function ReportDateFilter({ value, onChange }: { value: ReportDateRange; onChange: (value: ReportDateRange) => void }) {
  const [open, setOpen] = useState(false);
  const [includeToday, setIncludeToday] = useState(true);
  const pendingPreset = useRef<ReportDateRange | undefined>(undefined);
  return <DatePicker.RangePicker className="report-date-filter" classNames={{ popup: { root: 'report-date-popup' } }}
    prefix={<strong>日期：</strong>} separator={<ArrowRightOutlined />} format="YYYY/MM/DD"
    placeholder={['开始日期', '结束日期']} aria-label="报表日期区间" allowClear
    value={value.start && value.end ? [dayjs(value.start), dayjs(value.end)] : null}
    open={open} onOpenChange={next => { if (next) pendingPreset.current = undefined; setOpen(next); }}
    onChange={dates => {
      if (!dates) { pendingPreset.current = undefined; onChange({ start: '', end: '' }); }
      else if (dates[0] && dates[1]) {
        const range = { start: dates[0].format('YYYY-MM-DD'), end: dates[1].format('YYYY-MM-DD') };
        const preset = pendingPreset.current;
        // Closing the picker can flush an earlier partial range after a preset was submitted.
        if (preset && (range.start !== preset.start || range.end !== preset.end)) return;
        onChange({ ...range, preset: preset?.preset });
      }
    }}
    presets={reportDatePresets.map(preset => ({
      label: <Button type="text" aria-pressed={value.preset === preset.value}
        className={value.preset === preset.value ? 'report-date-preset-active' : ''}
        onClick={() => {
          const range = { ...reportDateRange(preset.value, new Date(), includeToday), preset: preset.value };
          pendingPreset.current = range;
          if (range.start === value.start && range.end === value.end) onChange(range);
        }}>{preset.label}</Button>,
      value: () => { const range = reportDateRange(preset.value, new Date(), includeToday); return [dayjs(range.start), dayjs(range.end)]; },
    }))}
    panelRender={panel => <div className="report-date-panel">
      <div className="report-date-presets-heading">
        <Checkbox checked={includeToday} onChange={event => {
          const checked = event.target.checked;
          setIncludeToday(checked);
          if (value.preset && isRollingReportPreset(value.preset)) onChange({ ...reportDateRange(value.preset, new Date(), checked), preset: value.preset });
        }}>含当天</Checkbox>
        <span className="report-date-preset-help">仅影响最近 N 天</span>
      </div>
      {panel}
    </div>} />;
}
