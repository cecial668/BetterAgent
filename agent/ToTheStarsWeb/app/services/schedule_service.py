from __future__ import annotations

from datetime import timedelta

from app.core.constants import DIFFICULTY_META
from app.core.date_utils import (
    DAY_BOUNDARY_HOUR,
    date_str,
    next_date,
    parse_date,
    prev_date,
    today_str,
)
from app.repositories.log_repo import LogRepo
from app.repositories.quest_repo import QuestRepo
from app.repositories.schedule_repo import ScheduleRepo
from app.services.vacation_service import VacationService

DAY_MINUTES = 24 * 60
BUCKET_MINUTES = 4 * 60
BUCKET_NAMES = ['清晨', '上午', '午后', '傍晚', '夜晚', '深夜']
WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

COLOR_BY_KEY = {
    'free': '#38BDF8',
    'quest': '#F59E0B',
    'quest-done': '#34D399',
}


def parse_clock(value) -> tuple[int, int]:
    raw = str(value or '').strip()
    if not raw:
        raise ValueError('时间不能为空')
    parts = raw.split(':')
    if len(parts) < 2:
        raise ValueError('时间格式不正确，请使用 HH:MM')
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        raise ValueError('时间格式不正确，请使用 HH:MM')
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError('时间需要在 00:00 - 23:59 之间')
    return hour, minute


def clock_to_offset(value) -> int:
    """把钟表时间换算为“逻辑日 04:00 起算”的偏移，范围 0 - 1439。"""
    hour, minute = parse_clock(value)
    return (hour * 60 + minute - DAY_BOUNDARY_HOUR * 60) % DAY_MINUTES


def parse_time_offset(value, as_end=False) -> int:
    offset = clock_to_offset(value)
    if as_end and offset == 0:
        # 结束时间填 04:00 表示逻辑日结束（即次日 04:00）。
        return DAY_MINUTES
    return offset


def offset_to_label(offset) -> str:
    offset = max(0, int(offset))
    clock = (offset + DAY_BOUNDARY_HOUR * 60) % DAY_MINUTES
    return f'{clock // 60:02d}:{clock % 60:02d}'


def minutes_label(minutes) -> str:
    total = max(0, int(minutes))
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f'{hours} 小时 {mins} 分'
    if hours:
        return f'{hours} 小时'
    return f'{mins} 分钟'


def build_timeline() -> dict:
    ticks = []
    for minute in range(0, DAY_MINUTES + 1, 120):
        ticks.append({
            'minute': minute,
            'label': offset_to_label(minute),
            'is_major': minute % BUCKET_MINUTES == 0,
            'is_day_end': minute == DAY_MINUTES,
        })
    return {
        'start_hour': DAY_BOUNDARY_HOUR,
        'end_hour': DAY_BOUNDARY_HOUR + 24,
        'total_minutes': DAY_MINUTES,
        'step_minutes': 120,
        'ticks': ticks,
    }


def build_buckets() -> list[dict]:
    buckets = []
    for index, name in enumerate(BUCKET_NAMES):
        start = index * BUCKET_MINUTES
        end = start + BUCKET_MINUTES
        buckets.append({
            'key': f'b{index}',
            'name': name,
            'start_minute': start,
            'end_minute': end,
            'range_label': f'{offset_to_label(start)}-{offset_to_label(end)}',
        })
    return buckets


def assign_lanes(plans: list[dict]) -> int:
    """给时间重叠的计划分配不同行：先按开始时间排序，放进第一条放得下的行。"""
    lane_ends: list[int] = []
    for plan in sorted(plans, key=lambda p: (p['start_minute'], p['end_minute'], p['id'])):
        for index, lane_end in enumerate(lane_ends):
            if lane_end <= plan['start_minute']:
                lane_ends[index] = plan['end_minute']
                plan['lane'] = index
                break
        else:
            lane_ends.append(plan['end_minute'])
            plan['lane'] = len(lane_ends) - 1
    return max(1, len(lane_ends))


