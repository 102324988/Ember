"""Legacy naive timestamps represent Shanghai wall time."""
from datetime import datetime
from zoneinfo import ZoneInfo
from config.settings import settings


def get_timezone():
    return ZoneInfo(settings.TIMEZONE)


def to_epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone())
    return parsed.timestamp()


def time_period(epoch):
    hour = datetime.fromtimestamp(epoch, get_timezone()).hour
    if hour < 5 or hour >= 23:
        return '深夜'
    if hour < 7:
        return '清晨'
    if hour < 11:
        return '上午'
    if hour < 14:
        return '中午'
    if hour < 18:
        return '下午'
    return '晚上'
