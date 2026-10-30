"""Calendar windows, with half-open boundaries in Europe/Rome (Python 3.9+)."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

ROME = ZoneInfo('Europe/Rome')
PRESETS = ('today', 'yesterday', 'last7', 'previous-week')


@dataclass(frozen=True)
class Window:
    name: str
    start: datetime
    end: datetime

    @property
    def key(self):
        # UTC subtraction/comparisons avoid same-zone wall-clock DST arithmetic.
        return (self.start.astimezone(timezone.utc), self.end.astimezone(timezone.utc))


def calendar_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('use YYYY-MM-DD')
    return date.fromisoformat(value)


def resolve_window(name, now, start=None, end=None):
    if now.tzinfo is None:
        raise ValueError('generation time must include a timezone')
    today = now.astimezone(ROME).date()
    if name == 'today':
        first, stop = today, today + timedelta(days=1)
    elif name == 'yesterday':
        first, stop = today - timedelta(days=1), today
    elif name == 'last7':
        first, stop = today - timedelta(days=6), today + timedelta(days=1)
    elif name == 'previous-week':
        stop = today - timedelta(days=today.weekday())
        first = stop - timedelta(days=7)
    elif name == 'custom':
        first, stop = start, end
        if not isinstance(first, date) or not isinstance(stop, date):
            raise ValueError('custom range requires --start and --end dates')
    else:
        raise ValueError('unknown timeframe')
    if first >= stop:
        raise ValueError('--end must be later than --start (end is exclusive)')
    begin = datetime.combine(first, time.min, ROME)
    finish = datetime.combine(stop, time.min, ROME)
    window = Window(name, begin, finish)
    window.key  # Validate representable UTC boundaries, including extreme dates.
    return window
