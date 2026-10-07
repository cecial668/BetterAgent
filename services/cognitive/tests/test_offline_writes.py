"""离线写入能力测试：focus URL 前缀、历史日记、待提交队列、本地直连、权限门控。"""
import asyncio
import os
import sys

import pytest

import shared.config_loader as config_loader
import shared.tothestars_outbox as outbox
from services.cognitive.tools import tothestars_tool as tt

TOTHESTARS_ROOT = r"E:\ToTheStars\ToTheStarsV26-6-1\ToTheStarsWeb_react_frontend_full\ToTheStarsWeb\ToTheStarsWeb"


def _set_tothestars(monkeypatch, **section):
    base = {"enabled": True, "endpoint": "http://127.0.0.1:8765", "timeout_seconds": 0.3}
    base.update(section)
    monkeypatch.setattr(
        config_loader, "_cached_config",
        {"integration": {"tothestars": base}},
        raising=False,
    )


# ---------- bug 回归：番茄钟写入路径 ----------

def test_create_focus_session_uses_api_prefix():
    client = tt.TothestarsClient(endpoint="http://x")
    calls = []

    async def fake_request(method, path, params=None, json_body=None):
        calls.append((method, path, json_body))
        return {"ok": True, "data": {"ok": True}}

    client.request_json = fake_request
    result = asyncio.run(client.create_focus_session(
        started_at="2026-09-13 09:00:00",
        ended_at="2026-09-13 10:00:00",
        planned_minutes=60,
        duration_seconds=3600,
        category="工作",
        description="写完了报告",
    ))
    assert result["ok"] is True
    # 回归防线：必须带 /api 前缀（向着星统一挂在 /api 下，少了就是 404）
    assert calls[0][1] == "/api/focus/sessions"
    assert calls[0][2]["planned_minutes"] == 60


# ---------- bug 回归：历史日记 ----------

def test_get_journal_history_uses_snapshot_date():
    client = tt.TothestarsClient(endpoint="http://x")
    calls = []

    async def fake_request(method, path, params=None, json_body=None):
        calls.append((method, path, params))
        return {"ok": True, "data": {"journal": {"date": "2026-09-12", "has_text": True}}}

    client.request_json = fake_request
    result = asyncio.run(client.get_journal(date="2026-09-12", include_text=True))
    assert result["ok"] is True
    assert result["data"]["date"] == "2026-09-12"
    assert calls == [(
        "GET", "/api/agent/snapshot",
        {"date": "2026-09-12", "include_journal_text": "true"},
    )]


def test_get_journal_history_missing_returns_error():
    client = tt.TothestarsClient(endpoint="http://x")

    async def fake_request(method, path, params=None, json_body=None):
        return {"ok": True, "data": {"journal": None}}

    client.request_json = fake_request
    result = asyncio.run(client.get_journal(date="2026-01-01"))
    assert result["ok"] is False
    assert "2026-01-01" in result["error"]


# ---------- 权限：专注类目门控 ----------

def test_focus_propose_tool_gated_by_write_permission(monkeypatch):
    from shared.life_data_permissions import is_tool_visible

    _set_tothestars(monkeypatch, permissions={"focus": "read_only"})
    assert is_tool_visible("focus_propose_session") is False

    _set_tothestars(monkeypatch, permissions={"focus": "read_write_proactive"})
    assert is_tool_visible("focus_propose_session") is True

    _set_tothestars(monkeypatch, enabled=False, permissions={"focus": "read_write_proactive"})
    assert is_tool_visible("focus_propose_session") is False


def test_focus_record_requires_write_permission(monkeypatch):
    from services.cognitive.tools.focus_tool import record_focus_session

    _set_tothestars(monkeypatch, permissions={"focus": "read_only"})
    result = asyncio.run(record_focus_session(
        started_at="2026-09-13 09:00:00",
        ended_at="2026-09-13 10:00:00",
        planned_minutes=60,
        duration_seconds=3600,
    ))
    assert result["status"] == "failed"
    assert "权限" in result["error"]


# ---------- 待提交队列 ----------

def test_outbox_backoff_and_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox, "OUTBOX_PATH", tmp_path / "outbox.json", raising=False)
    item = outbox.enqueue("POST", "/api/quests", json_body={"title": "取快递"})
    assert outbox.pending_count() == 1

    assert outbox.due_items(now=item["next_at"] - 1) == []
    due = outbox.due_items(now=item["next_at"] + 1)
    assert len(due) == 1 and due[0]["id"] == item["id"]

    updated = outbox.mark_failure(item["id"])
    assert updated is not None
    assert updated["attempts"] == 1
    assert updated["next_at"] > item["next_at"]

    delivered = outbox.mark_success(item["id"])
    assert delivered is not None and delivered["label"] == "委托修改"
    assert outbox.pending_count() == 0


def test_outbox_label_for_path():
    assert outbox.label_for_path("/api/quests/3/complete") == "委托修改"
    assert outbox.label_for_path("/api/schedule/plans") == "日程修改"
    assert outbox.label_for_path("/api/focus/sessions") == "专注记录"
    assert outbox.label_for_path("/api/agent/audit/9/undo") == "撤销操作"


# ---------- 远程模式：失败暂存 ----------

