"""向着星（ToTheStars）生活数据工具族。

数据全部来自向着星后端的 Agent 接口（`GET /api/agent/snapshot` 等），
本模块不复制、不缓存任何生活数据，也不参与它的业务规则（结算/点数/顺延
全部留在向着星）。

只读工具（`tothestars_get_*`）直接查询即可；写入走「写入确认协议」：
- 模型看到的写工具全部是 ``tothestars_propose_*``，执行 ``execute()`` 时
  **只生成结构化提议，不产生任何写入**；
- 用户确认后由 cognitive_engine 调用本模块的 ``execute_proposal()`` 确定性
  执行（不再经过模型决策），向着星侧按 ``X-Actor: companion`` 记审计；
- 执行前按同一权限再次校验，防止"提议之后、执行之前权限被收回"仍写入。

权限口径（见 shared/life_data_permissions.py）：读工具要求 can_read，
提议工具要求 can_write；工具可见性由 cognitive_engine 每轮调用
``is_tool_visible()`` 门控。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import threading
from typing import Any, Dict, List, Optional

import httpx

from services.cognitive.tools.base_tool import BaseTool
from shared.life_data_permissions import (
    UNDO_CATEGORIES,
    can_be_proactive,
    can_read,
    can_write,
    get_tothestars_config,
    get_tothestars_endpoint,
    get_tothestars_timeout,
    is_tothestars_enabled,
)

logger = logging.getLogger("tothestars_tool")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CONNECTION_ERROR_MESSAGE = "暂时连不上向着星服务，先按没有这份数据回答，不要编造。"

# 本地直连桥按项目根目录缓存（导入与 Database 初始化只做一次）。
_LOCAL_BRIDGES: Dict[str, Any] = {}
_LOCAL_BRIDGES_LOCK = threading.Lock()


def _get_local_bridge(project_root: str):
    with _LOCAL_BRIDGES_LOCK:
        bridge = _LOCAL_BRIDGES.get(project_root)
        if bridge is None:
            from services.cognitive.tools.tothestars_local import LocalToTheStars

            bridge = LocalToTheStars(project_root)
            _LOCAL_BRIDGES[project_root] = bridge
        return bridge


class TothestarsClient:
    """向着星本地 REST 的薄客户端。写操作会带 ``X-Actor: companion`` 供审计区分来源。

    两种通道由 ``integration.tothestars.write_mode`` 决定：
    - ``local``  ：进程内直连向着星数据库（复用它的服务层，离线可用）；
    - ``remote`` ：HTTP；写失败（连不上/5xx）先暂存到待提交队列，后台自动重试。
    """

    def __init__(self, endpoint: Optional[str] = None, timeout: Optional[float] = None):
        self._endpoint = endpoint
        self._timeout = timeout

    @property
    def endpoint(self) -> str:
        return (self._endpoint or get_tothestars_endpoint()).rstrip("/")

    @property
    def timeout(self) -> float:
        return float(self._timeout or get_tothestars_timeout())

    async def request_json(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        config = get_tothestars_config()
        if config.get("write_mode") == "local":
            return await self._request_local(config, method, path, params, json_body)

        result = await self.request_json_http(method, path, params, json_body)
        if not result.get("ok") and (method or "GET").upper() != "GET" and result.get("retryable"):
            # 远程模式：网络性失败先暂存，后台按退避节奏补交（静默，不播报）。
            from shared.tothestars_outbox import enqueue

            item = enqueue(method, path, params, json_body)
            logger.info(
                f"📥 向着星写操作暂存待补交: {item['label']} ({method} {path}) —— {result.get('error')}"
            )
            return {
                "ok": True,
                "queued": True,
                "data": {"queued": True, "outbox_id": item["id"], "error": result.get("error", "")},
            }
        return result

    async def _request_local(
        self,
        config: Dict[str, Any],
        method: str,
        path: str,
        params: Optional[Dict[str, Any]],
        json_body: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        project_root = str(config.get("local_project_root") or "").strip()
        if not project_root:
            return {
                "ok": False,
                "error": "本地直连还没配置向着星项目路径（设置 → 生活数据）：填好路径或改用远程连接。",
            }
        bridge = _get_local_bridge(project_root)
        return await asyncio.to_thread(bridge.request_json, method, path, params, json_body)

    async def request_json_http(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """强制走 HTTP（不经过模式分发/暂存队列），供补交任务复用。"""
        url = f"{self.endpoint}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"X-Actor": "companion"},
                )
        except Exception as e:
            logger.warning(f"向着星请求失败 {method} {url}: {e}")
            return {"ok": False, "error": _CONNECTION_ERROR_MESSAGE, "retryable": True}

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str(resp.json().get("detail") or "")
            except Exception:
                pass
            logger.warning(f"向着星返回 {resp.status_code} {method} {url}: {detail[:200]}")
            return {
                "ok": False,
                "error": detail or f"向着星返回了错误（HTTP {resp.status_code}）。",
                # 5xx 多为服务暂时不可用，值得重试；4xx 是业务/参数错误，重试没意义。
                "retryable": resp.status_code >= 500,
            }

        try:
            return {"ok": True, "data": resp.json()}
        except ValueError:
            return {"ok": False, "error": "向着星返回了无法解析的数据。"}

    async def get_snapshot(self, include_journal_text: bool = False) -> Dict[str, Any]:
        return await self.request_json(
            "GET",
            "/api/agent/snapshot",
            params={"include_journal_text": "true" if include_journal_text else "false"},
        )

    async def get_commissions(self, date: Optional[str] = None) -> Dict[str, Any]:
        return await self.request_json("GET", "/api/quests", params={"date": date} if date else None)

    async def get_schedule(self, date: Optional[str] = None, scope: str = "day") -> Dict[str, Any]:
        path = "/api/schedule/week" if scope == "week" else "/api/schedule/day"
        return await self.request_json("GET", path, params={"date": date} if date else None)

    async def get_legends(self) -> Dict[str, Any]:
        return await self.request_json("GET", "/api/legends")

    async def get_today_journal(self) -> Dict[str, Any]:
        return await self.request_json("GET", "/api/states/today")

    async def get_journal(self, date: Optional[str] = None, include_text: bool = False) -> Dict[str, Any]:
        """读取某天日记（缺省今天）。历史日期走 agent/snapshot?date= —— 它是
        唯一带日期参数的日记入口，字段与 /states/today 同源但做了裁剪。"""
        if not date:
            return await self.request_json("GET", "/api/states/today")
        result = await self.request_json(
            "GET",
            "/api/agent/snapshot",
            params={
                "date": date,
                "include_journal_text": "true" if include_text else "false",
            },
        )
        if not result.get("ok"):
            return result
        journal = (result.get("data") or {}).get("journal")
        if not journal:
            return {"ok": False, "error": f"{date} 没有日记记录（这一天没写，或还没开始写）。"}
        return {"ok": True, "data": journal}

    async def get_audit(self, limit: int = 50) -> Dict[str, Any]:
        return await self.request_json("GET", "/api/agent/audit", params={"limit": max(1, min(int(limit), 500))})

    async def create_focus_session(
        self,
        *,
        started_at: str,
        ended_at: str,
        planned_minutes: int,
        duration_seconds: int,
        category: str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        """写入一条番茄钟专注记录（POST /focus/sessions）。

        与其它写操作一样带 X-Actor: companion；业务校验（时长 ≤ 计划+5s、
        时间先后）仍在向着星 FocusService 里，这里只负责送达。
        """
        return await self.request_json(
            "POST",
            "/api/focus/sessions",
            json_body={
                "started_at": started_at,
                "ended_at": ended_at,
                "planned_minutes": int(planned_minutes),
                "duration_seconds": int(duration_seconds),
                "category": category or "未分类",
                "description": description or "",
            },
        )


def _clean_date(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    return text if _DATE_RE.match(text) else None


def _titles(items: List[Dict[str, Any]], limit: int = 4) -> str:
    names = [str(i.get("title") or "").strip() for i in items if str(i.get("title") or "").strip()]
    shown = "、".join(names[:limit])
    if len(names) > limit:
        shown += f" 等 {len(names)} 条"
    return shown


def _strip_journal_text(journal: Dict[str, Any]) -> Dict[str, Any]:
    keep = {k: v for k, v in journal.items() if k not in ("review_text", "images", "image_urls")}
    keep["text_available"] = bool(str(journal.get("review_text") or "").strip())
    return keep


def snapshot_with_permissions(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """按当前权限裁剪 `/api/agent/snapshot` 的返回，hidden 类目直接缺席。"""
    if not isinstance(snapshot, dict):
        return {}

    out: Dict[str, Any] = {
        "date": snapshot.get("date"),
        "is_vacation": snapshot.get("is_vacation"),
    }
    if can_read("commissions"):
        out["condition"] = snapshot.get("condition")
        out["commissions"] = snapshot.get("commissions") or []
    if can_read("schedule"):
        out["schedule"] = snapshot.get("schedule") or {}
    if can_read("legends"):
        out["legends"] = snapshot.get("legends") or []
    if can_read("wallet"):
        out["wallet"] = snapshot.get("wallet") or {}
    if can_read("journal"):
        journal = snapshot.get("journal")
        if isinstance(journal, dict):
            journal = journal if can_read("journal_text") else _strip_journal_text(journal)
        out["journal"] = journal
    return out


def render_snapshot_for_prompt(snapshot: Dict[str, Any]) -> str:
    """把快照压缩成一段提示词文本；只渲染允许"主动提及"的类目。

    日记只给心情/能量，不给标题与正文——即使是 read_only/可主动提及档，
    正文也只有在 journal_text 权限允许且用户问起时由工具返回。
    """
    if not isinstance(snapshot, dict):
        return ""

    lines: List[str] = []

    commissions = snapshot.get("commissions") or []
    if commissions and can_be_proactive("commissions"):
        done = [q for q in commissions if q.get("is_completed")]
        line = f"委托：今日 {len(commissions)} 条，已完成 {len(done)}"
        unfinished_required = [q for q in commissions if q.get("is_required") and not q.get("is_completed")]
        if unfinished_required:
            line += f"；必要委托未完成：{_titles(unfinished_required)}"
        unfinished_optional = [q for q in commissions if not q.get("is_required") and not q.get("is_completed")]
        if unfinished_optional:
            line += f"；其他未完成：{_titles(unfinished_optional)}"
        lines.append(line)

    plans = (snapshot.get("schedule") or {}).get("plans") or []
    if plans and can_be_proactive("schedule"):
        parts = []
        for plan in plans[:5]:
            mark = "（已完成）" if plan.get("completed") else ""
            parts.append(f"{plan.get('start')}-{plan.get('end')} {plan.get('title')}{mark}")
        lines.append("日程：" + "；".join(parts))

    legends = snapshot.get("legends") or []
    if legends and can_be_proactive("legends"):
        parts = []
        for legend in legends[:3]:
            progress = legend.get("progress") or {}
            part = f"「{legend.get('title')}」{progress.get('done', '?')}/{progress.get('total', '?')}"
            if legend.get("deadline"):
                part += f"，截止 {legend.get('deadline')}"
                if legend.get("remaining_days") is not None:
                    part += f"（剩 {legend.get('remaining_days')} 天）"
            parts.append(part)
        lines.append("传说任务：" + "；".join(parts))

    wallet = snapshot.get("wallet") or {}
    if wallet and can_be_proactive("wallet"):
        practice = wallet.get("practice_points")
        growth = wallet.get("growth_points")
        if practice is not None or growth is not None:
            lines.append(f"点数：实践 {practice if practice is not None else '?'} / 成长 {growth if growth is not None else '?'}")

    journal = snapshot.get("journal")
    if isinstance(journal, dict) and can_be_proactive("journal"):
        bits = []
        if journal.get("rating") is not None:
            bits.append(f"评分 {journal.get('rating')}/5")
        if journal.get("energy") is not None:
            bits.append(f"能量 {journal.get('energy'):+g}" if isinstance(journal.get("energy"), (int, float)) else f"能量 {journal.get('energy')}")
        emotions = journal.get("emotions") or []
        if emotions:
            bits.append("情绪：" + "、".join(str(e) for e in emotions[:4]))
        if bits:
            lines.append("今日心情：" + "，".join(bits))

    if not lines:
        return ""
    return (
        f"[向着星·今日生活快照 {snapshot.get('date') or ''}]\n"
        + "\n".join(f"- {line}" for line in lines)
    )


def fetch_life_snapshot_block() -> str:
    """同步拉取快照并渲染成提示词片段（供 PromptBuilder 注入）。

    只读、短超时、失败静默（返回空串）——向着星没开时绝不能拖慢或打断聊天。
    永远不带 include_journal_text：正文只允许通过用户明确问起的工具路径获取。
    """
    if not is_tothestars_enabled():
        return ""
    try:
        with httpx.Client(timeout=get_tothestars_timeout(), trust_env=False) as client:
            resp = client.get(
                f"{get_tothestars_endpoint()}/api/agent/snapshot",
                params={"include_journal_text": "false"},
                headers={"X-Actor": "companion"},
            )
            if resp.status_code != 200:
                logger.debug(f"快照注入跳过：向着星返回 HTTP {resp.status_code}")
                return ""
            snapshot = resp.json()
    except Exception as e:
        logger.debug(f"快照注入跳过：连不上向着星（{e}）")
        return ""
    try:
        return render_snapshot_for_prompt(snapshot)
    except Exception as e:
        logger.warning(f"快照渲染失败: {e}")
        return ""


class _TothestarsReadTool(BaseTool):
    """只读工具公共基类：统一总开关与类目权限的二次校验。"""

    category: str = ""
    tool_params: Dict[str, Any] = {}

    def __init__(self, client: Optional[TothestarsClient] = None):
        self._client = client or TothestarsClient()

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": self.tool_params, "required": []}

    def _denied(self) -> Dict[str, Any]:
        return {
            "status": "denied",
            "message": "对方没有把这类生活数据开放给你查看，如实说明你看不到这部分，不要猜测。",
        }

    def _offline(self, error: str) -> Dict[str, Any]:
        return {"status": "failed", "error": error, "message": _CONNECTION_ERROR_MESSAGE}

    def _guard(self) -> Optional[Dict[str, Any]]:
        if not is_tothestars_enabled():
            return self._offline("向着星联动已关闭")
        if not can_read(self.category):
            return self._denied()
        return None

    @staticmethod
    def _ok(data: Any) -> Dict[str, Any]:
        return {"status": "success", "data": data}


class ToTheStarsLifeSnapshotTool(_TothestarsReadTool):
    """今日生活快照（聚合只读）。"""

    category = "commissions"

    @property
    def name(self) -> str:
        return "tothestars_get_life_snapshot"

    @property
    def description(self) -> str:
        return (
            "读取对方在《向着星》里的今日生活概览：委托完成度、今日日程、传说任务进度、"
            "点数与日记摘要（内容受对方的权限设置限制，没有的字段说明看不到）。"
            "当对方问'我今天还有什么没做'、'今天什么安排'或你需要了解其今日状态时调用。"
            "只读，不会修改任何数据。"
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if not is_tothestars_enabled():
            return self._offline("向着星联动已关闭")
        result = await self._client.get_snapshot(include_journal_text=False)
        if not result["ok"]:
            return self._offline(result["error"])
        return self._ok(snapshot_with_permissions(result["data"]))


class ToTheStarsCommissionsTool(_TothestarsReadTool):
    """查询某日委托清单（只读）。"""

    category = "commissions"

    @property
    def name(self) -> str:
        return "tothestars_get_commissions"

    @property
    def description(self) -> str:
        return (
            "查询对方《向着星》里某一天的每日委托清单（标题、难度、是否必要、完成状态）。"
            "date 用 YYYY-MM-DD，省略为今天；注意该应用的'今天'以凌晨 4 点为界。"
            "需要确认委托编号（id）供后续操作时也用这个工具。只读。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "date": {"type": "string", "description": "日期 YYYY-MM-DD，省略为今天。"},
        }

    async def execute(self, date: str = "", **kwargs) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        clean = _clean_date(date)
        if date and not clean:
            return {"status": "failed", "error": "日期格式应为 YYYY-MM-DD"}
        result = await self._client.get_commissions(clean)
        if not result["ok"]:
            return self._offline(result["error"])
        commissions = result["data"] if isinstance(result["data"], list) else []
        return self._ok({"date": clean or "today", "commissions": commissions})


class ToTheStarsScheduleTool(_TothestarsReadTool):
    """查询日程（只读）。"""

    category = "schedule"

    @property
    def name(self) -> str:
        return "tothestars_get_schedule"

    @property
    def description(self) -> str:
        return (
            "查询对方《向着星》里的日程安排。scope=day（默认）返回某天时间轴，"
            "scope=week 返回以该日期所在周为单位的整周视图。date 省略为今天。只读。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "date": {"type": "string", "description": "日期 YYYY-MM-DD，省略为今天。"},
            "scope": {"type": "string", "enum": ["day", "week"], "description": "day=日视图（默认），week=周视图。"},
        }

    async def execute(self, date: str = "", scope: str = "day", **kwargs) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        clean = _clean_date(date)
        if date and not clean:
            return {"status": "failed", "error": "日期格式应为 YYYY-MM-DD"}
        result = await self._client.get_schedule(clean, "week" if scope == "week" else "day")
        if not result["ok"]:
            return self._offline(result["error"])
        return self._ok(result["data"])


class ToTheStarsLegendProgressTool(_TothestarsReadTool):
    """查询传说任务进度（只读）。"""

    category = "legends"

    @property
    def name(self) -> str:
        return "tothestars_get_legend_progress"

    @property
    def description(self) -> str:
        return (
            "查询对方《向着星》的传说任务（长期目标）：指标清单、完成进度、截止日期。"
            "对方聊到长期计划、复习目标或问'我的传说任务怎么样了'时调用。只读。"
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        result = await self._client.get_legends()
        if not result["ok"]:
            return self._offline(result["error"])
        return self._ok(result["data"])


class ToTheStarsJournalSummaryTool(_TothestarsReadTool):
    """今日日记摘要（只读，仅在用户明确问起时调用）。"""

    category = "journal"

    @property
    def name(self) -> str:
        return "tothestars_get_journal_summary"

    @property
    def description(self) -> str:
        return (
            "读取对方《向着星》日记的摘要（心情评分、能量、情绪标签）。"
            "只应当在对方明确问起日记/心情时调用，不要主动提起。"
            "对方问「昨天/某天」的日记时，把 date 传成对应日期（YYYY-MM-DD）；"
            "不传 date = 今天。include_text=true 可请求日记正文，"
            "但只有对方开放了正文权限时才会返回；返回里没有正文就如实说看不到，"
            "不要编造。只读。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "date": {"type": "string", "description": "要读的日期 YYYY-MM-DD；省略 = 今天。「昨天」要换算成具体日期。"},
            "include_text": {"type": "boolean", "description": "是否请求日记正文（默认 false，且受权限限制）。"},
        }

    async def execute(self, include_text: bool = False, date: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        want_text = bool(include_text and can_read("journal_text"))
        clean_date = str(date).strip() if isinstance(date, str) and date.strip() else None
        result = await self._client.get_journal(date=clean_date, include_text=want_text)
        if not result["ok"]:
            return self._offline(result["error"])
        data = result["data"]
        if not isinstance(data, dict):
            return self._ok(None)
        if not want_text:
            data = _strip_journal_text(data)
        return self._ok(data)


# ---------------------------------------------------------------------------
# 写入确认协议：提议工具族 + 确定性执行器
# ---------------------------------------------------------------------------

PROPOSAL_STATUS = "needs_confirmation"

PROPOSAL_EXECUTION_LABELS = {
    "commission.create": "正在把新委托写进你的委托本…",
    "commission.complete": "正在更新委托的完成状态…",
    "commission.update": "正在修改委托内容…",
    "schedule.add": "正在把计划填进日程表…",
    "audit.undo": "正在把刚才那步操作撤销…",
}

_ACTION_LABELS = {
    "quest.create": "新增委托",
    "quest.update": "修改委托",
    "quest.complete": "更新委托完成状态",
    "quest.delete": "删除委托",
    "schedule.create": "新增日程",
    "schedule.update": "修改日程",
    "schedule.delete": "删除日程",
    "legend.create": "新增传说任务",
    "legend.update": "修改传说任务",
    "legend.delete": "删除传说任务",
    "legend.complete": "完成传说任务",
    "legend.indicator.add": "新增传说任务指标",
    "legend.indicator.complete": "勾选传说任务指标",
}

_ACTION_CATEGORY = {"quest": "commissions", "schedule": "schedule", "legend": "legends"}

_UPDATE_FIELD_LABELS = {
    "title": "标题",
    "description": "描述",
    "difficulty": "难度",
    "category": "分类",
    "is_required": "必要委托",
    "is_recurring": "日常委托",
}

_DIFFICULTIES = ("A", "B", "C", "D")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

_TIME_PARAM = {"type": "string", "description": "24 小时制时间，格式 HH:MM，例如 20:00。"}
_DATE_PARAM = {"type": "string", "description": "日期 YYYY-MM-DD；省略表示今天（该应用以凌晨 4 点为日界）。"}


def render_proposal_activity_label(kind: str) -> str:
    return PROPOSAL_EXECUTION_LABELS.get(kind, "正在写入向着星…")


def _proposal(kind: str, params: Dict[str, Any], summary: str) -> Dict[str, Any]:
    return {"status": PROPOSAL_STATUS, "proposal": {"kind": kind, "params": params, "summary": summary}}


def _failed(error: str) -> Dict[str, Any]:
    return {"status": "failed", "error": error}


def _queued(label: str = "") -> Dict[str, Any]:
    """远程模式下写操作已暂存待补交（不是失败，也不是立刻成功）。"""
    what = f"「{label}」" if label else "这次修改"
    return {
        "status": "queued",
        "message": f"{what}已先暂存在我这儿，等向着星恢复我就自动补交，不用你再确认。",
    }


def _denied_write(category: str) -> Dict[str, Any]:
    label = {"commissions": "委托", "schedule": "日程", "legends": "传说任务"}.get(category, "这类数据")
    return {"status": "denied", "message": f"对方已经收回了{label}的修改权限，这次没有执行任何写入。"}


def _display_change(field: str, old: Any, new: Any) -> str:
    label = _UPDATE_FIELD_LABELS.get(field, field)
    if field in ("is_required", "is_recurring"):
        return f"{label} {'是' if old else '否'}→{'是' if new else '否'}"
    return f"{label}「{old or '空'}」→「{new or '空'}」"


# 确认框里允许用户手动编辑的字段（按提议类型）。白名单之外的字段一律忽略：
# 哪怕前端被篡改，也只能改这些"本来就是给人改的"业务字段；服务端执行前仍会
# 走 execute_proposal 的完整校验（难度、日期、权限、存在性……）。
_LIFE_EDIT_FIELDS: Dict[str, tuple] = {
    "commission.create": (
        "title", "description", "difficulty", "category", "is_required", "is_recurring", "assigned_date",
    ),
    "commission.complete": ("completed",),
    "commission.update": (
        "title", "description", "difficulty", "category", "is_required", "is_recurring",
    ),
    "schedule.add": ("plan_date", "title", "content", "start", "end"),
    "audit.undo": (),
    # 专注模式（番茄钟）提议：用户可在确认框里调整分钟数。
    "focus.start": ("minutes",),
}

_BOOL_EDIT_FIELDS = ("is_required", "is_recurring", "completed")
_DATE_EDIT_FIELDS = ("assigned_date", "plan_date")
_INT_EDIT_FIELDS = ("minutes",)


def apply_life_proposal_edits(
    kind: str,
    params: Optional[Dict[str, Any]],
    edits: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """把确认框里的手改字段合并进提议参数（返回新 dict，不改原对象）。

    commission.update 的可编辑字段在嵌套的 body 里；其余类型直接改顶层。
    布尔字段强制转 bool 并保留 False（不能用真值判断跳过）；日期做一次
    YYYY-MM-DD 归一，非法值原样留下交给 execute_proposal 报错，绝不静默丢弃。
    """
    merged = copy.deepcopy(params or {})
    if not edits:
        return merged

    allowed = _LIFE_EDIT_FIELDS.get(kind, ())
    target = merged.get("body") if kind == "commission.update" else merged
    if not isinstance(target, dict):
        return merged

    for field in allowed:
        if field not in edits:
            continue
        value = edits[field]
        if value is None:
            continue
        if field in _BOOL_EDIT_FIELDS:
            target[field] = bool(value)
            continue
        if field in _INT_EDIT_FIELDS:
            # 分钟数：能转 int 就转，转不了原样留下交给执行端钳制/报错。
            try:
                target[field] = int(value)
            except (TypeError, ValueError):
                target[field] = value
            continue
        text = str(value).strip()
        if field in _DATE_EDIT_FIELDS:
            text = _clean_date(text) or text
        target[field] = text

    if isinstance(target.get("difficulty"), str):
        target["difficulty"] = target["difficulty"].strip().upper()
    return merged


class _TothestarsProposalTool(BaseTool):
    """提议工具公共基类：只检查权限与参数，绝不调用任何写接口。"""

    category: str = ""
    tool_params: Dict[str, Any] = {}
    required_params: List[str] = []

    def __init__(self, client: Optional[TothestarsClient] = None):
        self._client = client or TothestarsClient()

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": self.tool_params, "required": list(self.required_params)}

    def _guard(self) -> Optional[Dict[str, Any]]:
        if not is_tothestars_enabled():
            return _failed("向着星联动已关闭，无法写入")
        if not can_write(self.category):
            return _denied_write(self.category)
        return None

    async def _find_quest(self, quest_id: Any, date: Optional[str]) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """按日期取当天委托并找到编号；找不到时返回 (None, 失败结果)。"""
        try:
            qid = int(quest_id)
        except (TypeError, ValueError):
            return None, _failed("委托编号必须是数字")
        result = await self._client.get_commissions(date)
        if not result["ok"]:
            return None, _failed(result["error"])
        quests = result["data"] if isinstance(result["data"], list) else []
        quest = next((q for q in quests if int(q.get("id") or 0) == qid), None)
        if not quest:
            where = f"{date} 的" if date else "今天的"
            return None, _failed(
                f"在{where}委托列表里没找到编号 #{qid}。先用 tothestars_get_commissions 查看当天列表，用正确的编号再提议。"
            )
        return quest, None


class CreateCommissionProposalTool(_TothestarsProposalTool):
    """新增委托：只提议，不写入。"""

    category = "commissions"

    @property
    def name(self) -> str:
        return "tothestars_propose_create_commission"

    @property
    def description(self) -> str:
        return (
            "为对方新增一条每日委托。这是【提议工具】：只生成待确认的提案，"
            "不会写入任何数据——对方确认后系统才会真正写入。"
            "提议前先和对方确认清楚标题、难度（A/B/C/D）、是否必要委托、日期；"
            "需要先看当天列表时用 tothestars_get_commissions。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "title": {"type": "string", "description": "委托标题。"},
            "difficulty": {"type": "string", "enum": list(_DIFFICULTIES), "description": "难度 A/B/C/D。"},
            "description": {"type": "string", "description": "补充说明，可省略。"},
            "category": {"type": "string", "description": "分类，例如 学习/生活，可省略。"},
            "is_required": {"type": "boolean", "description": "是否必要委托，默认 false。"},
            "is_recurring": {"type": "boolean", "description": "是否日常重复委托，默认 false。"},
            "assigned_date": _DATE_PARAM,
        }

    @property
    def required_params(self) -> List[str]:
        return ["title", "difficulty"]

    async def execute(
        self,
        title: str,
        difficulty: str,
        description: str = "",
        category: str = "",
        is_required: bool = False,
        is_recurring: bool = False,
        assigned_date: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        title = str(title or "").strip()
        if not title:
            return _failed("委托标题不能为空")
        difficulty = str(difficulty or "").strip().upper()
        if difficulty not in _DIFFICULTIES:
            return _failed("难度需要是 A/B/C/D 之一")
        date = _clean_date(assigned_date)
        if assigned_date and not date:
            return _failed("日期格式应为 YYYY-MM-DD")
        summary = f"新增委托「{title}」（难度 {difficulty}，{'必要委托' if is_required else '支线委托'}"
        summary += f"，日期 {date}）" if date else "）"
        return _proposal("commission.create", {
            "title": title,
            "description": str(description or ""),
            "difficulty": difficulty,
            "category": str(category or "").strip() or "未分类",
            "is_required": bool(is_required),
            "is_recurring": bool(is_recurring),
            "assigned_date": date,
        }, summary)


class CompleteCommissionProposalTool(_TothestarsProposalTool):
    """更新委托完成状态：只提议，不写入。"""

    category = "commissions"

    @property
    def name(self) -> str:
        return "tothestars_propose_complete_commission"

    @property
    def description(self) -> str:
        return (
            "把对方某条每日委托标记为已完成（或恢复为未完成）。这是【提议工具】："
            "只生成待确认的提案，不会写入。quest_id 必须来自 "
            "tothestars_get_commissions 的查询结果，不要凭记忆编造编号。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "quest_id": {"type": "integer", "description": "委托编号，来自当天委托列表。"},
            "completed": {"type": "boolean", "description": "true=标记完成（默认），false=恢复未完成。"},
            "date": _DATE_PARAM,
        }

    @property
    def required_params(self) -> List[str]:
        return ["quest_id"]

    async def execute(self, quest_id: int, completed: bool = True, date: str = "", **kwargs) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        clean = _clean_date(date)
        if date and not clean:
            return _failed("日期格式应为 YYYY-MM-DD")
        quest, failure = await self._find_quest(quest_id, clean)
        if failure:
            return failure
        title = quest.get("title") or f"#{quest_id}"
        summary = f"把委托「{title}」{'标记为已完成' if completed else '恢复为未完成'}"
        return _proposal("commission.complete", {
            "quest_id": int(quest_id),
            "completed": bool(completed),
        }, summary)


class UpdateCommissionProposalTool(_TothestarsProposalTool):
    """修改委托内容：只提议，不写入。"""

    category = "commissions"

    @property
    def name(self) -> str:
        return "tothestars_propose_update_commission"

    @property
    def description(self) -> str:
        return (
            "修改对方某条每日委托的标题/说明/难度/分类/必要属性。这是【提议工具】："
            "只生成待确认的提案，不会写入。只传需要改的字段；未传的字段保持原样。"
            "quest_id 必须来自 tothestars_get_commissions 的查询结果。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "quest_id": {"type": "integer", "description": "委托编号，来自当天委托列表。"},
            "date": _DATE_PARAM,
            "title": {"type": "string", "description": "新的标题（要改才传）。"},
            "description": {"type": "string", "description": "新的说明（要改才传）。"},
            "difficulty": {"type": "string", "enum": list(_DIFFICULTIES), "description": "新的难度（要改才传）。"},
            "category": {"type": "string", "description": "新的分类（要改才传）。"},
            "is_required": {"type": "boolean", "description": "是否必要委托（要改才传）。"},
            "is_recurring": {"type": "boolean", "description": "是否日常重复（要改才传）。"},
        }

    @property
    def required_params(self) -> List[str]:
        return ["quest_id"]

    async def execute(
        self,
        quest_id: int,
        date: str = "",
        title: Optional[str] = None,
        description: Optional[str] = None,
        difficulty: Optional[str] = None,
        category: Optional[str] = None,
        is_required: Optional[bool] = None,
        is_recurring: Optional[bool] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        clean = _clean_date(date)
        if date and not clean:
            return _failed("日期格式应为 YYYY-MM-DD")
        quest, failure = await self._find_quest(quest_id, clean)
        if failure:
            return failure

        changes: Dict[str, Any] = {}
        if title is not None:
            new_title = str(title).strip()
            if not new_title:
                return _failed("委托标题不能改成空")
            changes["title"] = new_title
        if description is not None:
            changes["description"] = str(description)
        if difficulty is not None:
            new_difficulty = str(difficulty).strip().upper()
            if new_difficulty not in _DIFFICULTIES:
                return _failed("难度需要是 A/B/C/D 之一")
            changes["difficulty"] = new_difficulty
        if category is not None:
            changes["category"] = str(category).strip() or "未分类"
        if is_required is not None:
            changes["is_required"] = bool(is_required)
        if is_recurring is not None:
            changes["is_recurring"] = bool(is_recurring)
        if not changes:
            return _failed("没有给出要修改的内容")

        body = {
            "title": changes.get("title", quest.get("title") or ""),
            "description": changes.get("description", quest.get("description") or ""),
            "difficulty": changes.get("difficulty", quest.get("difficulty")),
            "category": changes.get("category", quest.get("category") or "未分类"),
            "is_required": changes.get("is_required", bool(quest.get("is_required"))),
            "is_recurring": changes.get("is_recurring", bool(quest.get("is_recurring"))),
        }
        diffs = [_display_change(field, quest.get(field), value) for field, value in changes.items()]
        summary = f"修改委托「{quest.get('title') or f'#{int(quest_id)}'}」：" + "、".join(diffs)
        return _proposal("commission.update", {
            "quest_id": int(quest_id),
            "body": body,
        }, summary)


class AddSchedulePlanProposalTool(_TothestarsProposalTool):
    """新增日程计划：只提议，不写入。"""

    category = "schedule"

    @property
    def name(self) -> str:
        return "tothestars_propose_add_schedule_plan"

    @property
    def description(self) -> str:
        return (
            "为对方在日程表里新增一条计划（可绑定已有委托，也可以是自定义计划）。"
            "这是【提议工具】：只生成待确认的提案，不会写入。"
            "start/end 用 HH:MM；要么给标题，要么给 quest_id 绑定委托。"
            "如果对方一次要排多条（例如同时加「健身」和「英语角」），"
            "请在同一轮里对本工具发起多次调用（每条一次），系统会为每条生成一个确认框，"
            "对方逐条确认——不要合并成一次调用，也不要只排一条然后让对方再等。"
        )

    @property
    def tool_params(self) -> Dict[str, Any]:
        return {
            "start": _TIME_PARAM,
            "end": _TIME_PARAM,
            "title": {"type": "string", "description": "计划标题（绑定委托时可省略）。"},
            "content": {"type": "string", "description": "计划说明，可省略。"},
            "plan_date": _DATE_PARAM,
            "quest_id": {"type": "integer", "description": "要绑定的委托编号，自定义计划可省略。"},
        }

    @property
    def required_params(self) -> List[str]:
        return ["start", "end"]

    async def execute(
        self,
        start: str,
        end: str,
        title: str = "",
        content: str = "",
        plan_date: str = "",
        quest_id: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        start_text, end_text = str(start or "").strip(), str(end or "").strip()
        if not _TIME_RE.match(start_text) or not _TIME_RE.match(end_text):
            return _failed("时间格式应为 HH:MM（24 小时制）")
        qid: Optional[int] = None
        if quest_id not in (None, ""):
            try:
                qid = int(quest_id)
            except (TypeError, ValueError):
                return _failed("委托编号必须是数字")
        title = str(title or "").strip()
        if not title and qid is None:
            return _failed("给计划起个名字，或者告诉我绑定哪条委托（quest_id）")
        date = _clean_date(plan_date)
        if plan_date and not date:
            return _failed("日期格式应为 YYYY-MM-DD")
        name = title or f"委托 #{qid}"
        summary = f"新增日程 {start_text}-{end_text}「{name}」"
        summary += f"，日期 {date}" if date else "，日期今天"
        return _proposal("schedule.add", {
            "plan_date": date,
            "title": title,
            "content": str(content or ""),
            "start": start_text,
            "end": end_text,
            "quest_id": qid,
        }, summary)


class UndoLastActionProposalTool(_TothestarsProposalTool):
    """撤销最近一次 AI 写入：只提议，不写入。"""

    @property
    def name(self) -> str:
        return "tothestars_propose_undo_last_action"

    @property
    def description(self) -> str:
        return (
            "撤销数字人（你）最近一次在向着星里做过的写入操作。这是【提议工具】："
            "先查到最近的可撤销记录并生成撤销提议，对方确认后系统才执行撤销。"
            "对方说『撤销刚才那步』『把刚加的删掉』时用它；不要凭记忆猜撤销对象。"
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if not is_tothestars_enabled():
            return _failed("向着星联动已关闭，无法撤销")
        writable = [c for c in UNDO_CATEGORIES if can_write(c)]
        if not writable:
            return _denied_write(writable[0] if writable else "commissions")

        result = await self._client.get_audit(limit=20)
        if not result["ok"]:
            return _failed(result["error"])
        entries = result["data"] if isinstance(result["data"], list) else []
        candidate = None
        for entry in entries:
            if entry.get("actor") != "companion" or not entry.get("undoable") or entry.get("undone"):
                continue
            action = str(entry.get("action") or "")
            category = _ACTION_CATEGORY.get(action.split(".")[0])
            if category in writable:
                candidate = entry
                break
        if not candidate:
            return {"status": "empty", "message": "最近没有可以撤销的操作。"}

        action = str(candidate.get("action") or "")
        label = _ACTION_LABELS.get(action, action)
        target = candidate.get("target_id")
        summary = f"撤销上一步操作：{label}" + (f"（#{target}）" if target is not None else "")
        return _proposal("audit.undo", {
            "audit_id": int(candidate["id"]),
            "category": _ACTION_CATEGORY.get(action.split(".")[0], ""),
        }, summary)


async def execute_proposal(
    kind: str,
    params: Dict[str, Any],
    client: Optional[TothestarsClient] = None,
) -> Dict[str, Any]:
    """确定性执行已确认的写入提议（唯一允许真正写向着星的入口）。

    只由 cognitive_engine 在用户确认后调用。执行前按类目权限二次校验。
    """
    client = client or TothestarsClient()
    if not is_tothestars_enabled():
        return _failed("向着星联动已关闭，写入没有执行")

    if kind == "commission.create":
        if not can_write("commissions"):
            return _denied_write("commissions")
        body = {key: params.get(key) for key in (
            "title", "description", "difficulty", "category", "is_required", "is_recurring", "assigned_date",
        )}
        result = await client.request_json("POST", "/api/quests", json_body=body)
        if not result["ok"]:
            return _failed(result["error"])
        if result.get("queued"):
            return _queued(str(params.get("title") or ""))
        qid = (result["data"] or {}).get("id")
        return {
            "status": "success",
            "message": f"已新增委托「{params.get('title')}」" + (f"（编号 #{qid}）" if qid else ""),
            "data": result["data"],
        }

    if kind == "commission.complete":
        if not can_write("commissions"):
            return _denied_write("commissions")
        try:
            qid = int(params.get("quest_id"))
        except (TypeError, ValueError):
            return _failed("委托编号无效，写入没有执行")
        completed = bool(params.get("completed", True))
        result = await client.request_json(
            "POST", f"/api/quests/{qid}/complete", json_body={"completed": completed},
        )
        if not result["ok"]:
            return _failed(result["error"])
        if result.get("queued"):
            return _queued(f"委托 #{qid} 的完成状态")
        return {
            "status": "success",
            "message": f"已把委托 #{qid} {'标记为已完成' if completed else '恢复为未完成'}",
            "data": result["data"],
        }

    if kind == "commission.update":
        if not can_write("commissions"):
            return _denied_write("commissions")
        try:
            qid = int(params.get("quest_id"))
        except (TypeError, ValueError):
            return _failed("委托编号无效，写入没有执行")
        body = params.get("body") or {}
        result = await client.request_json("PUT", f"/api/quests/{qid}", json_body=body)
        if not result["ok"]:
            return _failed(result["error"])
        if result.get("queued"):
            return _queued(f"委托 #{qid} 的修改")
        return {"status": "success", "message": f"已修改委托 #{qid}", "data": result["data"]}

    if kind == "schedule.add":
        if not can_write("schedule"):
            return _denied_write("schedule")
        body = {key: params.get(key) for key in (
            "plan_date", "title", "content", "start", "end", "quest_id",
        )}
        result = await client.request_json("POST", "/api/schedule/plans", json_body=body)
        if not result["ok"]:
            return _failed(result["error"])
        if result.get("queued"):
            return _queued(str(params.get("title") or "日程计划"))
        plan = result["data"] or {}
        plan_id = (plan.get("plan") or {}).get("id")
        return {
            "status": "success",
            "message": f"已新增日程「{params.get('title') or '委托计划'}」" + (f"（编号 #{plan_id}）" if plan_id else ""),
            "data": result["data"],
        }

    if kind == "audit.undo":
        category = str(params.get("category") or "")
        if not category or not can_write(category):
            return _denied_write(category or "commissions")
        try:
            audit_id = int(params.get("audit_id"))
        except (TypeError, ValueError):
            return _failed("撤销记录编号无效，写入没有执行")
        result = await client.request_json("POST", f"/api/agent/audit/{audit_id}/undo")
        if not result["ok"]:
            return _failed(result["error"])
        if result.get("queued"):
            return _queued("撤销操作")
        return {"status": "success", "message": "已撤销刚才那步操作", "data": result["data"]}

    return _failed(f"未知的提议类型: {kind}")


def build_tothestars_tools(client: Optional[TothestarsClient] = None) -> List[BaseTool]:
    return [
        ToTheStarsLifeSnapshotTool(client),
        ToTheStarsCommissionsTool(client),
        ToTheStarsScheduleTool(client),
        ToTheStarsLegendProgressTool(client),
        ToTheStarsJournalSummaryTool(client),
        CreateCommissionProposalTool(client),
        CompleteCommissionProposalTool(client),
        UpdateCommissionProposalTool(client),
        AddSchedulePlanProposalTool(client),
        UndoLastActionProposalTool(client),
    ]
