from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.security import aware


def scheduled_times(day: date | None, clock: str | None, zone: str):
    if day is None:
        return None, None, None
    tz = ZoneInfo(zone)
    start = datetime.combine(day, time.min, tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tz)
    due = datetime.combine(day, time.fromisoformat(clock), tz) if clock else start
    # fold=0 chooses one occurrence on fallback; a spring gap rolls forward by the gap.
    return tuple(value.astimezone(timezone.utc) for value in (due, start, end))


def next_weekday(moment: datetime, weekday: int, clock: str | None, zone: str):
    local = aware(moment).astimezone(ZoneInfo(zone))
    day = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
    due, _, end = scheduled_times(day, clock, zone)
    if (due if clock else end) < aware(moment):
        day += timedelta(days=7)
    return day


def source_date(day: date | None, offset: int):
    return day + timedelta(days=offset) if day else None


def set_schedule(task, day, clock, zone, *, changed=True):
    different = (task.due_date, task.due_time, task.timezone) != (day, clock, zone)
    task.due_date, task.due_time, task.timezone = day, clock, zone
    task.due_at, task.day_start_at, task.day_end_at = scheduled_times(day, clock, zone)
    if different and changed:
        task.schedule_version += 1
        task.version += 1
    return different


def category(task, moment):
    if task.status != 'pending':
        return task.status
    if task.due_date is None:
        return 'unscheduled'
    deadline = task.due_at if task.due_time else task.day_end_at
    if aware(deadline) <= moment:
        return 'overdue'
    return 'today' if aware(task.day_start_at) <= moment < aware(task.day_end_at) else 'future'
