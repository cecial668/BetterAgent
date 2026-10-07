"""本地直连：在 BetterAgent 进程内复用向着星自己的服务层直接读写其 SQLite。

背景：两台应用同机部署时，HTTP 不是必需品 —— 向着星没启动时它的数据库文件
仍然在磁盘上。本模块把「向着星项目根目录」加入 ``sys.path``，实例化它自己的
``app.db.database.Database`` 并把请求分发给它自己的 Service/Repo，因此：

- 业务规则（难度、日界、日程冲突、审计/撤销……）与网页端**逐字一致**，不存在
  两套实现漂移的问题；
- 写操作仍然会写 ``agent_audit``（actor=companion），「AI 活动」页与撤销照常；
- 完全离线可用（不需要 8765 端口监听）。

线程安全：向着星 ``Database`` 每次调用新建连接，模块内只缓存导入与 Database
对象，并用锁保护首次初始化。调用方（asyncio）通过 ``asyncio.to_thread`` 调用。
"""
from __future__ import annotations

import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tothestars_local")


class LocalToTheStarsError(Exception):
    """本地直连的可预期失败（路径不对/业务校验失败）。"""


class LocalToTheStars:
    def __init__(self, project_root: str, db_path: Optional[str] = None):
        self.project_root = Path(project_root)
        self.db_path = Path(db_path) if db_path else self.project_root / "data" / "growth_system.db"
        self._db = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _ensure_ready(self):
        if self._db is not None:
            return
        with self._lock:
            if self._db is not None:
                return
            if not self.project_root.is_dir():
                raise LocalToTheStarsError(f"向着星项目路径不存在：{self.project_root}")
            if not self.db_path.is_file():
                raise LocalToTheStarsError(f"找不到向着星数据库文件：{self.db_path}")
            root = str(self.project_root)
            if root not in sys.path:
                sys.path.insert(0, root)
            try:
                from app.db.database import Database
            except Exception as exc:  # pragma: no cover - 环境损坏时给出人话
                raise LocalToTheStarsError(f"无法导入向着星服务代码（{root}）：{exc}")
            self._db = Database(self.db_path)
            logger.info(f"本地直连向着星已就绪: root={root} db={self.db_path}")

    # ------------------------------------------------------------------
    # 与 TothestarsClient.request_json 同形的分发入口
    # ------------------------------------------------------------------

    def request_json(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = (method or "GET").upper()
        params = params or {}
        json_body = json_body or {}
        try:
            self._ensure_ready()
            return self._dispatch(method, path, params, json_body)
        except LocalToTheStarsError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning(f"本地直连执行失败 {method} {path}: {exc}", exc_info=True)
            return {"ok": False, "error": f"本地直连失败：{exc}"}

    def _dispatch(self, method: str, path: str, params: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
        clean = path.split("?")[0].rstrip("/")

        if method == "GET":
            if clean == "/api/agent/snapshot":
                return self._snapshot(params)
            if clean == "/api/quests":
                return self._list_commissions(params.get("date"))
            if clean in ("/api/schedule/day", "/api/schedule/week"):
                return self._schedule(clean.rsplit("/", 1)[-1], params.get("date"))
            if clean == "/api/legends":
                return self._legends()
            if clean == "/api/states/today":
                return self._state_today()
            if clean == "/api/agent/audit":
                return self._audit_list(params.get("limit", 50), params.get("actor"))
            return {"ok": False, "error": f"本地直连暂不支持读取 {clean}"}

        if method == "POST":
            if clean == "/api/quests":
                return self._create_quest(body)
            if clean == "/api/schedule/plans":
                return self._create_schedule_plan(body)
            if clean == "/api/focus/sessions":
                return self._create_focus_session(body)
            m = re.fullmatch(r"/api/quests/(\d+)/complete", clean)
            if m:
                return self._complete_quest(int(m.group(1)), body)
            m = re.fullmatch(r"/api/agent/audit/(\d+)/undo", clean)
            if m:
                return self._undo_audit(int(m.group(1)))
            return {"ok": False, "error": f"本地直连暂不支持写入 {clean}"}

        if method == "PUT":
            m = re.fullmatch(r"/api/quests/(\d+)", clean)
            if m:
                return self._update_quest(int(m.group(1)), body)
            return {"ok": False, "error": f"本地直连暂不支持修改 {clean}"}

        return {"ok": False, "error": f"本地直连暂不支持方法 {method} {clean}"}

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def _snapshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from app.api.routes_common import condition_for, format_legend, format_quest, safe_json
        from app.core.date_utils import DAY_BOUNDARY_HOUR, today_str
        from app.services.daily_quest_service import DailyQuestService
        from app.services.legend_service import LegendService
        from app.services.schedule_service import ScheduleService
        from app.services.state_service import StateService
        from app.services.vacation_service import VacationService
        from app.services.wallet_service import WalletService

        db = self._db
        target = str(params.get("date") or "").strip() or today_str()
        include_text = str(params.get("include_journal_text", "false")).lower() == "true"

        formatted_quests = [format_quest(q) for q in DailyQuestService(db).list(target)]
        is_vacation = VacationService(db).is_vacation(target)
        day = ScheduleService(db).day(target)
        plans = [
            {
                "id": p["id"],
                "title": p["title"],
                "start": p["start_label"],
                "end": p["end_label"],
                "duration_label": p["duration_label"],
                "kind": p["kind"],
                "completed": p["completed"],
                "quest_id": p["quest_id"],
                "is_required": p["is_required"],
            }
            for p in day["plans"]
        ]

        legends = []
        legend_svc = LegendService(db)
        for legend in legend_svc.list():
            if legend.get("status") != "active":
                continue
            formatted = format_legend(legend, legend_svc.indicators(legend["id"]))
            legends.append({
                key: formatted.get(key)
                for key in (
                    "id", "title", "difficulty", "difficulty_name", "growth_points",
                    "deadline", "progress", "remaining_days", "ready_to_complete",
                )
            })

        journal = None
        state = StateService(db).get(target)
        if state:
            journal = {
                "date": state.get("date"),
                "journal_title": state.get("journal_title") or "",
                "rating": state.get("rating"),
                "emotions": safe_json(state.get("emotions"), []) or [],
                "energy": state.get("energy"),
                "social_type": state.get("social_type"),
                "social_feeling": state.get("social_feeling"),
                "has_text": bool((state.get("review_text") or "").strip()),
            }
            if include_text:
                journal["review_text"] = state.get("review_text") or ""
                journal["images"] = safe_json(state.get("images_json"), []) or []

        return {
            "ok": True,
            "data": {
                "date": target,
                "day_boundary_hour": DAY_BOUNDARY_HOUR,
                "is_vacation": is_vacation,
                "wallet": WalletService(db).get(),
                "condition": condition_for(formatted_quests, is_vacation),
                "commissions": [
                    {
                        key: q.get(key)
                        for key in (
                            "id", "title", "description", "difficulty", "difficulty_name", "points",
                            "category", "is_required", "is_completed", "banked_points", "assigned_date",
                        )
                    }
                    for q in formatted_quests
                ],
                "schedule": {"date": target, "plans": plans},
                "legends": legends,
                "journal": journal,
            },
        }

    def _list_commissions(self, date: Optional[str]) -> Dict[str, Any]:
        from app.api.routes_common import format_quest
        from app.core.date_utils import today_str
        from app.services.daily_quest_service import DailyQuestService

        target = str(date or "").strip() or today_str()
        quests = [format_quest(q) for q in DailyQuestService(self._db).list(target)]
        return {"ok": True, "data": quests}

    def _schedule(self, scope: str, date: Optional[str]) -> Dict[str, Any]:
        from app.services.schedule_service import ScheduleService

        svc = ScheduleService(self._db)
        try:
            data = svc.week(date) if scope == "week" else svc.day(date)
        except ValueError as exc:
            raise LocalToTheStarsError(str(exc))
        return {"ok": True, "data": data}

    def _legends(self) -> Dict[str, Any]:
        from app.services.legend_service import LegendService

        return {"ok": True, "data": LegendService(self._db).list()}

    def _state_today(self) -> Dict[str, Any]:
        from app.core.date_utils import today_str
        from app.services.state_service import StateService

        return {"ok": True, "data": StateService(self._db).get(today_str())}

    def _audit_list(self, limit: Any, actor: Optional[str]) -> Dict[str, Any]:
        from app.services.audit_service import AuditService

        try:
            lim = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            lim = 50
        rows = AuditService(self._db).repo.list(limit=lim, actor=actor or None)
        return {"ok": True, "data": rows}

    # ------------------------------------------------------------------
    # 写（与网页端路由逐字段一致，并写 agent_audit）
    # ------------------------------------------------------------------

    def _validated(self, schema_name: str, body: Dict[str, Any]):
        """用向着星自己的 pydantic 模型校验（与 HTTP 路由同一套规则）。"""
        import app.api.schemas as schemas

        schema = getattr(schemas, schema_name)
        from pydantic import ValidationError
        try:
            return schema(**body)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(x) for x in first.get("loc", ())) or "payload"
            raise LocalToTheStarsError(f"{field}: {first.get('msg', '参数不合法')}")

    def _actor(self) -> str:
        return "companion"

    def _create_quest(self, body: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.audit_service import AuditService
        from app.services.daily_quest_service import DailyQuestService

        payload = self._validated("QuestCreate", body)
        svc = DailyQuestService(self._db)
        qid = svc.create(
            payload.title,
            payload.description,
            payload.difficulty,
            payload.category,
            payload.is_required,
            payload.assigned_date,
            payload.is_recurring,
        )
        AuditService(self._db).record(
            actor=self._actor(), action="quest.create", target_type="daily_quest", target_id=qid,
            params=payload.model_dump(), result={"id": qid},
            undo_payload={"quest_id": qid}, undoable=True,
        )
        return {"ok": True, "data": {"ok": True, "id": qid}}

    def _complete_quest(self, qid: int, body: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.audit_service import AuditService
        from app.services.daily_quest_service import DailyQuestService

        payload = self._validated("CompleteRequest", body)
        audit = AuditService(self._db)
        before = audit.snapshot_quest(qid)
        try:
            DailyQuestService(self._db).set_completed(qid, payload.completed)
        except ValueError as exc:
            raise LocalToTheStarsError(str(exc))
        previous = bool(before.get("is_completed")) if before else (not payload.completed)
        audit.record(
            actor=self._actor(), action="quest.complete", target_type="daily_quest", target_id=qid,
            params={"completed": payload.completed}, result={"completed": payload.completed},
            undo_payload={"quest_id": qid, "completed": previous}, undoable=True,
        )
        return {"ok": True, "data": {"ok": True}}

    def _update_quest(self, qid: int, body: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.audit_service import AuditService
        from app.services.daily_quest_service import DailyQuestService
        from app.services.schedule_service import ScheduleService

        payload = self._validated("QuestUpdate", body)
        audit = AuditService(self._db)
        before = audit.snapshot_quest(qid)
        try:
            DailyQuestService(self._db).update(
                qid, payload.title, payload.description, payload.difficulty,
                payload.category, payload.is_required, payload.is_recurring,
            )
        except ValueError as exc:
            raise LocalToTheStarsError(str(exc))
        ScheduleService(self._db).sync_quest(qid, payload.title, payload.description)
        audit.record(
            actor=self._actor(), action="quest.update", target_type="daily_quest", target_id=qid,
            params=payload.model_dump(), result={"ok": True},
            undo_payload={"quest_id": qid, "before": before}, undoable=bool(before),
        )
        return {"ok": True, "data": {"ok": True}}

    def _create_schedule_plan(self, body: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.audit_service import AuditService
        from app.services.schedule_service import ScheduleService

        payload = self._validated("SchedulePlanCreate", body)
        try:
            plan = ScheduleService(self._db).create(payload)
        except ValueError as exc:
            raise LocalToTheStarsError(str(exc))
        AuditService(self._db).record(
            actor=self._actor(), action="schedule.create", target_type="schedule_plan", target_id=plan["id"],
            params=payload.model_dump(), result={"id": plan["id"], "date": plan["plan_date"]},
            undo_payload={"plan_id": plan["id"]}, undoable=True,
        )
        return {"ok": True, "data": {"ok": True, "plan": plan, "date": plan["plan_date"]}}

    def _create_focus_session(self, body: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.focus_service import FocusService

        payload = self._validated("FocusSessionCreate", body)
        try:
            return {"ok": True, "data": FocusService(self._db).create_session(payload)}
        except ValueError as exc:
            raise LocalToTheStarsError(str(exc))

    def _undo_audit(self, audit_id: int) -> Dict[str, Any]:
        from app.services.audit_service import AuditService

        try:
            data = AuditService(self._db).undo(audit_id, actor=self._actor())
        except ValueError as exc:
            raise LocalToTheStarsError(str(exc))
        return {"ok": True, "data": data}
