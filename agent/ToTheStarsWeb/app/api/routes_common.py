from __future__ import annotations
import json
from fastapi import HTTPException, Request
from app.core.constants import DIFFICULTY_META, LEGEND_META
from app.core.date_utils import today_str, business_date, parse_date


def db(request: Request):
    return request.app.state.db


def actor_of(request: Request) -> str:
    """写操作的来源标识。旧前端不带头 -> 'me'；数字人工具带 X-Actor: companion。"""
    raw = (request.headers.get('X-Actor') or '').strip().lower()
    return raw if raw in ('me', 'companion') else 'me'


def today():
    return today_str()


def to_bool(v):
    return bool(v) if v is not None else False


def safe_json(value, default=None):
    if value in (None, ''):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def raise400(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def day_title(total, is_vacation=False):
    if is_vacation:
        return '假期日'
    if total <= 0:
        return '摆烂日'
    if total < 4:
        return '休息日'
    if total == 4:
        return '行动日'
    return '拓展日'


def explain_condition(total, required_all, is_vacation, can_bank):
    if is_vacation:
        return '今天是假期日，已完成委托可以入池，不要求满 4 点。'
    if can_bank:
        return f'今日已达到 {total:g} 点且所有必要委托完成，可以进行普通结算。'

    reasons = []
    if total < 4:
        reasons.append(f'当前仅 {total:g} 点，普通日需要至少 4 点')
    if not required_all:
        reasons.append('仍有必要委托未完成')

    return '；'.join(reasons) + '，暂时不能入池。'


def format_quest(q):
    meta = DIFFICULTY_META.get(q.get('difficulty'), {})
    banked = float(q.get('banked_points') or 0)

    badges = ['必做' if q.get('is_required') else '支线']
    if q.get('is_recurring'):
        badges.append('日常委托')
    if banked > 0:
        badges.append('已入池')
    if q.get('is_completed'):
        badges.append('已完成')

    return {
        **q,
        'is_required': to_bool(q.get('is_required')),
        'is_recurring': to_bool(q.get('is_recurring')),
        'is_completed': to_bool(q.get('is_completed')),
        'points': float(q.get('points') or meta.get('points') or 0),
        'banked_points': banked,
        'difficulty_name': meta.get('name', q.get('difficulty')),
        'difficulty_color': meta.get('color', '#64748B'),
        'badges': badges,
    }


def condition_for(quests, is_vacation):
    total = sum(float(q.get('points') or 0) for q in quests if q.get('is_completed'))
    required_all = all(q.get('is_completed') for q in quests if q.get('is_required'))
    can_bank = bool(is_vacation or (total >= 4 and required_all))

    return {
        'total_points': total,
        'required_all_done': required_all,
        'is_success': None if is_vacation else (total >= 4 and required_all),
        'day_title_preview': day_title(total, is_vacation),
        'can_bank': can_bank,
        'explain': explain_condition(total, required_all, is_vacation, can_bank),
    }


def format_reward(r, wallet):
    stock = int(r.get('stock') or 0)
    bal = wallet['practice_points'] if r.get('point_type') == 'practice' else wallet['growth_points']

    sold = stock <= 0 or r.get('status') == 'sold_out'
    affordable = (not sold) and float(bal) >= float(r.get('price') or 0)

    if sold:
        display_status = '售空'
    elif affordable:
        display_status = '买得起'
    else:
        display_status = '买不起'

    return {
        **r,
        'price': float(r.get('price') or 0),
        'stock': stock,
        'affordable': affordable,
        'display_status': display_status,
        'point_type_label': '历练点' if r.get('point_type') == 'practice' else '成长点',
    }


def format_legend(l, indicators):
    total = len(indicators)
    done = sum(1 for i in indicators if i.get('is_completed'))

    try:
        remaining = (parse_date(l['deadline']) - business_date()).days if l.get('deadline') else None
    except Exception:
        remaining = None

    meta = LEGEND_META.get(l.get('difficulty'), {})

    return {
        **l,
        'growth_points': float(l.get('growth_points') or meta.get('points') or 0),
        'difficulty_name': meta.get('name', l.get('difficulty')),
        'difficulty_color': meta.get('color', '#A855F7'),
        'indicators': [{**i, 'is_completed': to_bool(i.get('is_completed'))} for i in indicators],
        'progress': {'done': done, 'total': total},
        'ready_to_complete': total > 0 and done == total and not to_bool(l.get('points_awarded')) and l.get('status') == 'active',
        'remaining_days': remaining,
        'points_awarded': to_bool(l.get('points_awarded')),
    }


def format_reward_purchase(p):
    status = p.get('outbound_status') or 'pending'
    return {
        **p,
        'price': float(p.get('price') or 0),
        'stock_after': int(p.get('stock_after') or 0),
        'balance_after': float(p.get('balance_after') or 0),
        'outbound_status': status,
        'outbound_status_label': '已出库' if status == 'shipped' else '待出库',
        'point_type_label': '历练点' if p.get('point_type') == 'practice' else '成长点',
    }
