"""联网搜索开关（L0 全局层）的解析接口。

这是「开关」与「将来真正发起搜索的代码」之间唯一的读取入口。任何以后要判断
"现在能不能联网"的地方都应该调用这里，而不是各自去 get_config_val，否则各服务
的口径会不一致（这正是 docs/WEB-SEARCH-PLAN.md 里提醒过的坑）。

三条设计约定：
1. 默认关闭。config.yaml 里没有这段、或字段缺失时，一律按关闭处理。
2. 「已开启」和「可用」是两件事。开关打开但没填 API Key 时不算可用，应当按
   关闭处理 —— 否则模型会看到一个必然失败的工具，然后反复重试。
3. 读取走 shared.config_loader，它带进程级缓存。后台改完配置后由
   agent.config.reloaded 的消费端调用 invalidate_cache() 刷新，所以这里不需要
   自己做缓存。
"""

import os
import re
import logging
from typing import Any, Dict

from shared.config_loader import get_config_val

logger = logging.getLogger("web_search_config")

CONFIG_PATH = "tools.web_search"

# provider -> 默认环境变量名。目前只规划了 tavily 一家。
PROVIDER_DEFAULT_ENV = {
    "tavily": "TAVILY_API_KEY",
}

DEFAULT_PROVIDER = "tavily"

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _resolve_api_key_env(raw: Any, provider: str) -> str:
    """把配置里的 api_key_env 收敛成一个安全的合法环境变量名。

    config.yaml 是可信文件，但这里仍然做一次形状校验：拼错的、带小写或特殊
    字符的名字一律退回该 provider 的默认值，避免拿着一个坏名字去 os.getenv
    而永远读不到 Key。provider 由调用方传入，避免与 get_web_search_config
    互相递归。
    """
    if isinstance(raw, str) and _ENV_NAME_RE.match(raw.strip()):
        return raw.strip()
    return PROVIDER_DEFAULT_ENV.get(provider, "TAVILY_API_KEY")


def _coerce_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def get_web_search_config() -> Dict[str, Any]:
    """返回归一化后的联网搜索配置（所有字段都保证存在且类型正确）。"""
    provider_raw = get_config_val(f"{CONFIG_PATH}.provider", DEFAULT_PROVIDER)
    provider = provider_raw.strip().lower() if isinstance(provider_raw, str) and provider_raw.strip() else DEFAULT_PROVIDER

    enabled_raw = get_config_val(f"{CONFIG_PATH}.enabled", False)
    # YAML 里写成 "false" 字符串时也应视为关闭，这里统一按布尔语义解释。
    if isinstance(enabled_raw, str):
        enabled = enabled_raw.strip().lower() in ("1", "true", "yes", "on")
    else:
        enabled = bool(enabled_raw)

    return {
        "enabled": enabled,
        "provider": provider,
        "api_key_env": _resolve_api_key_env(
            get_config_val(f"{CONFIG_PATH}.api_key_env"), provider,
        ),
        "top_k": _coerce_int(get_config_val(f"{CONFIG_PATH}.top_k"), 5),
        "timeout_seconds": _coerce_int(get_config_val(f"{CONFIG_PATH}.timeout_seconds"), 15),
        "max_calls_per_turn": _coerce_int(get_config_val(f"{CONFIG_PATH}.max_calls_per_turn"), 1),
    }


def is_web_search_enabled() -> bool:
    """L0 总开关本身的状态，不关心有没有配 Key。"""
    return bool(get_web_search_config()["enabled"])


def get_web_search_api_key() -> str:
    """按配置的 api_key_env 读取搜索服务的 Key；没有则返回空串。"""
    env_name = get_web_search_config()["api_key_env"]
    value = os.getenv(env_name, "").strip()
    # 与 admin 侧 _mask_key 的口径一致：.env.example 里的占位值不算已配置。
    if not value or value.startswith("your_"):
        return ""
    return value


def is_web_search_available() -> bool:
    """是否真正可用：开关打开 **且** 拿得到 Key。

    将来注册 web_search 工具、以及往 system prompt 里注入"你可以上网查"这段
    说明时，都应该用这个函数而不是 is_web_search_enabled()，否则会出现
    "模型以为能查、实际查不了"的情况。
    """
    return is_web_search_enabled() and bool(get_web_search_api_key())


def describe_web_search_state() -> str:
    """一行中文状态描述，用于启动日志与配置热更新日志。"""
    config = get_web_search_config()
    if not config["enabled"]:
        return f"联网搜索: 已关闭 (provider={config['provider']})"
    if not get_web_search_api_key():
        return (
            f"联网搜索: 开关已打开但缺少 {config['api_key_env']}，按不可用处理 "
            f"(provider={config['provider']})"
        )
    return (
        f"联网搜索: 可用 (provider={config['provider']}, "
        f"top_k={config['top_k']}, max_calls_per_turn={config['max_calls_per_turn']})"
    )


def log_web_search_state(prefix: str = "") -> None:
    """把当前状态打一条 INFO 日志，方便确认开关是否真的传到了本服务。"""
    message = describe_web_search_state()
    logger.info(f"{prefix}{message}" if prefix else message)
