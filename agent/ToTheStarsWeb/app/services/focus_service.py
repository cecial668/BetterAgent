from __future__ import annotations

from datetime import datetime, timedelta

from app.core.constants import DEFAULT_CATEGORIES
from app.core.date_utils import (
    DT_FMT,
    business_date,
    business_date_from_datetime_string,
    date_str,
    parse_date,
    today_str,
)
from app.repositories.focus_repo import FocusRepo

FOCUS_PRESETS = [15, 25, 30, 45, 60]
FOCUS_EXTRA_CATEGORIES = ['学习', '工作', '编程', '阅读', '写作', '复盘', '其他']


def _parse_datetime(value: str) -> datetime:
    if not value or not str(value).strip():
        raise ValueError('开始时间和结束时间不能为空')

    raw = str(value).strip()
    if raw.endswith('Z'):
        raw = raw[:-1]
    raw = raw.replace('T', ' ')
    if '.' in raw:
        raw = raw.split('.', 1)[0]

    for fmt in (DT_FMT, '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError('时间格式不正确，请使用 YYYY-MM-DD HH:MM:SS')


def _fmt_datetime(dt: datetime) -> str:
    return dt.strftime(DT_FMT)


class FocusService:
    def __init__(self, db):
        self.db = db
        self.repo = FocusRepo(db)

    def categories(self):
        seen = set()
        result = []
        for item in [*DEFAULT_CATEGORIES, *FOCUS_EXTRA_CATEGORIES, '未分类']:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def _format_session(self, row):
        seconds = int(row.get('duration_seconds') or 0)
        minutes = round(seconds / 60, 1)
        return {
            **row,
            'planned_minutes': int(row.get('planned_minutes') or 0),
            'duration_seconds': seconds,
            'duration_minutes': minutes,
            'duration_label': self.format_duration(seconds),
        }

    @staticmethod
    def format_duration(seconds):
        seconds = max(int(seconds or 0), 0)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours:
            return f'{hours:02d}:{minutes:02d}:{secs:02d}'
        return f'{minutes:02d}:{secs:02d}'

    def create_session(self, payload):
        started_dt = _parse_datetime(payload.started_at)
        ended_dt = _parse_datetime(payload.ended_at)
        if started_dt >= ended_dt:
            raise ValueError('开始时间必须早于结束时间')

        planned_minutes = int(payload.planned_minutes)
        duration_seconds = int(payload.duration_seconds)
        max_allowed = planned_minutes * 60 + 5
        if duration_seconds > max_allowed:
            raise ValueError('专注时长不能大于计划时长')
        if duration_seconds <= 0:
            raise ValueError('专注时长必须大于 0')

        category = (payload.category or '').strip() or '未分类'
        description = (payload.description or '').strip()
        business = business_date_from_datetime_string(_fmt_datetime(started_dt)) or date_str(business_date(started_dt))

        row = self.repo.create(
            business,
            _fmt_datetime(started_dt),
            _fmt_datetime(ended_dt),
            planned_minutes,
            duration_seconds,
            category,
            description,
        )
        return {
            'ok': True,
            'session': self._format_session(row),
            'today_seconds': self.repo.total_by_date(today_str()),
            'total_seconds': self.repo.total_seconds(),
        }

    def today(self):
        date = today_str()
        sessions = [self._format_session(r) for r in self.repo.list_by_date(date, 100)]
        today_seconds = sum(s['duration_seconds'] for s in sessions)
        return {
            'date': date,
            'today_seconds': today_seconds,
            'today_minutes': round(today_seconds / 60, 1),
            'today_label': self.format_duration(today_seconds),
            'sessions': sessions,
            'categories': self.categories(),
            'presets': FOCUS_PRESETS,
        }

    def sessions(self, date=None, limit=100):
        if date:
            rows = self.repo.list_by_date(date, limit)
        else:
            rows = self.repo.list_recent(limit)
        return [self._format_session(r) for r in rows]

    def summary(self, days=14):
        days = max(1, min(int(days or 14), 366))
        today = today_str()
        start = date_str(parse_date(today) - timedelta(days=days - 1))
        raw = {r['date']: int(r['seconds'] or 0) for r in self.repo.daily_totals_between(start, today)}
        daily = []
        current = parse_date(start)
        end = parse_date(today)
        while current <= end:
            d = date_str(current)
            sec = raw.get(d, 0)
            daily.append({'date': d, 'seconds': sec, 'minutes': round(sec / 60, 1), 'label': self.format_duration(sec)})
            current += timedelta(days=1)

        today_seconds = raw.get(today, self.repo.total_by_date(today))
        return {
            'date': today,
            'today_seconds': today_seconds,
            'today_minutes': round(today_seconds / 60, 1),
            'today_label': self.format_duration(today_seconds),
            'total_seconds': self.repo.total_seconds(),
            'total_label': self.format_duration(self.repo.total_seconds()),
            'daily': daily,
            'sessions': self.sessions(limit=100),
            'categories': self.categories(),
            'presets': FOCUS_PRESETS,
        }
