"""专注模式（番茄钟）测试：控制哨兵解析、提议工具、确认启动、完成写入与提示注入。"""
import asyncio
import json
import time

import pytest

import services.cognitive.cognitive_engine as engine_module
from services.cognitive.cognitive_engine import (
    FOCUS_CONTROL_PREFIX,
    CognitiveEngine,
    parse_focus_control,
)
from services.cognitive.tools import tothestars_tool as tt
from services.cognitive.tools.focus_tool import ProposeFocusSessionTool, clamp_focus_minutes
from shared.schema.payloads import (
    FocusCommandPayload,
    InboundMessagePayload,
    LifeProposalPayload,
    ReasoningRequestPayload,
)


async def _collect(agen):
    return [event async for event in agen]


def _payload(text, trigger_type="user_message"):
    return ReasoningRequestPayload(
        chat_id=1001,
        user_id=1,
        trigger_type=trigger_type,
        inbound_message=InboundMessagePayload(
            chat_id=1001, user_id=1, message_id=1, raw_text=text,
        ),
    )


def _sentinel(**data):
    data.setdefault("v", 1)
    return FOCUS_CONTROL_PREFIX + json.dumps(data)


@pytest.mark.parametrize(("text", "action"), [
    (_sentinel(action="pause"), "pause"),
    (_sentinel(action="resume"), "resume"),
    (_sentinel(action="abandon"), "abandon"),
    (_sentinel(action="finish", category="工作", description="写完了报告"), "finish"),
    # 前端流水线的时间戳前缀照样能解析
    (f"[2026-09-12 18:22] {_sentinel(action='pause')}", "pause"),
])
def test_parse_focus_control(text, action):
    assert parse_focus_control(text)["action"] == action


def test_parse_focus_control_rejects_bad_input():
    assert parse_focus_control("普通消息") is None
    assert parse_focus_control(FOCUS_CONTROL_PREFIX + "not json") is None
    assert parse_focus_control(FOCUS_CONTROL_PREFIX + json.dumps({"v": 2, "action": "pause"})) is None
    assert parse_focus_control(FOCUS_CONTROL_PREFIX + json.dumps({"v": 1, "action": "dance"})) is None


def test_finish_sentinel_carries_content_fields():
    parsed = parse_focus_control(_sentinel(action="finish", category="编程", description="完成接口", planned_minutes=25))
    assert parsed["category"] == "编程"
    assert parsed["description"] == "完成接口"
    assert parsed["planned_minutes"] == 25


def test_propose_focus_session_tool():
    tool = ProposeFocusSessionTool()
    out = asyncio.run(tool.execute(minutes=90, reason="写报告"))
    assert out["status"] == "needs_confirmation"
    assert out["proposal"]["kind"] == "focus.start"
    assert out["proposal"]["params"]["minutes"] == 90
    assert "90 分钟" in out["proposal"]["summary"]

    clamped_high = asyncio.run(tool.execute(minutes=999))
    assert clamped_high["proposal"]["params"]["minutes"] == 240
    clamped_low = asyncio.run(tool.execute(minutes=0))
    assert clamped_low["proposal"]["params"]["minutes"] == clamp_focus_minutes(0)


def test_apply_life_proposal_edits_focus_minutes_are_ints():
    merged = tt.apply_life_proposal_edits("focus.start", {"minutes": 60}, {"minutes": "25"})
    assert merged["minutes"] == 25
    assert isinstance(merged["minutes"], int)
    # 白名单之外的手改字段一律忽略（前端被篡改也只能改分钟数）
    merged = tt.apply_life_proposal_edits("focus.start", {"minutes": 60}, {"chat_id": 999})
    assert "chat_id" not in merged


def _focus_engine_with_pending(minutes: int = 60):
    engine = CognitiveEngine()
    engine._pending_life_actions[1001] = {
        "proposal": {
            "id": "focus123",
            "kind": "focus.start",
            "params": {"minutes": minutes},
            "summary": f"开始一次 {minutes} 分钟专注",
        },
        "created_at": time.time(),
    }
    return engine


def test_confirm_focus_proposal_starts_timer():
    engine = _focus_engine_with_pending()
    payload = _payload("【确认框】" + json.dumps(
        {"v": 1, "id": "focus123", "action": "confirm", "edits": {"minutes": 25}},
    ))
    messages = []

    events = asyncio.run(_collect(engine._settle_pending_life_action(payload, messages)))

    commands = [e for e in events if isinstance(e, FocusCommandPayload)]
    assert len(commands) == 1
    assert commands[0].action == "start"
    assert commands[0].minutes == 25
    assert [e.phase for e in events if isinstance(e, LifeProposalPayload)] == ["executed"]
    assert any("番茄钟已启动" in m["content"] for m in messages)
    # 专注提议不写向着星：不应产生工具执行事件、也不应调用 execute_proposal
    assert not any(getattr(e, "tool", "") == "tothestars:focus.start" for e in events)


def test_cancel_focus_proposal_writes_nothing():
    engine = _focus_engine_with_pending()
    payload = _payload("【确认框】" + json.dumps({"v": 1, "id": "focus123", "action": "cancel"}))
    messages = []

    events = asyncio.run(_collect(engine._settle_pending_life_action(payload, messages)))

    assert not [e for e in events if isinstance(e, FocusCommandPayload)]
    assert [e.phase for e in events if isinstance(e, LifeProposalPayload)] == ["cancelled"]
    assert any("取消" in m["content"] for m in messages)


