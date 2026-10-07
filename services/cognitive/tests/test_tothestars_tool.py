"""向着星只读工具族测试：权限裁剪、正文闸门、离线容错、提示词渲染。

隔离策略：替换 shared.config_loader 缓存 + 注入假的 TothestarsClient，
不发起任何真实 HTTP 请求（离线用例除外，它指向必然拒绝的端口）。
"""
import asyncio

import shared.config_loader as config_loader
from services.cognitive.tools import tothestars_tool as tt


def _set_config(monkeypatch, permissions=None, enabled=True):
    section = {"enabled": enabled, "endpoint": "http://127.0.0.1:8765", "timeout_seconds": 0.3}
    if permissions is not None:
        section["permissions"] = permissions
    monkeypatch.setattr(
        config_loader, "_cached_config",
        {"integration": {"tothestars": section}},
        raising=False,
    )


_SNAPSHOT = {
    "date": "2026-09-12",
    "is_vacation": False,
    "wallet": {"practice_points": 12, "growth_points": 4},
    "condition": {"total_points": 1},
    "commissions": [
        {"id": 1, "title": "写周报", "is_required": True, "is_completed": False, "points": 2},
        {"id": 2, "title": "背单词", "is_required": False, "is_completed": True, "points": 1},
    ],
    "schedule": {
        "date": "2026-09-12",
        "plans": [{"id": 5, "title": "组会", "start": "09:00", "end": "10:00", "completed": False}],
    },
    "legends": [
        {"id": 3, "title": "期末复习", "deadline": "2026-09-20", "remaining_days": 8,
         "progress": {"done": 3, "total": 5}},
    ],
    "journal": {
        "date": "2026-09-12",
        "journal_title": "安静的一天",
        "rating": 4,
        "energy": 1,
        "emotions": ["平静"],
        "has_text": True,
        "review_text": "今天把重要的事推进了一步。",
        "images": ["a.jpg"],
        "image_urls": ["/journal-images/a.jpg"],
    },
}


class _FakeClient:
    def __init__(self, snapshot=None, journal=None, audit=None):
        self._snapshot = snapshot
        self._journal = journal
        self._audit = audit
        self.calls = 0

    async def get_snapshot(self, include_journal_text=False):
        self.calls += 1
        return {"ok": True, "data": self._snapshot}

    async def get_commissions(self, date=None):
        self.calls += 1
        return {"ok": True, "data": (self._snapshot or {}).get("commissions") or []}

    async def get_audit(self, limit=50):
        self.calls += 1
        return {"ok": True, "data": self._audit or []}

    async def get_today_journal(self):
        self.calls += 1
        return {"ok": True, "data": self._journal if self._journal is not None else self._snapshot["journal"]}

    async def get_journal(self, date=None, include_text=False):
        self.calls += 1
        data = self._journal if self._journal is not None else self._snapshot["journal"]
        if data is None:
            return {"ok": False, "error": f"{date} 没有日记记录"}
        return {"ok": True, "data": data}


def test_snapshot_tool_filters_hidden_categories(monkeypatch):
    _set_config(monkeypatch, {"journal": "hidden", "wallet": "hidden"})
    client = _FakeClient(snapshot=_SNAPSHOT)
    result = asyncio.run(tt.ToTheStarsLifeSnapshotTool(client).execute())
    assert result["status"] == "success"
    data = result["data"]
    assert "journal" not in data
    assert "wallet" not in data
    assert data["commissions"] and data["schedule"] and data["legends"]


def test_snapshot_tool_strips_journal_text_by_default(monkeypatch):
    _set_config(monkeypatch)  # 默认：日记 on_request、正文 hidden
    result = asyncio.run(tt.ToTheStarsLifeSnapshotTool(_FakeClient(snapshot=_SNAPSHOT)).execute())
    journal = result["data"]["journal"]
    assert journal["rating"] == 4
    assert "review_text" not in journal
    assert "images" not in journal
    assert journal["text_available"] is True


def test_journal_tool_denied_when_category_hidden(monkeypatch):
    _set_config(monkeypatch, {"journal": "hidden"})
    result = asyncio.run(tt.ToTheStarsJournalSummaryTool(_FakeClient(snapshot=_SNAPSHOT)).execute())
    assert result["status"] == "denied"


def test_journal_tool_gates_text_on_journal_text_permission(monkeypatch):
    _set_config(monkeypatch, {"journal": "on_request", "journal_text": "hidden"})
    tool = tt.ToTheStarsJournalSummaryTool(_FakeClient(snapshot=_SNAPSHOT))
    assert "review_text" not in asyncio.run(tool.execute(include_text=True))["data"]

    _set_config(monkeypatch, {"journal": "on_request", "journal_text": "on_request"})
    tool = tt.ToTheStarsJournalSummaryTool(_FakeClient(snapshot=_SNAPSHOT))
    assert asyncio.run(tool.execute(include_text=True))["data"]["review_text"]
    assert "review_text" not in asyncio.run(tool.execute(include_text=False))["data"]


