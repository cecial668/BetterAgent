"""权限内核测试：四档解析、默认最小权限、工具可见性。

隔离策略：直接替换 shared.config_loader 的进程级缓存，测完由 monkeypatch 还原。
"""
import shared.config_loader as config_loader
from shared import life_data_permissions as perms


def _set_config(monkeypatch, config):
    monkeypatch.setattr(config_loader, "_cached_config", config, raising=False)


def _cfg(permissions=None, enabled=True):
    section = {"enabled": enabled, "endpoint": "http://127.0.0.1:8765", "timeout_seconds": 2.0}
    if permissions is not None:
        section["permissions"] = permissions
    return {"integration": {"tothestars": section}}


def test_missing_config_means_disabled_and_hidden_tools(monkeypatch):
    _set_config(monkeypatch, {})
    assert perms.is_tothestars_enabled() is False
    for name in ("tothestars_get_life_snapshot", "tothestars_get_commissions", "tothestars_get_journal_summary"):
        assert perms.is_tool_visible(name) is False
    assert perms.is_tool_visible("web_search") is True


def test_default_tiers_follow_minimal_privilege(monkeypatch):
    _set_config(monkeypatch, _cfg())
    assert perms.get_permission("commissions") == perms.TIER_READ_WRITE_PROACTIVE
    assert perms.can_write("commissions") is True
    assert perms.get_permission("legends") == perms.TIER_READ_ONLY
    assert perms.can_read("legends") is True
    assert perms.can_write("legends") is False
    assert perms.get_permission("journal") == perms.TIER_ON_REQUEST
    assert perms.can_read("journal") is True
    assert perms.can_be_proactive("journal") is False
    assert perms.get_permission("journal_text") == perms.TIER_HIDDEN
    assert perms.can_read("journal_text") is False


def test_unknown_tier_fails_closed(monkeypatch):
    _set_config(monkeypatch, _cfg({"commissions": "banana", "wallet": ""}))
    assert perms.get_permission("commissions") == perms.TIER_HIDDEN
    assert perms.get_permission("wallet") == perms.TIER_HIDDEN
    assert perms.is_tool_visible("tothestars_get_commissions") is False


def test_tool_visibility_follows_category_permission(monkeypatch):
    _set_config(monkeypatch, _cfg({"journal": "hidden", "legends": "hidden"}))
    assert perms.is_tool_visible("tothestars_get_journal_summary") is False
    assert perms.is_tool_visible("tothestars_get_legend_progress") is False
    assert perms.is_tool_visible("tothestars_get_commissions") is True
    # 快照只要还有任一可读类目就可见
    assert perms.is_tool_visible("tothestars_get_life_snapshot") is True
    # 未知 tothestars_* 工具 fail-closed
    assert perms.is_tool_visible("tothestars_unknown_tool") is False


def test_disabled_hides_all_tothestars_tools(monkeypatch):
    _set_config(monkeypatch, _cfg(enabled=False))
    assert perms.is_tool_visible("tothestars_get_life_snapshot") is False
    assert perms.is_tool_visible("tothestars_get_commissions") is False
    assert perms.is_tool_visible("tothestars_get_journal_summary") is False
    assert perms.is_tool_visible("add_schedule") is True


def test_write_tools_follow_write_permission(monkeypatch):
    _set_config(monkeypatch, _cfg({"commissions": "read_only"}))
    assert perms.is_tool_visible("tothestars_propose_create_commission") is False
    # schedule 仍是默认可写档
    assert perms.is_tool_visible("tothestars_propose_add_schedule_plan") is True

    _set_config(monkeypatch, _cfg({"commissions": "read_write_proactive"}))
    assert perms.is_tool_visible("tothestars_propose_create_commission") is True
    assert perms.is_tool_visible("tothestars_propose_complete_commission") is True
    assert perms.is_tool_visible("tothestars_propose_update_commission") is True


def test_undo_tool_needs_some_writable_category(monkeypatch):
    _set_config(monkeypatch, _cfg({"commissions": "read_only", "schedule": "read_only", "legends": "read_only"}))
    assert perms.is_tool_visible("tothestars_propose_undo_last_action") is False

    _set_config(monkeypatch, _cfg({"commissions": "read_write_proactive", "schedule": "read_only"}))
    assert perms.is_tool_visible("tothestars_propose_undo_last_action") is True
