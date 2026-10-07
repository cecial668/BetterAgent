"""Agent 操作审计与撤销服务。

职责边界：
- 记录路由层已经成功执行过的写操作（不改任何业务规则）；
- 撤销时只回放"逆操作"，且仍然调用既有 Service/Repo（结算、入池等规则不受影响）。

撤销载荷（undo_payload）由各写路由在成功之后生成，形如：
- quest.create      -> {"quest_id": int}
- quest.update      -> {"quest_id": int, "before": {...}}
- quest.complete    -> {"quest_id": int, "completed": bool}   # 撤销时恢复为原值
- quest.delete      -> {"snapshot": {...}}
- schedule.create   -> {"plan_id": int}
- schedule.update   -> {"plan_id": int, "before": {...}}
- schedule.delete   -> {"snapshot": {...}}
- legend.indicator.complete -> {"indicator_id": int, "completed": bool}
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.repositories.audit_repo import AuditRepo
from app.repositories.quest_repo import QuestRepo
from app.repositories.schedule_repo import ScheduleRepo
from app.services.daily_quest_service import DailyQuestService
from app.services.legend_service import LegendService
from app.services.schedule_service import ScheduleService, offset_to_label

QUEST_SNAPSHOT_FIELDS = (
    'title', 'description', 'difficulty', 'category',
    'is_required', 'is_recurring', 'assigned_date',
)
PLAN_SNAPSHOT_FIELDS = ('plan_date', 'title', 'content', 'start_minute', 'end_minute', 'quest_id')


class AuditService:
    def __init__(self, db):
        self.db = db
        self.repo = AuditRepo(db)

    # ---------- 记录 ----------

    def record(self, **kwargs) -> int:
        return self.repo.record(**kwargs)

    def snapshot_quest(self, quest_id: int) -> dict | None:
        row = QuestRepo(self.db).get(quest_id)
        if not row:
            return None
        return {k: row.get(k) for k in ('id', *QUEST_SNAPSHOT_FIELDS)}

    def snapshot_plan(self, plan_id: int) -> dict | None:
        row = ScheduleRepo(self.db).get(plan_id)
        if not row:
            return None
        return {k: row.get(k) for k in ('id', *PLAN_SNAPSHOT_FIELDS)}

    # ---------- 撤销 ----------

    def undo(self, audit_id: int, actor: str = 'me') -> dict:
        entry = self.repo.get(audit_id)
        if not entry:
            raise ValueError('找不到这条操作记录')
        if entry.get('undone_at'):
            raise ValueError('这条操作已经撤销过了')
        if not entry.get('undoable'):
            raise ValueError('这条操作不支持撤销（例如：奖励结算、批量操作或日记写入）')

        try:
            payload = json.loads(entry.get('undo_payload_json') or '{}')
        except json.JSONDecodeError:
            raise ValueError('撤销数据已损坏，无法撤销')

        note = self._dispatch(entry.get('action') or '', payload)
        self.repo.mark_undone(audit_id, note)
        # 撤销本身也进审计，保证"谁撤了什么"同样可追溯。
        self.repo.record(
            actor=actor,
            action='audit.undo',
            target_type='agent_audit',
            target_id=int(audit_id),
            params={'action': entry.get('action')},
            result={'note': note},
        )
        return {'ok': True, 'undone_id': int(audit_id), 'note': note}

    def _dispatch(self, action: str, payload: dict) -> str:
        if action == 'quest.create':
            quest_id = int(payload['quest_id'])
            ScheduleService(self.db).unbind_quests([quest_id])
            DailyQuestService(self.db).delete(quest_id)
            return f'已删除委托 #{quest_id}'

        if action == 'quest.update':
            quest_id = int(payload['quest_id'])
            before = payload['before']
            DailyQuestService(self.db).update(
                quest_id,
                before.get('title') or '',
                before.get('description') or '',
                before.get('difficulty'),
                before.get('category'),
                bool(before.get('is_required')),
                bool(before.get('is_recurring')),
            )
            ScheduleService(self.db).sync_quest(quest_id, before.get('title') or '', before.get('description') or '')
            return f'已恢复委托 #{quest_id} 的原始内容'

        if action == 'quest.complete':
            quest_id = int(payload['quest_id'])
            DailyQuestService(self.db).set_completed(quest_id, bool(payload.get('completed')))
            return f'已把委托 #{quest_id} 恢复为{"已完成" if payload.get("completed") else "未完成"}'

        if action == 'quest.delete':
            snapshot = payload['snapshot']
            qid = DailyQuestService(self.db).create(
                snapshot.get('title') or '未命名委托',
                snapshot.get('description') or '',
                snapshot.get('difficulty'),
                snapshot.get('category'),
                bool(snapshot.get('is_required')),
                snapshot.get('assigned_date'),
                bool(snapshot.get('is_recurring')),
            )
            return f'已按删除前的内容重建委托（新编号 #{qid}）'

        if action == 'schedule.create':
            plan_id = int(payload['plan_id'])
            ScheduleService(self.db).delete(plan_id)
            return f'已删除日程计划 #{plan_id}'

        if action == 'schedule.update':
            plan_id = int(payload['plan_id'])
            before = payload['before']
            ScheduleService(self.db).update(plan_id, self._plan_namespace(before))
            return f'已恢复日程计划 #{plan_id} 的原始时间与文案'

        if action == 'schedule.delete':
            snapshot = payload['snapshot']
            created = ScheduleService(self.db).create(self._plan_namespace(snapshot))
            return f'已按删除前的内容重建日程计划（新编号 #{created.get("id")}）'

        if action == 'legend.indicator.complete':
            indicator_id = int(payload['indicator_id'])
            LegendService(self.db).complete_indicator(indicator_id, bool(payload.get('completed')))
            return f'已把传说任务指标 #{indicator_id} 恢复为{"已完成" if payload.get("completed") else "未完成"}'

        raise ValueError(f'未知的撤销类型: {action}')

    @staticmethod
    def _plan_namespace(snapshot: dict) -> SimpleNamespace:
        return SimpleNamespace(
            plan_date=snapshot.get('plan_date'),
            title=snapshot.get('title') or '',
            content=snapshot.get('content') or '',
            start=offset_to_label(snapshot.get('start_minute') or 0),
            end=offset_to_label(snapshot.get('end_minute') or 0),
            quest_id=snapshot.get('quest_id'),
        )