def test_unreachable_service_returns_friendly_failure(monkeypatch):
    _set_config(monkeypatch)
    client = tt.TothestarsClient(endpoint="http://127.0.0.1:9", timeout=0.3)
    result = asyncio.run(tt.ToTheStarsCommissionsTool(client).execute())
    assert result["status"] == "failed"
    assert "不要编造" in result["message"]


def test_render_snapshot_for_prompt_respects_proactive_tiers(monkeypatch):
    _set_config(monkeypatch)  # journal 默认 on_request -> 不主动注入
    block = tt.render_snapshot_for_prompt(_SNAPSHOT)
    assert "委托：" in block and "写周报" in block
    assert "日程：" in block
    assert "传说任务：" in block
    assert "点数：" in block
    assert "今日心情" not in block
    assert "安静的一天" not in block

    _set_config(monkeypatch, {"journal": "read_only"})
    block = tt.render_snapshot_for_prompt(_SNAPSHOT)
    assert "今日心情：" in block
    assert "安静的一天" not in block  # 标题属于正文类信息，绝不进提示词


def test_tothestars_disabled_returns_offline(monkeypatch):
    _set_config(monkeypatch, enabled=False)
    result = asyncio.run(tt.ToTheStarsCommissionsTool(_FakeClient(snapshot=_SNAPSHOT)).execute())
    assert result["status"] == "failed"


def _build_prompt(monkeypatch, trigger_type):
    import services.cognitive.prompt_builder as pb
    from shared.schema.payloads import ReasoningRequestPayload

    monkeypatch.setattr(pb, "is_tothestars_enabled", lambda: True)
    monkeypatch.setattr(pb, "can_read", lambda category: True)
    monkeypatch.setattr(pb, "fetch_life_snapshot_block", lambda: "[向着星·今日生活快照 2026-09-12]\n- 委托：今日 2 条，已完成 1")
    monkeypatch.setattr(pb, "log_raw_trace", lambda *a, **k: None)
    payload = ReasoningRequestPayload(chat_id=1001, user_id=1, trigger_type=trigger_type)
    return pb.PromptBuilder.build_system_prompt(payload)


def test_prompt_builder_injects_snapshot_and_boundary(monkeypatch):
    prompt = _build_prompt(monkeypatch, "user_message")
    assert "今日生活快照" in prompt
    assert "生活数据使用边界" in prompt


def test_prompt_builder_skips_snapshot_for_game_turn(monkeypatch):
    prompt = _build_prompt(monkeypatch, "game_turn")
    assert "今日生活快照" not in prompt
    assert "生活数据使用边界" not in prompt


# ---------------------------------------------------------------------------
# 写入确认协议：提议工具只生成提案，执行器才是唯一写入口
# ---------------------------------------------------------------------------

_AUDIT = [
    {"id": 9, "actor": "companion", "action": "legend.indicator.complete",
     "target_type": "legend_indicator", "target_id": 3, "undoable": True, "undone": False},
    {"id": 8, "actor": "companion", "action": "quest.create",
     "target_type": "daily_quest", "target_id": 1, "undoable": True, "undone": False},
]


class _RecordingClient:
    """记录写请求的假客户端；execute_proposal 必须通过它来写。"""

    def __init__(self):
        self.calls = []

    async def request_json(self, method, path, params=None, json_body=None):
        self.calls.append((method, path, json_body))
        return {"ok": True, "data": {"id": 7}}


def test_create_proposal_never_writes(monkeypatch):
    _set_config(monkeypatch)
    client = _FakeClient(snapshot=_SNAPSHOT)
    result = asyncio.run(tt.CreateCommissionProposalTool(client).execute(
        title="取快递", difficulty="b", is_required=True,
    ))
    assert result["status"] == "needs_confirmation"
    assert "取快递" in result["proposal"]["summary"]
    assert "必要委托" in result["proposal"]["summary"]
    assert result["proposal"]["params"]["difficulty"] == "B"
    assert client.calls == 0  # 提议阶段零 HTTP 调用


def test_create_proposal_denied_without_write_permission(monkeypatch):
    _set_config(monkeypatch, {"commissions": "read_only"})
    result = asyncio.run(tt.CreateCommissionProposalTool(_FakeClient()).execute(title="x", difficulty="A"))
    assert result["status"] == "denied"


def test_complete_proposal_resolves_quest_title(monkeypatch):
    _set_config(monkeypatch)
    result = asyncio.run(tt.CompleteCommissionProposalTool(_FakeClient(snapshot=_SNAPSHOT)).execute(quest_id=1))
    assert result["status"] == "needs_confirmation"
    assert "写周报" in result["proposal"]["summary"]