def test_remote_mode_write_failure_enqueues(monkeypatch, tmp_path):
    monkeypatch.setattr(outbox, "OUTBOX_PATH", tmp_path / "outbox.json", raising=False)
    _set_tothestars(monkeypatch, write_mode="remote")

    async def fake_http(method, path, params=None, json_body=None):
        return {"ok": False, "error": "连不上", "retryable": True}

    client = tt.TothestarsClient()
    client.request_json_http = fake_http
    result = asyncio.run(client.request_json("POST", "/api/quests", json_body={"title": "x"}))
    assert result["ok"] is True and result.get("queued") is True
    assert outbox.pending_count() == 1


def test_remote_mode_4xx_not_enqueued(monkeypatch, tmp_path):
    monkeypatch.setattr(outbox, "OUTBOX_PATH", tmp_path / "outbox.json", raising=False)
    _set_tothestars(monkeypatch, write_mode="remote")

    async def fake_http(method, path, params=None, json_body=None):
        return {"ok": False, "error": "参数不合法", "retryable": False}

    client = tt.TothestarsClient()
    client.request_json_http = fake_http
    result = asyncio.run(client.request_json("POST", "/api/quests", json_body={}))
    assert result["ok"] is False
    assert outbox.pending_count() == 0


def test_local_mode_routes_to_bridge(monkeypatch):
    _set_tothestars(monkeypatch, write_mode="local", local_project_root=r"C:\fake\root")
    called = {}

    class FakeBridge:
        def request_json(self, method, path, params=None, json_body=None):
            called.update({"method": method, "path": path, "body": json_body})
            return {"ok": True, "data": {"ok": True, "id": 7}}

    monkeypatch.setattr(tt, "_get_local_bridge", lambda root: FakeBridge())
    client = tt.TothestarsClient()
    result = asyncio.run(client.request_json("POST", "/api/quests", json_body={"title": "x"}))
    assert result == {"ok": True, "data": {"ok": True, "id": 7}}
    assert called["path"] == "/api/quests"


# ---------- 本地直连（用临时数据库跑真实向着星服务层） ----------

@pytest.mark.skipif(not os.path.isdir(TOTHESTARS_ROOT), reason="本机没有向着星项目")
def test_local_bridge_writes_and_audits(tmp_path):
    if TOTHESTARS_ROOT not in sys.path:
        sys.path.insert(0, TOTHESTARS_ROOT)
    from app.db.database import Database
    from services.cognitive.tools.tothestars_local import LocalToTheStars

    db = Database(tmp_path / "growth.db")
    bridge = LocalToTheStars(TOTHESTARS_ROOT)
    bridge._db = db

    created = bridge.request_json("POST", "/api/quests", json_body={
        "title": "本地直连测试", "description": "", "difficulty": "C",
        "category": "测试", "is_required": False, "is_recurring": False,
        "assigned_date": "2026-09-13",
    })
    assert created["ok"] is True and created["data"]["id"] > 0
    qid = created["data"]["id"]

    with db.connect() as conn:
        audit = conn.execute("SELECT id, actor, action, undoable FROM agent_audit ORDER BY id DESC LIMIT 1").fetchone()
    assert audit["actor"] == "companion"
    assert audit["action"] == "quest.create"
    assert audit["undoable"] == 1

    complete = bridge.request_json("POST", f"/api/quests/{qid}/complete", json_body={"completed": True})
    assert complete["ok"] is True

    plan = bridge.request_json("POST", "/api/schedule/plans", json_body={
        "plan_date": "2026-09-13", "title": "写代码", "content": "",
        "start": "09:00", "end": "10:00",
    })
    assert plan["ok"] is True and plan["data"]["plan"]["id"] > 0

    focus = bridge.request_json("POST", "/api/focus/sessions", json_body={
        "started_at": "2026-09-13 09:00:00", "ended_at": "2026-09-13 10:00:00",
        "planned_minutes": 60, "duration_seconds": 3600,
        "category": "工作", "description": "写完了报告",
    })
    assert focus["ok"] is True and focus["data"]["ok"] is True
    with db.connect() as conn:
        row = conn.execute("SELECT category, description FROM focus_sessions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["category"] == "工作" and row["description"] == "写完了报告"

    snap = bridge.request_json("GET", "/api/agent/snapshot", params={"date": "2026-09-13"})
    assert snap["ok"] is True and snap["data"]["date"] == "2026-09-13"

    # 撤销刚才的 quest.create（走审计，与网页端同一套逻辑）
    undone = bridge.request_json("POST", f"/api/agent/audit/{audit['id']}/undo")
    assert undone["ok"] is True
    with db.connect() as conn:
        left = conn.execute("SELECT COUNT(*) AS c FROM daily_quests WHERE id=?", (qid,)).fetchone()
    assert left["c"] == 0


@pytest.mark.skipif(not os.path.isdir(TOTHESTARS_ROOT), reason="本机没有向着星项目")
def test_local_bridge_rejects_bad_params(tmp_path):
    if TOTHESTARS_ROOT not in sys.path:
        sys.path.insert(0, TOTHESTARS_ROOT)
    from app.db.database import Database
    from services.cognitive.tools.tothestars_local import LocalToTheStars

    bridge = LocalToTheStars(TOTHESTARS_ROOT)
    bridge._db = Database(tmp_path / "growth.db")

    # 难度非法：与 HTTP 路由的 pydantic 校验同一套规则
    bad = bridge.request_json("POST", "/api/quests", json_body={"title": "x", "difficulty": "Z"})
    assert bad["ok"] is False and "difficulty" in bad["error"]
