from datetime import datetime, timedelta, time


def period(kind, now):
    """Calendar keys avoid elapsed-hour/DST errors; callers use local wall time."""
    day = now.date() - timedelta(days=now.time() < time(6))
    if kind == 'weekly':
        day -= timedelta(days=day.weekday())
    return day.isoformat()


def next_reset(kind, now):
    day = datetime.fromisoformat(period(kind, now)).date()
    day += timedelta(days=7 if kind == 'weekly' else 1)
    return datetime.combine(day, time(6))
