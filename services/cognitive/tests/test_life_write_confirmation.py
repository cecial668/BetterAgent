"""写入确认协议测试：确认词判定、哨兵解析、提议登记、确认后确定性执行。

执行路径不经过模型：模型只能产出提议，引擎在用户（在确认框或对话里）确认后
调用 execute_proposal 真正写入（本测试用假执行器替换，验证协议本身）。
"""
import asyncio
import json
import time

import pytest

import services.cognitive.cognitive_engine as engine_module
from services.cognitive.cognitive_engine import (
    LIFE_DECISION_PREFIX,
    LIFE_PROPOSAL_TTL_SECONDS,
    CognitiveEngine,
    detect_life_action_confirmation,
    parse_life_decision,
)
from shared.schema.payloads import InboundMessagePayload, LifeProposalPayload, ReasoningRequestPayload, ToolActivityPayload


@pytest.mark.parametrize(("text", "expected"), [
    ("好", True),
    ("好的", True),
    ("好呀！", True),
    ("嗯嗯", True),
    ("可以", True),
    ("行吧", True),
    ("没问题", True),
    ("确认一下", True),
    ("就这样吧", True),
    ("OK", True),
    # 前端流水线会加时间戳前缀（线上"反复说好没反应"的根因，回归防线）
    ("[2026-09-12 18:22] 好", True),
    ("[2026-09-12 18:22] 好的", True),
    ("[2026-09-12 18:22] 取消", False),
    ("取消", False),
    ("算了", False),
    ("不用了", False),
    ("先不要", False),
    ("别了吧", False),
    ("不写", False),
    # 不是明确回应：一律 None（提议按安全默认作废）
    ("好烦啊", None),
    ("好吧不用了", None),       # 混合消息不猜语义，安全作废
    ("明天再加吧，今天算了", None),
    ("我考虑一下", None),
    ("把难度改成 A", None),
    ("", None),
])
def test_detect_life_action_confirmation(text, expected):
    assert detect_life_action_confirmation(text) is expected


def test_parse_life_decision_sentinel():
    sentinel = LIFE_DECISION_PREFIX + json.dumps(
        {"v": 1, "id": "abc123", "action": "confirm", "edits": {"title": "取快递"}},
    )
    assert parse_life_decision(sentinel) == {
        "id": "abc123", "action": "confirm", "edits": {"title": "取快递"},
    }
    # 时间戳前缀照样能解析
    assert parse_life_decision(f"[2026-09-12 18:22] {sentinel}")["action"] == "confirm"
    # 坏输入绝不猜测
    assert parse_life_decision(LIFE_DECISION_PREFIX + "not json") is None
    assert parse_life_decision(LIFE_DECISION_PREFIX + json.dumps({"v": 2, "id": "x", "action": "confirm"})) is None
    assert parse_life_decision(LIFE_DECISION_PREFIX + json.dumps({"v": 1, "id": "", "action": "confirm"})) is None
    assert parse_life_decision("普通消息") is None


def _payload(text, trigger_type="user_message"):
    return ReasoningRequestPayload(
        chat_id=1001,
        user_id=1,
        trigger_type=trigger_type,
        inbound_message=InboundMessagePayload(
            chat_id=1001, user_id=1, message_id=1, raw_text=text,
        ),
    )


_PROPOSAL = {
    "id": "abc123def456",
    "kind": "commission.create",
    "params": {"title": "取快递", "difficulty": "B"},
    "summary": "新增委托「取快递」（难度 B，支线委托）",
}


def _engine_with_pending(age_seconds=0.0):
    engine = CognitiveEngine()
    engine._pending_life_actions[1001] = [{
        "proposal": dict(_PROPOSAL),
        "created_at": time.time() - age_seconds,
    }]
    return engine


async def _settle(engine, payload, messages):
    events = []
    async for event in engine._settle_pending_life_action(payload, messages):
        events.append(event)
    return events


def _proposal_phases(events):
    return [e.phase for e in events if isinstance(e, LifeProposalPayload)]


def _tool_phases(events):
    return [e.phase for e in events if isinstance(e, ToolActivityPayload)]


