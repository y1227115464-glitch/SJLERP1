"""Calendar buckets for SKU sales detail (inclusive date ranges)."""
from datetime import date, timedelta
from typing import Literal

Granularity = Literal['day', 'week', 'month', 'year']


def period_start(day: date, granularity: Granularity) -> date:
    if granularity == 'week':
        return day - timedelta(days=day.weekday())
    if granularity == 'month':
        return day.replace(day=1)
    if granularity == 'year':
        return day.replace(month=1, day=1)
    return day


def period_end(day: date, granularity: Granularity) -> date:
    if granularity == 'year':
        return day.replace(month=12, day=31)
    if granularity == 'month':
        if day.month == 12:
            return day.replace(day=31)
        return day.replace(month=day.month + 1, day=1) - timedelta(days=1)
    if granularity == 'week':
        return day + timedelta(days=min(6, (date.max - day).days))
    return day
