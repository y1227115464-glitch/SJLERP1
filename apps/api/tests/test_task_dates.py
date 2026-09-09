from datetime import date, datetime, timezone

from app.tasks.dates import next_weekday, scheduled_times, source_date


def test_monday_boundary_and_source_offsets():
    assert next_weekday(datetime(2026, 9, 11, 2, tzinfo=timezone.utc), 0, '09:00', 'Asia/Shanghai') == date(2026, 9, 14)
    assert next_weekday(datetime(2026, 9, 14, 0, tzinfo=timezone.utc), 0, '09:00', 'Asia/Shanghai') == date(2026, 9, 14)
    assert next_weekday(datetime(2026, 9, 14, 1, tzinfo=timezone.utc), 0, '09:00', 'Asia/Shanghai') == date(2026, 9, 14)
    assert next_weekday(datetime(2026, 9, 14, 2, tzinfo=timezone.utc), 0, '09:00', 'Asia/Shanghai') == date(2026, 9, 21)
    assert source_date(date(2026, 9, 18), -2) == date(2026, 9, 16)
    assert source_date(None, -2) is None


def test_all_day_and_dst_calendar_boundaries():
    due, start, end = scheduled_times(date(2026, 9, 18), None, 'Asia/Shanghai')
    assert due == start == datetime(2026, 9, 17, 16, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 18, 16, tzinfo=timezone.utc)
    due, start, end = scheduled_times(date(2026, 3, 8), '02:30', 'America/New_York')
    assert (end - start).total_seconds() == 23 * 3600
    assert due == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)
    assert scheduled_times(None, None, 'Asia/Shanghai') == (None, None, None)
