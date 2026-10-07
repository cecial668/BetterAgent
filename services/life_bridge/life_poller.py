"""
向着星生活事件桥（services/life_bridge/life_poller.py）。

轮询向着星 `/api/agent/snapshot`（必要时再取一次结算流水算连续天数），把
"状态满足触发条件"翻译成生活事件，POST 到 Go Core 的 `/api/life-event`
（core/internal/webgateway/life_event_handler.go）。是否真的开口由 UrgeEngine
决定 —— 静默时段、每小时/每天上限、心情、冷却都在 Go 侧统一判定；本桥只负责
"什么时候值得提"，不自己抢答。

事件类型与权重见 config.yaml 的 `game_events.games.life`：
  morning_brief / evening_review / deadline_near / required_unfinished / streak_milestone

设计约定：
- 设置页关掉 `integration.tothestars.proactive.enabled` 后完全不发事件；
- 每个事件按天去重（临期按传说任务、里程碑按具体数值），桥重启最多让同一天
  多发一条，不会刷屏；
- 文案只给事实（几条、剩几天），真正的说法由角色卡与认知层决定。
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

import shared.config_loader as config_loader
from shared.config_loader import get_config_val
from shared.logger import setup_logger

logger = setup_logger("life_poller")

CONFIG_PATH = "integration.tothestars"

# 触发窗口（分钟数，本地时钟）。窗口内且条件满足才发对应事件。
MORNING_WINDOW = (7 * 60, 10 * 60 + 30)
EVENING_WINDOW = (21 * 60, 23 * 60)
REQUIRED_CHECK_AFTER = 20 * 60
DEFAULT_DEADLINE_DAYS = 3
STREAK_STEP = 7

DEFAULT_POLL_INTERVAL_SECONDS = 60


@dataclass
class LifeEvent:
    event_type: str
    detail: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 按天去重的键：同一天同一 key 只发一次。
    dedupe_key: str = ""


@dataclass
class BridgeState:
    # dedupe_key -> 已发送的逻辑日（YYYY-MM-DD）
    sent: Dict[str, str] = field(default_factory=dict)
    reachable: Optional[bool] = None

    def should_send(self, key: str, day: str) -> bool:
        return self.sent.get(key) != day

    def mark_sent(self, key: str, day: str) -> None:
        self.sent[key] = day


def _minute_of_day(now: datetime) -> int:
    return now.hour * 60 + now.minute


def _in_window(minute: int, window: tuple[int, int]) -> bool:
    return window[0] <= minute < window[1]


def _pending_required(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        q for q in (snapshot.get("commissions") or [])
        if q.get("is_required") and not q.get("is_completed")
    ]


def current_streak(settlements: List[Dict[str, Any]]) -> int:
    """连续成功结算天数（流水按日期倒序；遇到失败即断）。

    假期日也算成功（假期日本身就是允许休整的规则），None 视为未定不计。
    """
    streak = 0
    for row in settlements or []:
        success = row.get("is_success")
        if success is None:
            continue
        if int(success) == 1:
            streak += 1
        else:
            break
    return streak


def evaluate_events(
    snapshot: Dict[str, Any],
    settlements: List[Dict[str, Any]],
    now: datetime,
    state: BridgeState,
    deadline_days: int = DEFAULT_DEADLINE_DAYS,
) -> List[LifeEvent]:
    """纯函数：当前状态/时间下应该发哪些事件（不发送、不改 state）。"""
    if not isinstance(snapshot, dict):
        return []

    day = str(snapshot.get("date") or now.strftime("%Y-%m-%d"))
    minute = _minute_of_day(now)
    events: List[LifeEvent] = []

    commissions = snapshot.get("commissions")
    plans = ((snapshot.get("schedule") or {}).get("plans")) or []

    # 1. 晨间简报：早上窗口内、今天有委托或日程，每天一次。
    if _in_window(minute, MORNING_WINDOW) and commissions is not None:
        if commissions or plans:
            required = sum(1 for q in commissions if q.get("is_required"))
            if state.should_send("morning_brief", day):
                detail = f"今天 {len(commissions)} 条委托（必要 {required} 条）、{len(plans)} 项日程"
                events.append(LifeEvent(
                    "morning_brief", detail,
                    {"required_count": required, "plan_count": len(plans)},
                    dedupe_key="morning_brief",
                ))

    # 2. 必要委托未完成：20:00 之后，每天一次。
    pending = _pending_required(snapshot)
    if minute >= REQUIRED_CHECK_AFTER and pending and state.should_send("required_unfinished", day):
        names = "、".join(str(q.get("title") or "") for q in pending[:3])
        events.append(LifeEvent(
            "required_unfinished",
            f"必要委托还差 {len(pending)} 条：{names}",
            {"count": len(pending)},
            dedupe_key="required_unfinished",
        ))

    # 3. 传说任务临期：剩余天数 <= 阈值，按任务去重。
    for legend in snapshot.get("legends") or []:
        remaining = legend.get("remaining_days")
        if remaining is None:
            continue
        if 0 <= int(remaining) <= deadline_days:
            key = f"deadline_near:{legend.get('id')}"
            if state.should_send(key, day):
                days_text = "今天截止" if int(remaining) == 0 else f"只剩 {int(remaining)} 天"
                events.append(LifeEvent(
                    "deadline_near",
                    f"传说任务「{legend.get('title')}」{days_text}",
                    {"legend_id": legend.get("id"), "remaining_days": int(remaining)},
                    dedupe_key=key,
                ))

    # 4. 晚间复盘：晚间窗口内、今天还没写日记，每天一次。
    if _in_window(minute, EVENING_WINDOW) and not snapshot.get("journal"):
        if state.should_send("evening_review", day):
            events.append(LifeEvent(
                "evening_review", "今天还没有写日记",
                dedupe_key="evening_review",
            ))

    # 5. 连续完成里程碑：7/14/21... 天，按具体数值去重。
    streak = current_streak(settlements)
    if streak >= STREAK_STEP and streak % STREAK_STEP == 0:
        key = f"streak_milestone:{streak}"
        if state.should_send(key, day):
            events.append(LifeEvent(
                "streak_milestone", f"已经连续完成 {streak} 天",
                {"streak": streak},
                dedupe_key=key,
            ))

    return events


async def post_life_event(
    session: aiohttp.ClientSession,
    life_event_url: str,
    token: str,
    event: LifeEvent,
) -> bool:
    if not token:
        logger.debug("LIFE_EVENT_TOKEN not configured, skipping life event report")
        return False
    payload = {
        "event_type": event.event_type,
        "detail": event.detail,
        "metadata": event.metadata,
    }
    try:
        async with session.post(
            life_event_url,
            json=payload,
            headers={"X-Life-Event-Token": token},
            timeout=aiohttp.ClientTimeout(total=3),
        ) as resp:
            if resp.status == 200:
                logger.info(f"🌟 Reported life event: {event.event_type} -- {event.detail}")
                return True
            body = await resp.text()
            logger.warning(f"life-event POST for {event.event_type} returned {resp.status}: {body}")
    except Exception as e:
        logger.warning(f"Failed to POST life event {event.event_type}: {e}")
    return False


async def fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[Any]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception:
        return None


async def poll_once(
    session: aiohttp.ClientSession,
    endpoint: str,
    life_event_url: str,
    token: str,
    state: BridgeState,
    now: Optional[datetime] = None,
    deadline_days: int = DEFAULT_DEADLINE_DAYS,
) -> List[LifeEvent]:
    """一轮轮询：读快照 -> 判定 -> 上报。返回本轮成功上报的事件。"""
    now = now or datetime.now()
    base = endpoint.rstrip("/")
    snapshot = await fetch_json(session, f"{base}/api/agent/snapshot")

    if snapshot is None:
        if state.reachable is not False:
            logger.warning(f"向着星快照读取失败（{base}）—— 服务未启动或联动已关闭？")
            state.reachable = False
        return []

    if state.reachable is not True:
        logger.info(f"向着星快照连通（{base}）")
        state.reachable = True

    # 结算流水只用于连续天数；取不到就跳过里程碑判定，不影响其他事件。
    settlements = await fetch_json(session, f"{base}/api/stats/settlements") or []

    events = evaluate_events(snapshot, settlements, now, state, deadline_days)
    reported: List[LifeEvent] = []
    for event in events:
        if await post_life_event(session, life_event_url, token, event):
            state.mark_sent(event.dedupe_key, str(snapshot.get("date") or now.strftime("%Y-%m-%d")))
            reported.append(event)
    return reported


def _life_event_url() -> str:
    bind_addr = get_config_val("core_engine.game_event_bind_addr", "127.0.0.1:8090")
    return f"http://{bind_addr}/api/life-event"


def _config_mtime() -> float:
    """config.yaml 的修改时间（用于在设置页改动后刷新进程级配置缓存）。

    认知服务通过 NATS 的 agent.config.reloaded 刷新缓存；桥不订阅 NATS，
    这里用文件 mtime 达到同样效果：设置页保存后最多一个轮询周期内生效。
    """
    try:
        config_path = Path(config_loader.__file__).resolve().parents[1] / "config" / "config.yaml"
        return os.path.getmtime(config_path)
    except OSError:
        return 0.0


async def main():
    import dotenv

    dotenv.load_dotenv()

    token = os.getenv("LIFE_EVENT_TOKEN", "")
    life_event_url = _life_event_url()
    state = BridgeState()
    last_config_mtime = 0.0

    logger.info(f"向着星生活事件桥启动（life_event_url={life_event_url}）")
    if not token:
        logger.warning(
            "LIFE_EVENT_TOKEN 未配置：事件会被 Go Core 按 503 拒绝。"
            "复制 .env.example 并设置该值后重启 runner.py。"
        )

    async with aiohttp.ClientSession() as session:
        while True:
            current_mtime = _config_mtime()
            if current_mtime and current_mtime != last_config_mtime:
                config_loader.invalidate_cache()
                last_config_mtime = current_mtime

            if not get_config_val(f"{CONFIG_PATH}.enabled", False):
                if state.reachable is not False:
                    logger.info("向着星联动已关闭（integration.tothestars.enabled=false），桥暂停上报")
                    state.reachable = False
                await asyncio.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
                continue

            if not get_config_val(f"{CONFIG_PATH}.proactive.enabled", False):
                if state.reachable is not False:
                    logger.info("主动策略已关闭（proactive.enabled=false），桥暂停上报")
                    state.reachable = False
                await asyncio.sleep(DEFAULT_POLL_INTERVAL_SECONDS)
                continue

            endpoint = get_config_val(f"{CONFIG_PATH}.endpoint", "http://127.0.0.1:8765")
            interval = float(get_config_val(
                f"{CONFIG_PATH}.proactive.poll_interval_seconds",
                DEFAULT_POLL_INTERVAL_SECONDS,
            ))
            deadline_days = int(get_config_val(
                f"{CONFIG_PATH}.proactive.deadline_days", DEFAULT_DEADLINE_DAYS,
            ))

            await poll_once(session, endpoint, life_event_url, token, state, deadline_days=deadline_days)
            await asyncio.sleep(max(10.0, interval))


if __name__ == "__main__":
    asyncio.run(main())
