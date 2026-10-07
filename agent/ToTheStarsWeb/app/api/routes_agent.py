"""面向数字人（BetterAgent）的只读聚合接口与审计接口。

设计边界：
- 只读：/snapshot 一次返回"今日生活快照"，字段做了裁剪，方便 Agent 侧消费；
- 审计：/audit 列表 + /audit/{id}/undo 撤销；
- 不新增任何业务规则：数据全部来自既有 Service，写入仍走各自的写路由。
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.routes_common import (
    actor_of,
    condition_for,
    db,
    format_legend,
    format_quest,
    raise400,
    safe_json,
    today,
)
from app.core.date_utils import DAY_BOUNDARY_HOUR
from app.core.config import AGENT_CHAT_ID, AGENT_WS_TOKEN, AGENT_WS_URL
from app.services.audit_service import AuditService
from app.services.daily_quest_service import DailyQuestService
from app.services.legend_service import LegendService
from app.services.schedule_service import ScheduleService
from app.services.state_service import StateService
from app.services.vacation_service import VacationService
from app.services.wallet_service import WalletService

router = APIRouter(prefix='/agent')

COMMISSION_FIELDS = (
    'id', 'title', 'description', 'difficulty', 'difficulty_name', 'points',
    'category', 'is_required', 'is_completed', 'banked_points', 'assigned_date',
)
LEGEND_FIELDS = (
    'id', 'title', 'difficulty', 'difficulty_name', 'growth_points', 'deadline',
    'progress', 'remaining_days', 'ready_to_complete',
)


@router.get('/snapshot')
def snapshot(
    request: Request,
    date: str | None = Query(default=None),
    include_journal_text: bool = Query(default=False),
):
    """今日生活快照：委托 / 日程 / 传说任务 / 点数 / 日记摘要。"""
    target = date or today()
    quests_svc = DailyQuestService(db(request))
    formatted_quests = [format_quest(q) for q in quests_svc.list(target)]
    is_vacation = VacationService(db(request)).is_vacation(target)

    day = ScheduleService(db(request)).day(target)
    plans = [
        {
            'id': p['id'],
            'title': p['title'],
            'start': p['start_label'],
            'end': p['end_label'],
            'duration_label': p['duration_label'],
            'kind': p['kind'],
            'completed': p['completed'],
            'quest_id': p['quest_id'],
            'is_required': p['is_required'],
        }
        for p in day['plans']
    ]

    legends = []
    legend_svc = LegendService(db(request))
    for legend in legend_svc.list():
        if legend.get('status') != 'active':
            continue
        formatted = format_legend(legend, legend_svc.indicators(legend['id']))
        legends.append({key: formatted.get(key) for key in LEGEND_FIELDS})

    journal = None
    state = StateService(db(request)).get(target)
    if state:
        journal = {
            'date': state.get('date'),
            'journal_title': state.get('journal_title') or '',
            'rating': state.get('rating'),
            'emotions': safe_json(state.get('emotions'), []) or [],
            'energy': state.get('energy'),
            'social_type': state.get('social_type'),
            'social_feeling': state.get('social_feeling'),
            'has_text': bool((state.get('review_text') or '').strip()),
        }
        if include_journal_text:
            journal['review_text'] = state.get('review_text') or ''
            journal['images'] = safe_json(state.get('images_json'), []) or []

    return {
        'date': target,
        'day_boundary_hour': DAY_BOUNDARY_HOUR,
        'is_vacation': is_vacation,
        'wallet': WalletService(db(request)).get(),
        'condition': condition_for(formatted_quests, is_vacation),
        'commissions': [{key: q.get(key) for key in COMMISSION_FIELDS} for q in formatted_quests],
        'schedule': {'date': target, 'plans': plans},
        'legends': legends,
        'journal': journal,
    }


@router.get('/chat-config')
def chat_config():
    """数字人对话气泡的连接参数。

    缺省关闭：`AGENT_WS_TOKEN` 没配时返回 enabled=false，前端不渲染气泡 ——
    未部署 BetterAgent 的环境零变化。只有本机页面能读到 token（服务仅监听
    127.0.0.1），这就是气泡的访问控制边界。
    """
    token = (AGENT_WS_TOKEN or '').strip()
    return {
        'enabled': bool(token),
        'ws_url': AGENT_WS_URL,
        'token': token,
        'chat_id': AGENT_CHAT_ID,
    }


@router.get('/audit')
def audit_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    actor: str | None = Query(default=None),
):
    """Agent 操作流水（默认倒序），带可撤销标记。"""
    rows = AuditService(db(request)).repo.list(limit=limit, actor=actor)
    return [
        {
            'id': row['id'],
            'created_at': row['created_at'],
            'actor': row['actor'],
            'action': row['action'],
            'target_type': row.get('target_type') or '',
            'target_id': row.get('target_id'),
            'params': safe_json(row.get('params_json'), {}),
            'result': safe_json(row.get('result_json'), {}),
            'undoable': bool(row.get('undoable')),
            'undone': bool(row.get('undone_at')),
            'undone_at': row.get('undone_at') or '',
            'undo_note': row.get('undo_note') or '',
        }
        for row in rows
    ]


@router.post('/audit/{audit_id}/undo')
def audit_undo(audit_id: int, request: Request):
    return raise400(AuditService(db(request)).undo, audit_id, actor_of(request))