def test_complete_proposal_unknown_id_fails(monkeypatch):
    _set_config(monkeypatch)
    result = asyncio.run(tt.CompleteCommissionProposalTool(_FakeClient(snapshot=_SNAPSHOT)).execute(quest_id=999))
    assert result["status"] == "failed"
    assert "没找到" in result["error"]


def test_update_proposal_merges_current_fields(monkeypatch):
    _set_config(monkeypatch)
    result = asyncio.run(tt.UpdateCommissionProposalTool(_FakeClient(snapshot=_SNAPSHOT)).execute(
        quest_id=1, difficulty="A",
    ))
    assert result["status"] == "needs_confirmation"
    body = result["proposal"]["params"]["body"]
    assert body["difficulty"] == "A"
    assert body["title"] == "写周报"
    assert body["is_required"] is True
    assert "难度" in result["proposal"]["summary"]


def test_schedule_proposal_requires_name_or_quest(monkeypatch):
    _set_config(monkeypatch)
    result = asyncio.run(tt.AddSchedulePlanProposalTool(_FakeClient()).execute(start="20:00", end="21:00"))
    assert result["status"] == "failed"

    result = asyncio.run(tt.AddSchedulePlanProposalTool(_FakeClient()).execute(start="20:00", end="21:00", title="练琴"))
    assert result["status"] == "needs_confirmation"
    assert "20:00-21:00" in result["proposal"]["summary"]


def test_undo_proposal_skips_readonly_category(monkeypatch):
    _set_config(monkeypatch)  # legends 默认 read_only -> 跳过，选最近的 quest.create
    result = asyncio.run(tt.UndoLastActionProposalTool(_FakeClient(audit=_AUDIT)).execute())
    assert result["status"] == "needs_confirmation"
    assert result["proposal"]["params"]["audit_id"] == 8
    assert "新增委托" in result["proposal"]["summary"]


def test_undo_proposal_empty_when_nothing_undoable(monkeypatch):
    _set_config(monkeypatch)
    result = asyncio.run(tt.UndoLastActionProposalTool(_FakeClient(audit=[])).execute())
    assert result["status"] == "empty"


def test_execute_proposal_create_writes_with_companion(monkeypatch):
    _set_config(monkeypatch)
    client = _RecordingClient()
    result = asyncio.run(tt.execute_proposal("commission.create", {
        "title": "取快递", "description": "", "difficulty": "B", "category": "生活",
        "is_required": False, "is_recurring": False, "assigned_date": None,
    }, client=client))
    assert result["status"] == "success"
    assert client.calls == [("POST", "/api/quests", {
        "title": "取快递", "description": "", "difficulty": "B", "category": "生活",
        "is_required": False, "is_recurring": False, "assigned_date": None,
    })]


def test_execute_proposal_denied_after_permission_revoked(monkeypatch):
    _set_config(monkeypatch, {"commissions": "hidden"})
    client = _RecordingClient()
    result = asyncio.run(tt.execute_proposal("commission.create", {"title": "x"}, client=client))
    assert result["status"] == "denied"
    assert client.calls == []


def test_execute_proposal_undo_writes_audit_undo(monkeypatch):
    _set_config(monkeypatch)
    client = _RecordingClient()
    result = asyncio.run(tt.execute_proposal(
        "audit.undo", {"audit_id": 8, "category": "commissions"}, client=client,
    ))
    assert result["status"] == "success"
    assert client.calls == [("POST", "/api/agent/audit/8/undo", None)]


def test_execute_proposal_unknown_kind_fails(monkeypatch):
    _set_config(monkeypatch)
    result = asyncio.run(tt.execute_proposal("banana", {}, client=_RecordingClient()))
    assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# 确认框手动编辑：白名单 + 归一化 + 不改原对象
# ---------------------------------------------------------------------------

def test_apply_life_proposal_edits_whitelist_and_normalize():
    base = {"title": "旧标题", "difficulty": "b", "description": ""}
    merged = tt.apply_life_proposal_edits(
        "commission.create", base,
        {"title": "新标题", "difficulty": "a", "is_required": True, "不存在的字段": "x"},
    )
    assert merged["title"] == "新标题"
    assert merged["difficulty"] == "A"
    assert merged["is_required"] is True
    assert "不存在的字段" not in merged
    assert base["difficulty"] == "b"  # 原对象不被修改


def test_apply_life_proposal_edits_update_targets_nested_body():
    base = {"quest_id": 1, "body": {"title": "旧标题", "difficulty": "B", "category": "生活"}}
    merged = tt.apply_life_proposal_edits("commission.update", base, {"difficulty": "c"})
    assert merged["body"]["difficulty"] == "C"
    assert merged["body"]["title"] == "旧标题"
    assert base["body"]["difficulty"] == "B"


def test_apply_life_proposal_edits_keeps_false_boolean():
    merged = tt.apply_life_proposal_edits(
        "commission.complete", {"quest_id": 1, "completed": True}, {"completed": False},
    )
    assert merged["completed"] is False
