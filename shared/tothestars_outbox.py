"""远程模式下写失败后的暂存队列（持久化 JSON + 指数退避重试）。

只有「远程连接」模式会用到：HTTP 连不上/5xx 时把这次写操作原样存下来，
后台任务按 15s → 30s → 60s → 120s → 300s（封顶）的节奏重试；成功后发一条
轻量通知（agent.notice → 前端右下角 toast），不经过 LLM、不发语音。

本地直连模式不经过本模块（数据库在磁盘上，不需要"等向着星上线"）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tothestars_outbox")

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTBOX_PATH = ROOT_DIR / "data" / "tothestars_outbox.json"

# 重试节奏（秒）：第一次 15s，之后逐档放大，封顶 5 分钟；最长重试 60 次
# （≈ 5 小时），仍不成功则放弃并提示用户「有改动始终没提交成功」。
BACKOFF_SECONDS = (15, 30, 60, 120, 300)
MAX_ATTEMPTS = 60

_LOCK = threading.Lock()


def label_for_path(path: str) -> str:
    """给通知用的业务人类标签。"""
    clean = (path or "").split("?")[0]
    if clean.startswith("/api/quests"):
        return "委托修改"
    if clean.startswith("/api/schedule"):
        return "日程修改"
    if clean.startswith("/api/focus"):
        return "专注记录"
    if clean.startswith("/api/agent/audit"):
        return "撤销操作"
    return "向着星写入"


def _load() -> List[Dict[str, Any]]:
    try:
        data = json.loads(OUTBOX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning(f"待提交队列读取失败（按空处理）: {exc}")
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTBOX_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUTBOX_PATH)


def enqueue(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """暂存一条写操作，返回队列项（含 id/label）。"""
    now = time.time()
    item = {
        "id": uuid.uuid4().hex[:12],
        "method": (method or "POST").upper(),
        "path": path,
        "params": params or {},
        "json_body": json_body or {},
        "label": label_for_path(path),
        "created_at": now,
        "attempts": 0,
        "next_at": now + BACKOFF_SECONDS[0],
    }
    with _LOCK:
        items = _load()
        items.append(item)
        _save(items)
    logger.info(f"📥 [待提交] 已暂存 {item['label']}（{item['method']} {path}），将在 {BACKOFF_SECONDS[0]}s 后重试")
    return item


def due_items(now: Optional[float] = None) -> List[Dict[str, Any]]:
    now = time.time() if now is None else now
    with _LOCK:
        return [item for item in _load() if float(item.get("next_at") or 0) <= now]


def mark_success(item_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        items = _load()
        found = next((item for item in items if item.get("id") == item_id), None)
        if found is None:
            return None
        _save([item for item in items if item.get("id") != item_id])
        return found


def mark_failure(item_id: str) -> Optional[Dict[str, Any]]:
    """记录一次失败；返回更新后的队列项；超过上限被放弃时返回 None。"""
    with _LOCK:
        items = _load()
        found = next((item for item in items if item.get("id") == item_id), None)
        if found is None:
            return None
        attempts = int(found.get("attempts") or 0) + 1
        if attempts >= MAX_ATTEMPTS:
            _save([item for item in items if item.get("id") != item_id])
            return None
        found["attempts"] = attempts
        found["next_at"] = time.time() + BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS) - 1)]
        _save(items)
        return found


def pending_count() -> int:
    with _LOCK:
        return len(_load())
