from datetime import datetime, date, time, timedelta

DATE_FMT = '%Y-%m-%d'
DT_FMT = '%Y-%m-%d %H:%M:%S'

# 向着星的“逻辑日”切换时间：凌晨 4 点
# 00:00 - 03:59 仍然算作前一天
DAY_BOUNDARY_HOUR = 4


def now() -> datetime:
    return datetime.now()


def now_str() -> str:
    return now().strftime(DT_FMT)


def business_date(dt: datetime | None = None) -> date:
    """
    返回系统逻辑日期。

    本项目不再以 00:00 作为日期边界，而是以凌晨 4 点作为日期边界。
    例如：
    2026-05-20 03:59 仍属于 2026-05-19
    2026-05-20 04:00 才属于 2026-05-20
    """
    dt = dt or now()
    return (dt - timedelta(hours=DAY_BOUNDARY_HOUR)).date()


def today_str() -> str:
    return date_str(business_date())


def business_date_from_datetime_string(value: str | None) -> str | None:
    """
    将数据库中的真实时间戳转换为系统逻辑日期。

    用于会话补结算判断。
    如果用户 5月19日晚上打开软件，5月20日凌晨5点关闭软件，
    opened_at 属于逻辑日 5月19日，closed_at 属于逻辑日 5月20日。
    系统会用较早的逻辑日作为补结算候选，避免漏结算 5月19日。
    """
    if not value:
        return None

    try:
        dt = datetime.strptime(value, DT_FMT)
    except ValueError:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value.split(' ')[0]

    return date_str(business_date(dt))


def next_boundary(dt: datetime | None = None) -> datetime:
    """
    返回下一次逻辑日切换时间，即下一次凌晨 4 点。
    """
    dt = dt or now()
    candidate = datetime.combine(dt.date(), time(hour=DAY_BOUNDARY_HOUR))
    if dt >= candidate:
        candidate += timedelta(days=1)
    return candidate


def seconds_until_next_boundary(dt: datetime | None = None) -> float:
    """
    返回距离下一次凌晨 4 点还有多少秒。
    """
    dt = dt or now()
    return max((next_boundary(dt) - dt).total_seconds(), 0.0)


def parse_date(s: str) -> date:
    return datetime.strptime(s, DATE_FMT).date()


def date_str(d: date) -> str:
    return d.strftime(DATE_FMT)


def next_date(s: str) -> str:
    return date_str(parse_date(s) + timedelta(days=1))


def prev_date(s: str) -> str:
    return date_str(parse_date(s) - timedelta(days=1))


def date_range(start: str, end: str):
    d = parse_date(start)
    e = parse_date(end)
    while d <= e:
        yield date_str(d)
        d += timedelta(days=1)


def days_between(start: str, end: str) -> int:
    return (parse_date(end) - parse_date(start)).days