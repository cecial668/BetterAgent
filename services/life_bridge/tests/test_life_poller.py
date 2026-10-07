"""生活事件桥的纯判定测试：窗口/阈值/去重/连续天数。

不发起任何网络请求 —— poll_once 的真实链路由 e2e 脚本覆盖。
"""
from datetime import datetime

from services.life_bridge.life_poller import (
    BridgeState,
    current_streak,
    evaluate_events,
)

DAY = "2026-09-12"


def _snapshot(**overrides):
    snapshot = {
        "date": DAY,
        "commissions": [
            {"id": 1, "title": "写周报", "is_required": True, "is_completed": False},
            {"id": 2, "title": "背单词", "is_required": False, "is_completed": True},
        ],
        "schedule": {"plans": [{"id": 5, "title": "组会", "start": "09:00", "end": "10:00"}]},
        "legends": [],
        "journal": None,
    }
    snapshot.update(overrides)
    return snapshot


def _types(events):
    return [e.event_type for e in events]


def test_morning_brief_fires_once_inside_window():
    state = BridgeState()
    now = datetime(2026, 9, 12, 8, 0)
    events = evaluate_events(_snapshot(), [], now, state)
    assert "morning_brief" in _types(events)
    detail = next(e.detail for e in events if e.event_type == "morning_brief")
    assert "2 条委托" in detail and "必要 1 条" in detail and "1 项日程" in detail

    state.mark_sent("morning_brief", DAY)
    assert "morning_brief" not in _types(evaluate_events(_snapshot(), [], now, state))


def test_morning_brief_not_outside_window_or_when_empty():
    state = BridgeState()
    assert "morning_brief" not in _types(evaluate_events(_snapshot(), [], datetime(2026, 9, 12, 6, 30), state))
    assert "morning_brief" not in _types(evaluate_events(_snapshot(), [], datetime(2026, 9, 12, 11, 0), state))
    empty = _snapshot(commissions=[], schedule={"plans": []})
    assert "morning_brief" not in _types(evaluate_events(empty, [], datetime(2026, 9, 12, 8, 0), state))


def test_required_unfinished_only_after_evening_and_when_pending():
    state = BridgeState()
    assert "required_unfinished" not in _types(evaluate_events(_snapshot(), [], datetime(2026, 9, 12, 19, 30), state))

    events = evaluate_events(_snapshot(), [], datetime(2026, 9, 12, 20, 30), state)
    assert "required_unfinished" in _types(events)
    detail = next(e.detail for e in events if e.event_type == "required_unfinished")
    assert "还差 1 条" in detail and "写周报" in detail

    done = _snapshot(commissions=[{"id": 1, "title": "写周报", "is_required": True, "is_completed": True}])
    assert "required_unfinished" not in _types(evaluate_events(done, [], datetime(2026, 9, 12, 21, 0), state))


def test_deadline_near_threshold_and_dedupe():
    state = BridgeState()
    near = _snapshot(legends=[{"id": 3, "title": "期末复习", "remaining_days": 2}])
    far = _snapshot(legends=[{"id": 4, "title": "读完一摞书", "remaining_days": 5}])
    expired = _snapshot(legends=[{"id": 5, "title": "旧目标", "remaining_days": -1}])

    assert "deadline_near" in _types(evaluate_events(near, [], datetime(2026, 9, 12, 12, 0), state))
    assert "deadline_near" not in _types(evaluate_events(far, [], datetime(2026, 9, 12, 12, 0), state))
    assert "deadline_near" not in _types(evaluate_events(expired, [], datetime(2026, 9, 12, 12, 0), state))

    state.mark_sent("deadline_near:3", DAY)
    assert "deadline_near" not in _types(evaluate_events(near, [], datetime(2026, 9, 12, 12, 0), state))


def test_evening_review_only_without_journal_inside_window():
    state = BridgeState()
    assert "evening_review" not in _types(evaluate_events(_snapshot(), [], datetime(2026, 9, 12, 20, 0), state))
    assert "evening_review" in _types(evaluate_events(_snapshot(), [], datetime(2026, 9, 12, 21, 30), state))

    written = _snapshot(journal={"date": DAY, "rating": 4})
    assert "evening_review" not in _types(evaluate_events(written, [], datetime(2026, 9, 12, 21, 30), state))


def test_streak_milestone_at_week_multiples_only():
    state = BridgeState()
    now = datetime(2026, 9, 12, 15, 0)
    seven = [{"date": f"2026-09-{d:02d}", "is_success": 1} for d in range(6, 13)]
    six = seven[1:]

    assert "streak_milestone" not in _types(evaluate_events(_snapshot(), six, now, state))
    events = evaluate_events(_snapshot(), seven, now, state)
    assert "streak_milestone" in _types(events)
    assert "连续完成 7 天" in next(e.detail for e in events if e.event_type == "streak_milestone")

    state.mark_sent("streak_milestone:7", DAY)
    assert "streak_milestone" not in _types(evaluate_events(_snapshot(), seven, now, state))

    fourteen = seven + [{"date": f"2026-08-{d:02d}", "is_success": 1} for d in range(23, 30)]
    assert "streak_milestone" in _types(evaluate_events(_snapshot(), fourteen, now, state))


def test_current_streak_breaks_on_failure_and_skips_unknown():
    rows = [
        {"is_success": 1},
        {"is_success": None},  # 未定：跳过，不断
        {"is_success": 1},
        {"is_success": 0},
        {"is_success": 1},
    ]
    assert current_streak(rows) == 2
    assert current_streak([]) == 0
