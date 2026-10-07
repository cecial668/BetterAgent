"""专注模式（番茄钟）工具族与确定性写入。

- ``ProposeFocusSessionTool``：只生成"开始专注"提议（确认框），不启动任何计时；
  用户在弹窗里调好分钟数点确认后，由 cognitive_engine 的确认协议发出
  FocusCommandPayload → Go 的 FocusManager 才真正开始计时。
- ``record_focus_session``：番茄钟自然结束后，用户已在「专注总结」弹窗里确认过
  分类与完成内容，这里把这条记录确定性地写进向着星的 focus_sessions。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from shared.life_data_permissions import can_write, is_tothestars_enabled
from services.cognitive.tools.base_tool import BaseTool
from services.cognitive.tools.tothestars_tool import PROPOSAL_STATUS, TothestarsClient

logger = logging.getLogger("focus_tool")

FOCUS_MIN_MINUTES = 5
FOCUS_MAX_MINUTES = 240
FOCUS_DEFAULT_MINUTES = 60


def clamp_focus_minutes(value: Any, default: int = FOCUS_DEFAULT_MINUTES) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = default
    return max(FOCUS_MIN_MINUTES, min(FOCUS_MAX_MINUTES, minutes))


class ProposeFocusSessionTool(BaseTool):
    """提议开始一次专注（番茄钟）。只生成确认框，不启动任何计时。"""

    @property
    def name(self) -> str:
        return "focus_propose_session"

    @property
    def description(self) -> str:
        return (
            "当对方想要进入专注/安静工作状态（如「我要安静干活一小时」「开始番茄钟」）时，"
            "提议开始一次专注（番茄钟）。这会先弹出一个确认框，对方可以在框里调整分钟数并点「确认」；"
            "确认后计时器才会启动、进入专注模式（期间除对方主动搭话外不打扰）。"
            "分钟数范围 5~240，默认 60；不要替对方决定过长的时长，也不要在对方没表达专注意图时主动提议。"
        )

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "minutes": {
                    "type": "integer",
                    "description": "计划专注的分钟数（5~240）。对方说「大概一个小时」就传 60；说不清就传 60。",
                },
                "reason": {
                    "type": "string",
                    "description": "对方打算做什么（可转述他/她的话），会显示在确认框摘要里，便于对方核对。",
                },
            },
            "required": [],
        }

    async def execute(self, minutes: int = FOCUS_DEFAULT_MINUTES, reason: str = "", **kwargs) -> Dict[str, Any]:
        planned = clamp_focus_minutes(minutes)
        detail = f"：{reason.strip()}" if isinstance(reason, str) and reason.strip() else ""
        return {
            "status": PROPOSAL_STATUS,
            "proposal": {
                "kind": "focus.start",
                "params": {"minutes": planned},
                "summary": f"开始一次 {planned} 分钟专注{detail}",
            },
        }


def format_focus_datetime(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(float(epoch_seconds)).strftime("%Y-%m-%d %H:%M:%S")


async def record_focus_session(
    *,
    started_at: str,
    ended_at: str,
    planned_minutes: int,
    duration_seconds: int,
    category: str = "",
    description: str = "",
    client: Optional[TothestarsClient] = None,
) -> Dict[str, Any]:
    """把一次自然完成的专注写进向着星（用户已通过总结弹窗确认过内容）。

    不走提议工具族：表单提交本身就是用户的确认，这里是确定性的记录动作。
    """
    if not is_tothestars_enabled():
        return {"status": "failed", "error": "向着星联动已关闭，这次专注没法记进去"}
    if not can_write("focus"):
        return {"status": "failed", "error": "对方已经收回了专注记录的写入权限，这次没有记录"}
    api = client or TothestarsClient()
    result = await api.create_focus_session(
        started_at=started_at,
        ended_at=ended_at,
        planned_minutes=int(planned_minutes),
        duration_seconds=int(duration_seconds),
        category=category,
        description=description,
    )
    if result.get("queued"):
        return {
            "status": "queued",
            "message": "这次专注已先暂存，等向着星恢复后自动补交（不需要再操作）。",
            "today_minutes": None,
        }
    if not result.get("ok"):
        return {"status": "failed", "error": result.get("error") or "写入向着星失败"}
    data = result.get("data") or {}
    today_seconds = int(data.get("today_seconds") or 0)
    return {
        "status": "success",
        "message": f"已记录 {max(1, int(duration_seconds) // 60)} 分钟专注（{category or '未分类'}）",
        "today_minutes": round(today_seconds / 60, 1),
        "session": data.get("session") or {},
    }