class ScheduleService:
    def __init__(self, db):
        self.db = db
        self.repo = ScheduleRepo(db)
        self.quests = QuestRepo(db)
        self.log = LogRepo(db)
        self.vac = VacationService(db)

    # ---------- 格式化 ----------

    @staticmethod
    def _format_quest(row) -> dict:
        meta = DIFFICULTY_META.get(row.get('difficulty'), {})
        return {
            'id': row['id'],
            'title': row.get('title') or '',
            'description': row.get('description') or '',
            'difficulty': row.get('difficulty'),
            'difficulty_name': meta.get('name', row.get('difficulty')),
            'difficulty_color': meta.get('color', '#64748B'),
            'points': float(row.get('points') or 0),
            'category': row.get('category') or '未分类',
            'is_required': bool(row.get('is_required')),
            'is_recurring': bool(row.get('is_recurring')),
            'is_completed': bool(row.get('is_completed')),
            'banked_points': float(row.get('banked_points') or 0),
            'assigned_date': row.get('assigned_date'),
        }

    @staticmethod
    def _format_plan(row) -> dict:
        start = int(row.get('start_minute') or 0)
        end = int(row.get('end_minute') or 0)
        quest_id = row.get('quest_id')
        bound = quest_id is not None
        completed = bool(row.get('quest_completed')) if bound else False
        meta = DIFFICULTY_META.get(row.get('quest_difficulty'), {}) if bound else {}
        color_key = 'quest' if bound else 'free'
        if bound and completed:
            color_key = 'quest-done'

        # 委托计划始终展示委托本身的最新文案，避免两边漂移
        if bound and row.get('quest_title') is not None:
            title = row.get('quest_title') or ''
            content = row.get('quest_description') or ''
        else:
            title = row.get('title') or ''
            content = row.get('content') or ''

        return {
            'id': row['id'],
            'plan_date': row.get('plan_date'),
            'title': title,
            'content': content,
            'start_minute': start,
            'end_minute': end,
            'duration_minutes': max(0, end - start),
            'duration_label': minutes_label(end - start),
            'start_label': offset_to_label(start),
            'end_label': offset_to_label(end),
            'time_label': f'{offset_to_label(start)} - {offset_to_label(end)}',
            'quest_id': quest_id,
            'kind': 'quest' if bound else 'free',
            'completed': completed,
            'color_key': color_key,
            'color': COLOR_BY_KEY.get(color_key),
            'difficulty': row.get('quest_difficulty'),
            'difficulty_name': meta.get('name'),
            'difficulty_color': meta.get('color', '#64748B'),
            'category': row.get('quest_category') or '',
            'points': float(row.get('quest_points') or 0),
            'is_required': bool(row.get('quest_required')),
            'banked_points': float(row.get('quest_banked_points') or 0),
            'lane': 0,
            'created_at': row.get('created_at'),
            'updated_at': row.get('updated_at'),
        }

    # ---------- 校验 ----------

    @staticmethod
    def _clean_date(value, fallback=None) -> str:
        raw = str(value or fallback or today_str()).strip()
        try:
            parse_date(raw)
        except ValueError:
            raise ValueError('日期格式不正确，请使用 YYYY-MM-DD')
        return raw

    @staticmethod
    def _parse_range(start, end) -> tuple[int, int]:
        begin = parse_time_offset(start)
        finish = parse_time_offset(end, as_end=True)
        if finish <= begin:
            raise ValueError('结束时间需要晚于开始时间（一天的范围是 04:00 到次日 04:00）')
        if finish - begin < 5:
            raise ValueError('计划至少需要 5 分钟')
        return begin, finish

    def _bound_quest(self, quest_id):
        try:
            qid = int(quest_id)
        except (TypeError, ValueError):
            raise ValueError('选择的委托无效')
        quest = self.quests.get(qid)
        if not quest:
            raise ValueError('选择的委托不存在或已经被处理，请刷新后重试')
        return quest

    def _sync_quest_fields(self, quest, title, content):
        if (quest.get('title') or '') == title and (quest.get('description') or '') == (content or ''):
            return False
        self.quests.update(
            quest['id'],
            title,
            content or '',
            quest['difficulty'],
            quest['points'],
            quest['category'],
            quest['is_required'],
            quest.get('is_recurring') or 0,
        )
        self.log.log('schedule_sync_quest', 'daily_quest', quest['id'], {'title': title})
        return True

    # ---------- 周视图 ----------

    def week(self, date=None) -> dict:
        anchor = self._clean_date(date)
        day = parse_date(anchor)
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
        start_s, end_s = date_str(start), date_str(end)
        today = today_str()

        plans = [self._format_plan(r) for r in self.repo.list_between(start_s, end_s)]
        plans_by_date: dict[str, list[dict]] = {}
        for plan in plans:
            plans_by_date.setdefault(plan['plan_date'], []).append(plan)

        quests_by_date: dict[str, list[dict]] = {}
        for row in self.quests.list_between(start_s, end_s):
            quests_by_date.setdefault(row['assigned_date'], []).append(row)

        buckets = build_buckets()
        days = []
        for index in range(7):
            current = date_str(start + timedelta(days=index))
            day_plans = plans_by_date.get(current, [])
            scheduled_quest_ids = {p['quest_id'] for p in day_plans if p['quest_id']}
            day_quests = [self._format_quest(q) for q in quests_by_date.get(current, [])]
            cells = []
            for bucket in buckets:
                items = [
                    p for p in day_plans
                    if p['start_minute'] < bucket['end_minute'] and p['end_minute'] > bucket['start_minute']
                ]
                cells.append({**bucket, 'plans': items})

            date_obj = parse_date(current)
            days.append({
                'date': current,
                'weekday_label': WEEKDAY_LABELS[date_obj.weekday()],
                'day_number': date_obj.day,
                'month': date_obj.month,
                'is_today': current == today,
                'is_past': current < today,
                'is_vacation': self.vac.is_vacation(current),
                'plan_count': len(day_plans),
                'quest_count': len(day_quests),
                'unscheduled_count': len([q for q in day_quests if q['id'] not in scheduled_quest_ids]),
                'plans': day_plans,
                'buckets': cells,
            })

        return {
            'date': anchor,
            'today': today,
            'is_current_week': start_s <= today <= end_s,
            'week_start': start_s,
            'week_end': end_s,
            'week_label': f'{start_s} ~ {end_s}',
            'prev_week_date': date_str(start - timedelta(days=7)),
            'next_week_date': date_str(start + timedelta(days=7)),
            'buckets': [{k: v for k, v in bucket.items() if k != 'plans'} for bucket in buckets],
            'days': days,
            'timeline': build_timeline(),
            'color_legend': [
                {'key': 'quest', 'label': '每日委托（未完成）', 'color': COLOR_BY_KEY['quest']},
                {'key': 'quest-done', 'label': '每日委托（已完成）', 'color': COLOR_BY_KEY['quest-done']},
                {'key': 'free', 'label': '自定义计划', 'color': COLOR_BY_KEY['free']},
            ],
        }

    # ---------- 日视图 ----------

    def day(self, date=None) -> dict:
        current = self._clean_date(date)
        today = today_str()
        rows = self.repo.list_by_date(current)
        plans = [self._format_plan(r) for r in rows]
        lane_count = assign_lanes(plans)

        scheduled = {p['quest_id']: p for p in plans if p['quest_id']}
        quests = []
        for row in self.quests.list_by_date(current):
            quest = self._format_quest(row)
            plan = scheduled.get(quest['id'])
            quest['scheduled'] = plan is not None
            quest['plan_id'] = plan['id'] if plan else None
            quest['plan_time_label'] = plan['time_label'] if plan else ''
            quests.append(quest)

        date_obj = parse_date(current)
        relative = ''
        if current == today:
            relative = '今天'
        elif current == next_date(today):
            relative = '明天'
        elif current == prev_date(today):
            relative = '昨天'

        return {
            'date': current,
            'today': today,
            'is_today': current == today,
            'is_vacation': self.vac.is_vacation(current),
            'relative_label': relative,
            'weekday_label': WEEKDAY_LABELS[date_obj.weekday()],
            'month': date_obj.month,
            'day_number': date_obj.day,
            'prev_date': prev_date(current),
            'next_date': next_date(current),
            'plans': plans,
            'lane_count': lane_count,
            'quests': quests,
            'unscheduled_quests': [q for q in quests if not q['scheduled']],
            'total_minutes': sum(p['duration_minutes'] for p in plans),
            'total_label': minutes_label(sum(p['duration_minutes'] for p in plans)),
            'timeline': build_timeline(),
            'color_legend': [
                {'key': 'quest', 'label': '每日委托（未完成）', 'color': COLOR_BY_KEY['quest']},
                {'key': 'quest-done', 'label': '每日委托（已完成）', 'color': COLOR_BY_KEY['quest-done']},
                {'key': 'free', 'label': '自定义计划', 'color': COLOR_BY_KEY['free']},
            ],
        }

    # ---------- 增删改 ----------

    def create(self, payload) -> dict:
        plan_date = self._clean_date(getattr(payload, 'plan_date', None))
        start, end = self._parse_range(payload.start, payload.end)

        quest = None
        if getattr(payload, 'quest_id', None):
            quest = self._bound_quest(payload.quest_id)

        title = (getattr(payload, 'title', '') or '').strip()
        content = getattr(payload, 'content', '') or ''

        if quest:
            if not title:
                title = quest.get('title') or '未命名委托'
            if not content:
                content = quest.get('description') or ''
            self._sync_quest_fields(quest, title, content)
        else:
            if not title:
                raise ValueError('计划名称不能为空')
            content = content or ''

        plan_id = self.repo.create(plan_date, title, content, start, end, quest['id'] if quest else None)
        self.log.log(
            'schedule_create',
            'schedule_plan',
            plan_id,
            {'date': plan_date, 'quest_id': quest['id'] if quest else None, 'start': start, 'end': end},
        )
        return self._format_plan(self.repo.get(plan_id))

    def update(self, plan_id, payload) -> dict:
        row = self.repo.get(plan_id)
        if not row:
            raise ValueError('计划不存在或已被删除')

        plan_date = self._clean_date(getattr(payload, 'plan_date', None), row['plan_date'])
        start, end = self._parse_range(payload.start, payload.end)
        title = (getattr(payload, 'title', '') or '').strip() or (row.get('title') or '未命名计划')
        content = getattr(payload, 'content', None)
        content = row.get('content') or '' if content is None else content

        self.repo.update(plan_id, plan_date, title, content, start, end)

        quest_id = row.get('quest_id')
        if quest_id:
            quest = self.quests.get(quest_id)
            if quest:
                self._sync_quest_fields(quest, title, content)

        self.log.log('schedule_update', 'schedule_plan', plan_id, {'date': plan_date, 'start': start, 'end': end})
        return self._format_plan(self.repo.get(plan_id))

    def delete(self, plan_id) -> bool:
        row = self.repo.get(plan_id)
        if not row:
            raise ValueError('计划不存在或已被删除')
        self.repo.delete(plan_id)
        self.log.log('schedule_delete', 'schedule_plan', plan_id, {'date': row.get('plan_date')})
        return True

    # ---------- 与每日委托联动 ----------

    def sync_quest(self, quest_id, title, description) -> int:
        """每日委托标题/描述被修改后，同步到绑定计划。"""
        self.repo.rename_by_quest(quest_id, title, description or '')
        return len(self.repo.list_by_quest(quest_id))

    def unbind_quests(self, quest_ids) -> int:
        """委托被删除/归档后，保留计划内容但解除绑定。"""
        count = self.repo.unbind_quests(quest_ids)
        if count:
            self.log.log('schedule_unbind', 'schedule_plan', None, {'quest_ids': list(quest_ids), 'count': count})
        return count

    def move_quest_plans(self, quest_ids, new_date, conn=None) -> int:
        """委托顺延到新日期时，把绑定计划一并移动到新日期。"""
        return self.repo.move_quest_plans(quest_ids, self._clean_date(new_date), conn)
