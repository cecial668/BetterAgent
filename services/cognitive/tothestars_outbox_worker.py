"""待提交队列的补交任务（远程连接模式专用）。

由 services/cognitive/main.py 起一个后台循环调用：每 10 秒扫一次到期的暂存
写入，用强制 HTTP 客户端重放；成功 → 发一条 agent.notice（前端 toast，数字人
不播报）；失败 → 退避并等待下一次。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from shared.schema.payloads import NoticePayload
from shared.subjects import SUBJECT_NOTICE
from shared.tothestars_outbox import due_items, mark_failure, mark_success

logger = logging.getLogger("tothestars_outbox_worker")


async def _publish_notice(nc: Any, level: str, message: str, title: str = "向着星") -> None:
    envelope = {
        "id": "tothestars-outbox-notice",
        "subject": SUBJECT_NOTICE,
        "source": "cognitive_service",
        "payload": NoticePayload(level=level, title=title, message=message).model_dump(),
    }
    try:
        await nc.publish(SUBJECT_NOTICE, json.dumps(envelope, ensure_ascii=False).encode())
    except Exception as exc:
        logger.warning(f"发布补交通知失败: {exc}")


async def flush_tothestars_outbox(nc: Any) -> int:
    """重放所有到期的暂存写入，返回本次补交成功的条数。"""
    items = due_items()
    if not items:
        return 0

    # 局部导入，避免与 tothestars_tool 形成循环依赖。
    from services.cognitive.tools.tothestars_tool import TothestarsClient

    client = TothestarsClient()
    delivered = 0
    for item in items:
        result = await client.request_json_http(
            item.get("method") or "POST",
            item.get("path") or "",
            item.get("params") or {},
            item.get("json_body") or {},
        )
        label = str(item.get("label") or "向着星写入")
        if result.get("ok"):
            mark_success(str(item.get("id") or ""))
            delivered += 1
            logger.info(f"📤 [待提交] {label} 补交成功（第 {int(item.get('attempts') or 0) + 1} 次尝试）")
            await _publish_notice(nc, "info", f"之前暂存的{label}已经补交成功。")
        else:
            remaining = mark_failure(str(item.get("id") or ""))
            if remaining is None:
                logger.warning(f"📤 [待提交] {label} 重试次数用尽，已放弃")
                await _publish_notice(
                    nc, "warn",
                    f"有一条{label}反复补交仍没成功，已经放弃。请检查向着星是否正常。",
                )
            else:
                logger.info(
                    f"📤 [待提交] {label} 补交失败（第 {remaining.get('attempts')} 次），"
                    f"将在 {max(0, int(float(remaining.get('next_at') or 0) - time.time()))}s 后重试"
                )
    return delivered
