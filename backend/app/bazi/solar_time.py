"""真太阳时换算."""

from datetime import datetime, timedelta


def equation_of_time(day_of_year: int) -> float:
    """简化均时差（分钟）."""
    b = 2 * 3.14159265 * (day_of_year - 81) / 364
    return 9.87 * __import__("math").sin(2 * b) - 7.53 * __import__("math").cos(b) - 1.5 * __import__("math").sin(b)


def beijing_to_true_solar(
    dt: datetime,
    longitude: float,
    standard_longitude: float = 120.0,
) -> datetime:
    """
    北京时间转真太阳时。
    longitude: 出生地经度（东经为正）
    """
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    # 经度差修正：每度 4 分钟
    lon_offset_min = (longitude - standard_longitude) * 4
    eot = equation_of_time(dt.timetuple().tm_yday)
    total_min = lon_offset_min + eot
    return dt + timedelta(minutes=total_min)