def _running_state(**overrides):
    state = {
        "chat_id": 1001,
        "phase": "running",
        "planned_minutes": 60,
        "remaining_seconds": 60 * 40,
        "started_at_unix": time.time() - 60 * 20,
    }
    state.update(overrides)
    return state


def test_focus_pause_and_resume_commands():
    engine = CognitiveEngine()
    engine.update_focus_state(_running_state())

    messages = []
    events = asyncio.run(_collect(engine._handle_focus_control(_payload(_sentinel(action="pause")), messages)))
    assert [e.action for e in events if isinstance(e, FocusCommandPayload)] == ["pause"]
    assert any("暂停" in m["content"] for m in messages)

    messages = []
    events = asyncio.run(_collect(engine._handle_focus_control(_payload(_sentinel(action="resume")), messages)))
    assert [e.action for e in events if isinstance(e, FocusCommandPayload)] == ["resume"]
    assert any("结束暂停" in m["content"] for m in messages)


def test_focus_abandon_clears_state_and_blames():
    engine = CognitiveEngine()
    engine.update_focus_state(_running_state())

    messages = []
    events = asyncio.run(_collect(engine._handle_focus_control(_payload(_sentinel(action="abandon")), messages)))

    commands = [e for e in events if isinstance(e, FocusCommandPayload)]
    assert len(commands) == 1
    assert commands[0].action == "end"
    assert commands[0].outcome == "abandoned"
    assert engine._focus_state_for(1001) is None
    assert any("失望" in m["content"] for m in messages)


def test_focus_finish_writes_to_tothestars(monkeypatch):
    engine = CognitiveEngine()
    started = time.time() - 3600
    engine.update_focus_state(_running_state(planned_minutes=60, remaining_seconds=0, started_at_unix=started))

    recorded = {}

    async def fake_record_focus_session(**kwargs):
        recorded.update(kwargs)
        return {"status": "success", "message": "已记录 60 分钟专注（工作）", "today_minutes": 120.0}

    monkeypatch.setattr(engine_module, "record_focus_session", fake_record_focus_session)

    messages = []
    sentinel = _sentinel(action="finish", category="工作", description="写完了报告第三章")
    events = asyncio.run(_collect(engine._handle_focus_control(_payload(sentinel), messages)))

    assert recorded["planned_minutes"] == 60
    assert recorded["duration_seconds"] == 3600
    assert recorded["category"] == "工作"
    assert recorded["description"] == "写完了报告第三章"
    commands = [e for e in events if isinstance(e, FocusCommandPayload)]
    assert len(commands) == 1 and commands[0].action == "end" and commands[0].outcome == "completed"
    assert engine._focus_state_for(1001) is None
    assert any("写完了报告第三章" in m["content"] for m in messages)
    assert any("鼓励" in m["content"] for m in messages)


def test_focus_finish_write_failure_reported_honestly(monkeypatch):
    engine = CognitiveEngine()
    engine.update_focus_state(_running_state())

    async def fake_record_focus_session(**kwargs):
        return {"status": "failed", "error": "向着星没启动"}

    monkeypatch.setattr(engine_module, "record_focus_session", fake_record_focus_session)

    messages = []
    events = asyncio.run(_collect(engine._handle_focus_control(
        _payload(_sentinel(action="finish", category="学习", description="")), messages,
    )))

    commands = [e for e in events if isinstance(e, FocusCommandPayload)]
    assert len(commands) == 1 and commands[0].action == "end"
    assert any("没能记上" in m["content"] or "向着星没启动" in m["content"] for m in messages)


def test_focus_finish_without_cached_state_is_honest(monkeypatch):
    engine = CognitiveEngine()
    # 没有任何状态缓存（例如认知服务刚重启、心跳还没到）
    called = False

    async def fake_record_focus_session(**kwargs):
        nonlocal called
        called = True
        return {"status": "success"}

    monkeypatch.setattr(engine_module, "record_focus_session", fake_record_focus_session)

    messages = []
    events = asyncio.run(_collect(engine._handle_focus_control(
        _payload(_sentinel(action="finish", category="工作", description="x")), messages,
    )))

    assert called is False
    assert [e.action for e in events if isinstance(e, FocusCommandPayload)] == ["end"]
    assert any("丢失" in m["content"] for m in messages)


def test_focus_mode_hint_only_while_active():
    engine = CognitiveEngine()
    assert engine._focus_mode_hint(1001) is None

    engine.update_focus_state(_running_state(remaining_seconds=60 * 42))
    hint = engine._focus_mode_hint(1001)
    assert hint and "专注模式" in hint and "42" in hint

    engine.update_focus_state(_running_state(phase="paused"))
    assert "暂停中" in engine._focus_mode_hint(1001)

    engine.update_focus_state({"chat_id": 1001, "phase": "completed"})
    assert engine._focus_mode_hint(1001) is None

    engine.update_focus_state({"chat_id": 1001, "phase": "idle"})
    assert engine._focus_state_for(1001) is None
