"""向着星生活数据的四档权限门控（「AI 应该知道多少」的唯一真源）。

四档权限（每类数据独立配置，见 config.yaml 的 integration.tothestars.permissions）：

- ``read_write_proactive``: 可读、可写、可主动提及（默认：每日委托、日程）
- ``read_only``:            可读、不可写、可主动提及（默认：传说任务、点数）
- ``on_request``:           只有用户明确问起才可读，不主动提（默认：日记摘要）
- ``hidden``:               完全不可见——工具不进模型可见的 tools_schema，
  提示词也不注入（默认：日记正文与照片）

三条设计约定（与 shared/web_search_config.py 同口径）：

1. 默认最小权限：配置缺失、字段拼错、未知档位一律按 ``hidden`` 处理，绝不 fail-open。
2. 「工具可见」与「提示词注入」必须共用本模块的判断，否则会出现
   "提示词说不能读、工具却还能调"的割裂。
3. 本模块不自行缓存：读取走 shared.config_loader 的进程级缓存，后台改完配置由
   ``agent.config.reloaded`` 消费端调用 ``invalidate_cache()`` 刷新。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from shared.config_loader import get_config_val

logger = logging.getLogger("life_data_permissions")

CONFIG_PATH = "integration.tothestars"

TIER_READ_WRITE_PROACTIVE = "read_write_proactive"
TIER_READ_ONLY = "read_only"
TIER_ON_REQUEST = "on_request"
TIER_HIDDEN = "hidden"

PERMISSION_TIERS = (
    TIER_READ_WRITE_PROACTIVE,
    TIER_READ_ONLY,
    TIER_ON_REQUEST,
    TIER_HIDDEN,
)

CATEGORY_LABELS: Dict[str, str] = {
    "commissions": "每日委托",
    "schedule": "日程安排",
    "legends": "传说任务",
    "wallet": "点数钱包",
    "journal": "日记摘要",
    "journal_text": "日记正文",
    "focus": "专注/番茄钟",
}

DEFAULT_PERMISSIONS: Dict[str, str] = {
    "commissions": TIER_READ_WRITE_PROACTIVE,
    "schedule": TIER_READ_WRITE_PROACTIVE,
    "legends": TIER_READ_ONLY,
    "wallet": TIER_READ_ONLY,
    "journal": TIER_ON_REQUEST,
    "journal_text": TIER_HIDDEN,
    "focus": TIER_READ_WRITE_PROACTIVE,
}

# 工具名 -> 权限类目。快照工具要聚合多类数据，单独判定（见 is_tool_visible）。
TOOL_CATEGORY: Dict[str, str] = {
    "tothestars_get_commissions": "commissions",
    "tothestars_get_schedule": "schedule",
    "tothestars_get_legend_progress": "legends",
    "tothestars_get_journal_summary": "journal",
}

# 提议工具名 -> 权限类目。提议本身不写数据，但只有 can_write 类目才需要/
# 才允许生成提议（防止用户明明只给了只读权限，模型还在张罗着改）。
WRITE_TOOL_CATEGORY: Dict[str, str] = {
    "tothestars_propose_create_commission": "commissions",
    "tothestars_propose_complete_commission": "commissions",
    "tothestars_propose_update_commission": "commissions",
    "tothestars_propose_add_schedule_plan": "schedule",
}

# 撤销工具跟随"所撤目标"的类目权限判定，至少要有任一可写类目才出现。
UNDO_TOOL = "tothestars_propose_undo_last_action"
UNDO_CATEGORIES = ("commissions", "schedule", "legends")

# 快照工具只要有任何一类可读数据就该可见，返回内容再按类目裁剪。
SNAPSHOT_TOOL = "tothestars_get_life_snapshot"
SNAPSHOT_CATEGORIES = ("commissions", "schedule", "legends", "wallet", "journal")

# 专注模式（番茄钟）提议工具：名字不带 tothestars_ 前缀，单独按 focus 类目门控。
# 只有「可写」档才允许她张罗着开番茄钟/记录专注。
FOCUS_PROPOSE_TOOL = "focus_propose_session"


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if raw is None:
        return default
    return bool(raw)


def _coerce_timeout(raw: Any, default: float = 2.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if 0.2 <= value <= 30.0 else default


def get_tothestars_config() -> Dict[str, Any]:
    """返回归一化后的联动配置（所有字段保证存在且类型正确）。"""
    endpoint_raw = get_config_val(f"{CONFIG_PATH}.endpoint", "http://127.0.0.1:8765")
    endpoint = endpoint_raw.strip().rstrip("/") if isinstance(endpoint_raw, str) and endpoint_raw.strip() else "http://127.0.0.1:8765"

    raw_permissions = get_config_val(f"{CONFIG_PATH}.permissions", {})
    permissions: Dict[str, str] = {}
    for category, default_tier in DEFAULT_PERMISSIONS.items():
        raw_tier = raw_permissions.get(category) if isinstance(raw_permissions, dict) else None
        if raw_tier is None:
            # 字段缺席 = 采用该类目的默认档
            permissions[category] = default_tier
        else:
            # 字段存在但内容非法（拼错/空串/类型不对）= fail-closed 到 hidden，
            # 绝不因为一个笔误就把敏感数据放行。
            tier = raw_tier.strip().lower() if isinstance(raw_tier, str) else ""
            permissions[category] = tier if tier in PERMISSION_TIERS else TIER_HIDDEN

    raw_mode = get_config_val(f"{CONFIG_PATH}.write_mode", "local")
    write_mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else "local"
    if write_mode not in ("local", "remote"):
        write_mode = "local"
    raw_root = get_config_val(f"{CONFIG_PATH}.local_project_root", "")
    local_project_root = raw_root.strip() if isinstance(raw_root, str) else ""

    return {
        "enabled": _coerce_bool(get_config_val(f"{CONFIG_PATH}.enabled", False)),
        "endpoint": endpoint,
        "timeout_seconds": _coerce_timeout(get_config_val(f"{CONFIG_PATH}.timeout_seconds"), 2.0),
        "permissions": permissions,
        "write_mode": write_mode,
        "local_project_root": local_project_root,
        "proactive": {
            "enabled": _coerce_bool(get_config_val(f"{CONFIG_PATH}.proactive.enabled", False)),
            "quiet_hours": get_config_val(f"{CONFIG_PATH}.proactive.quiet_hours", ["23:00", "07:00"]),
            "max_per_hour": get_config_val(f"{CONFIG_PATH}.proactive.max_per_hour", 2),
            "max_per_day": get_config_val(f"{CONFIG_PATH}.proactive.max_per_day", 6),
        },
    }


def is_tothestars_enabled() -> bool:
    """L0 总开关。关闭时所有 tothestars_* 工具与提示词注入一并停用。"""
    return bool(get_tothestars_config()["enabled"])


def get_tothestars_endpoint() -> str:
    return str(get_tothestars_config()["endpoint"])


def get_tothestars_timeout() -> float:
    return float(get_tothestars_config()["timeout_seconds"])


def get_permission(category: str) -> str:
    """取某类数据的权限档；未知类目/拼错一律按 hidden 处理。"""
    permissions = get_tothestars_config()["permissions"]
    if category not in permissions:
        return TIER_HIDDEN
    return permissions[category]


def can_read(category: str) -> bool:
    """能否读取该类数据（工具可见性的最低要求）。"""
    return get_permission(category) != TIER_HIDDEN


def can_write(category: str) -> bool:
    """能否修改该类数据（写入确认协议与写工具都以此为准）。"""
    return get_permission(category) == TIER_READ_WRITE_PROACTIVE


def can_be_proactive(category: str) -> bool:
    """能否主动提及该类数据（on_request 与 hidden 都不允许）。"""
    return get_permission(category) in (TIER_READ_WRITE_PROACTIVE, TIER_READ_ONLY)


def readable_categories() -> List[str]:
    return [c for c in DEFAULT_PERMISSIONS if can_read(c)]


def is_tool_visible(tool_name: str) -> bool:
    """该工具是否允许进入本轮 tools_schema。

    非 tothestars_* 的工具不归本模块管，一律返回 True（调用方可对所有工具统一调用）。
    tothestars_* 工具在总开关关闭或对应类目不可读时返回 False；未知的
    tothestars_* 名字按 fail-closed 处理，避免以后新增工具忘了配权限就默认可见。
    """
    if tool_name == FOCUS_PROPOSE_TOOL:
        return is_tothestars_enabled() and can_write("focus")
    if not tool_name.startswith("tothestars_"):
        return True
    if not is_tothestars_enabled():
        return False
    if tool_name == SNAPSHOT_TOOL:
        return any(can_read(c) for c in SNAPSHOT_CATEGORIES)
    if tool_name == UNDO_TOOL:
        return any(can_write(c) for c in UNDO_CATEGORIES)
    write_category = WRITE_TOOL_CATEGORY.get(tool_name)
    if write_category:
        return can_write(write_category)
    category = TOOL_CATEGORY.get(tool_name)
    return bool(category) and can_read(category)


def describe_permissions_state() -> str:
    """一行中文状态描述，用于启动日志与配置热更新日志。"""
    config = get_tothestars_config()
    if not config["enabled"]:
        return "向着星联动: 已关闭"
    parts = [f"{CATEGORY_LABELS.get(c, c)}={get_permission(c)}" for c in DEFAULT_PERMISSIONS]
    return f"向着星联动: 可用 (endpoint={config['endpoint']}; " + ", ".join(parts) + ")"


def log_permissions_state(prefix: str = "") -> None:
    message = describe_permissions_state()
    logger.info(f"{prefix}{message}" if prefix else message)