def test_capture_returns_confirmation_box_event(monkeypatch):
    engine = CognitiveEngine()
    payload = _payload("帮我把取快递加到明天")
    captured = engine._capture_life_proposal(payload, {
        "status": "needs_confirmation", "proposal": {"kind": "commission.create", "params": {}, "summary": "x"},
    })
    model_output, event = captured
    assert model_output["status"] == "awaiting_user_confirmation"
    assert "确认框" in model_output["instruction"]
    # 提议带上了唯一 id，且事件发给了前端（pending）
    pending = engine._pending_life_actions[1001][0]["proposal"]
    assert pending["id"]
    assert isinstance(event, LifeProposalPayload)
    assert event.phase == "pending" and event.proposal_id == pending["id"]
    # 普通工具输出不会被当成提议
    assert engine._capture_life_proposal(payload, {"status": "success"}) is None


def test_confirm_executes_deterministically_and_reports(monkeypatch):
    engine = _engine_with_pending()
    executed = []

    async def fake_execute(kind, params):
        executed.append((kind, params))
        return {"status": "success", "message": "已新增委托「取快递」（编号 #7）"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    messages = [{"role": "user", "content": "好的"}]
    events = asyncio.run(_settle(engine, _payload("好的"), messages))

    assert executed == [("commission.create", _PROPOSAL["params"])]
    assert engine._pending_life_actions == {}
    assert _tool_phases(events) == ["start", "done"]
    assert _proposal_phases(events) == ["executing", "executed"]
    assert any("写入已经真实执行成功" in m["content"] for m in messages)


def test_timestamp_prefixed_confirmation_still_executes(monkeypatch):
    engine = _engine_with_pending()
    executed = []

    async def fake_execute(kind, params):
        executed.append(kind)
        return {"status": "success", "message": "ok"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    messages = []
    asyncio.run(_settle(engine, _payload("[2026-09-12 18:22] 好"), messages))
    assert executed == ["commission.create"]


def test_sentinel_confirm_merges_edits(monkeypatch):
    engine = _engine_with_pending()
    executed = []

    async def fake_execute(kind, params):
        executed.append((kind, params))
        return {"status": "success", "message": "ok"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    sentinel = LIFE_DECISION_PREFIX + json.dumps({
        "v": 1, "id": _PROPOSAL["id"], "action": "confirm",
        "edits": {"title": "回宿舍", "difficulty": "a", "is_required": True, "不存在的字段": "x"},
    })
    messages = []
    events = asyncio.run(_settle(engine, _payload(sentinel), messages))

    assert len(executed) == 1
    _, params = executed[0]
    assert params["title"] == "回宿舍"
    assert params["difficulty"] == "A"        # 归一化
    assert params["is_required"] is True
    assert "不存在的字段" not in params        # 白名单外忽略
    assert _proposal_phases(events) == ["executing", "executed"]


def test_sentinel_stale_id_keeps_current_proposal(monkeypatch):
    engine = _engine_with_pending()
    executed = []

    async def fake_execute(kind, params):
        executed.append(kind)
        return {"status": "success", "message": "不该发生"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    sentinel = LIFE_DECISION_PREFIX + json.dumps({"v": 1, "id": "stale999", "action": "confirm"})
    messages = []
    events = asyncio.run(_settle(engine, _payload(sentinel), messages))

    assert executed == []
    assert engine._pending_life_actions[1001][0]["proposal"]["id"] == _PROPOSAL["id"]
    assert _proposal_phases(events) == ["expired"]


def test_cancel_never_executes(monkeypatch):
    engine = _engine_with_pending()
    executed = []

    async def fake_execute(kind, params):
        executed.append(kind)
        return {"status": "success", "message": "不该发生"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    messages = [{"role": "user", "content": "取消"}]
    events = asyncio.run(_settle(engine, _payload("取消"), messages))

    assert executed == []
    assert engine._pending_life_actions == {}
    assert any("取消了写入提议" in m["content"] for m in messages)
    assert _proposal_phases(events) == ["cancelled"]


def test_ambiguous_reply_drops_proposal_without_execution(monkeypatch):
    engine = _engine_with_pending()
    executed = []

    async def fake_execute(kind, params):
        executed.append(kind)
        return {"status": "success", "message": "不该发生"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    messages = []
    events = asyncio.run(_settle(engine, _payload("我考虑一下"), messages))

    assert executed == []
    assert engine._pending_life_actions == {}
    assert messages == []  # 不注入任何系统事件，正常对话继续
    assert _proposal_phases(events) == ["expired"]  # 前端确认框会收到"失效"并收起


def test_expired_proposal_is_discarded(monkeypatch):
    engine = _engine_with_pending(age_seconds=LIFE_PROPOSAL_TTL_SECONDS + 1)
    executed = []

    async def fake_execute(kind, params):
        executed.append(kind)
        return {"status": "success", "message": "不应发生"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    messages = []
    events = asyncio.run(_settle(engine, _payload("好的"), messages))

    assert executed == []
    assert any("超时自动作废" in m["content"] for m in messages)
    assert _proposal_phases(events) == ["expired"]


def test_failed_execution_is_reported_honestly(monkeypatch):
    engine = _engine_with_pending()

    async def fake_execute(kind, params):
        return {"status": "failed", "error": "暂时连不上向着星"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)

    messages = []
    events = asyncio.run(_settle(engine, _payload("好"), messages))
    assert any("写入执行失败" in m["content"] for m in messages)
    assert _proposal_phases(events) == ["executing", "failed"]


def test_proactive_turn_keeps_pending_untouched():
    engine = _engine_with_pending()
    pending_before = engine._pending_life_actions[1001][0]["proposal"]

    messages = []
    events = asyncio.run(_settle(engine, _payload("", trigger_type="proactive"), messages))

    assert events == [] and messages == []
    assert engine._pending_life_actions[1001][0]["proposal"] == pending_before


# ---------- 多条待确认（排队确认） ----------

def _engine_with_two_pending():
    engine = CognitiveEngine()
    first = dict(_PROPOSAL, id="aaa111")
    second = dict(_PROPOSAL, id="bbb222", kind="schedule.add", summary="新增日程「英语角」")
    engine._pending_life_actions[1001] = [
        {"proposal": first, "created_at": time.time()},
        {"proposal": second, "created_at": time.time()},
    ]
    return engine


def _fake_executor(monkeypatch):
    executed = []

    async def fake_execute(kind, params):
        executed.append(kind)
        return {"status": "success", "message": "已执行"}

    monkeypatch.setattr(engine_module, "execute_proposal", fake_execute)
    return executed


def test_capture_appends_to_queue_instead_of_overwriting():
    engine = CognitiveEngine()
    payload = _payload("排两条日程")
    engine._capture_life_proposal(payload, {
        "status": "needs_confirmation",
        "proposal": {"kind": "schedule.add", "params": {"title": "健身"}, "summary": "健身"},
    })
    engine._capture_life_proposal(payload, {
        "status": "needs_confirmation",
        "proposal": {"kind": "schedule.add", "params": {"title": "英语角"}, "summary": "英语角"},
    })
    queue = engine._pending_life_actions[1001]
    assert [entry["proposal"]["params"]["title"] for entry in queue] == ["健身", "英语角"]
    assert len({entry["proposal"]["id"] for entry in queue}) == 2


def test_multi_pending_confirm_by_sentinel_id_only_targets_that_one(monkeypatch):
    engine = _engine_with_two_pending()
    executed = _fake_executor(monkeypatch)

    sentinel = LIFE_DECISION_PREFIX + json.dumps({"v": 1, "id": "bbb222", "action": "confirm"})
    messages = []
    events = asyncio.run(_settle(engine, _payload(sentinel), messages))

    assert executed == ["schedule.add"]
    # 第一条仍在队列里等确认，不会因为确认了第二条而丢失/执行
    remaining = engine._pending_life_actions[1001]
    assert len(remaining) == 1 and remaining[0]["proposal"]["id"] == "aaa111"
    assert _proposal_phases(events) == ["executing", "executed"]


def test_multi_pending_text_confirm_targets_oldest(monkeypatch):
    engine = _engine_with_two_pending()
    executed = _fake_executor(monkeypatch)

    messages = []
    events = asyncio.run(_settle(engine, _payload("好的"), messages))

    assert executed == ["commission.create"]
    remaining = engine._pending_life_actions[1001]
    assert len(remaining) == 1 and remaining[0]["proposal"]["id"] == "bbb222"


def test_multi_pending_ambiguous_reply_expires_all(monkeypatch):
    engine = _engine_with_two_pending()
    executed = _fake_executor(monkeypatch)

    messages = []
    events = asyncio.run(_settle(engine, _payload("我考虑一下"), messages))

    assert executed == []
    assert engine._pending_life_actions == {}
    assert _proposal_phases(events) == ["expired", "expired"]


def test_multi_pending_stale_sentinel_leaves_queue_untouched(monkeypatch):
    engine = _engine_with_two_pending()
    executed = _fake_executor(monkeypatch)

    sentinel = LIFE_DECISION_PREFIX + json.dumps({"v": 1, "id": "stale999", "action": "confirm"})
    messages = []
    events = asyncio.run(_settle(engine, _payload(sentinel), messages))

    assert executed == []
    assert len(engine._pending_life_actions[1001]) == 2
    assert _proposal_phases(events) == ["expired"]
