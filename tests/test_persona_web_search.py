"""Layer 2（角色卡联网字段）的测试。

覆盖三件事，缺一不可：
1. 字段本身：归一化、预设渲染、framing 覆盖、关闭时的空输出。
2. 三层门控的一致性：全局开关 × 角色卡开关 → 提示词注入 与 tools_schema 必须同步，
   否则会出现"关掉联网但模型还想着查"（卡壳）或"开着联网但模型不知道"（不触发）。
3. 落盘链路：admin PATCH 与 PersonaLoader 热更新都必须按 key 合并、保留布尔值，
   不能把没提交的子字段整段抹掉。
"""

import json

import pytest
import yaml
from unittest.mock import AsyncMock, patch

from shared.persona_loader import PersonaLoader
from shared.schema.payloads import ReasoningRequestPayload
from shared.web_search_persona import (
    STYLE_PRESETS,
    describe_persona_web_search,
    is_persona_web_search_enabled,
    normalize_web_search_settings,
    render_web_search_activity_label,
    render_web_search_persona_prompt,
)
from services.cognitive.cognitive_engine import _web_search_tool_visible
from services.cognitive.prompt_builder import PromptBuilder

WS_CONFIG = {
    "enabled": True,
    "provider": "tavily",
    "api_key_env": "TAVILY_API_KEY",
    "top_k": 5,
    "timeout_seconds": 15,
    "max_calls_per_turn": 1,
}


def _payload(trigger_type: str = "user_message") -> ReasoningRequestPayload:
    return ReasoningRequestPayload(
        event_id="evt-ws-persona",
        source_component="test",
        chat_id=1,
        user_id=1,
        short_term_history=[],
        user_profile={},
        rag_facts=[],
        trigger_type=trigger_type,
    )


# ---------------------------------------------------------------------------
# 1. 字段归一化与渲染
# ---------------------------------------------------------------------------

def test_defaults_follow_global_switch_and_use_neutral_style():
    """整段不写 = 跟随全局开关 + 中性说法（不是"没反应"）。"""
    settings = normalize_web_search_settings({"name": "x"})
    assert settings["enabled"] is True
    assert settings["style"] == "neutral"
    assert settings["alias"] == STYLE_PRESETS["neutral"]["alias"]
    assert is_persona_web_search_enabled({}) is True


def test_preset_supplies_alias_and_missed():
    settings = normalize_web_search_settings({"web_search": {"style": "divination"}})
    assert settings["style"] == "divination"
    assert settings["alias"] == STYLE_PRESETS["divination"]["alias"]
    assert settings["missed"] == STYLE_PRESETS["divination"]["missed"]


def test_explicit_alias_and_missed_override_preset():
    settings = normalize_web_search_settings({
        "web_search": {"style": "phone", "alias": "打个电话问问", "missed": "打不通。"},
    })
    assert settings["alias"] == "打个电话问问"
    assert settings["missed"] == "打不通。"


def test_unknown_style_falls_back_to_neutral():
    assert normalize_web_search_settings({"web_search": {"style": "telepathy"}})["style"] == "neutral"


def test_custom_style_without_framing_falls_back_to_neutral():
    """自动生成的角色卡可能只写了 style: custom 就交差 —— 必须仍有规则生效。"""
    assert normalize_web_search_settings({"web_search": {"style": "custom"}})["style"] == "neutral"


def test_string_false_disables_persona_web_search():
    """YAML 里写成 "false" / "off" / 0 都要按关闭处理。"""
    for raw in ("false", "off", "0", False, 0):
        assert is_persona_web_search_enabled({"web_search": {"enabled": raw}}) is False
    for raw in ("true", "on", 1, True):
        assert is_persona_web_search_enabled({"web_search": {"enabled": raw}}) is True


def test_render_contains_policy_and_persona_flavor():
    prompt = render_web_search_persona_prompt({
        "web_search": {"style": "phone", "alias": "翻手机查一下", "missed": "没翻到。"},
    })
    assert "翻手机查一下" in prompt
    assert "没翻到。" in prompt
    # 硬规则必须在场
    assert "不该查" in prompt
    assert "你自己的世界、经历、记忆和感受" in prompt


def test_framing_overrides_preset_verb_but_not_hard_rules():
    prompt = render_web_search_persona_prompt({
        "web_search": {"style": "phone", "framing": "说成「让我问问我的线人」。"},
    })
    assert "让我问问我的线人" in prompt
    # 预设的"怎么说"被覆盖了，但硬规则还在
    assert "我刚翻了下手机" not in prompt
    assert "不该查" in prompt
    assert "绝不能去查" in prompt


def test_render_is_empty_when_persona_disabled():
    assert render_web_search_persona_prompt({"web_search": {"enabled": False}}) == ""
    assert "已关闭" in describe_persona_web_search({"web_search": {"enabled": False}})


def test_searching_label_is_persona_flavoured():
    """Layer 4 的界面提示文案和 alias/framing 同源 —— 也归角色卡管。

    前端只是原文显示后端给的 label，所以"正在翻手机查资料…"这种说法
    必须由这里渲染，否则换一个古代剑客人设就会看到出戏的"正在搜索互联网…"。
    """
    assert render_web_search_activity_label(
        {"web_search": {"style": "library"}}
    ) == STYLE_PRESETS["library"]["searching"]
    # 单字段覆盖优先于预设
    assert render_web_search_activity_label(
        {"web_search": {"style": "phone", "searching": "让我翻翻手机…"}}
    ) == "让我翻翻手机…"
    # 人设关掉联网就不该出现"正在查资料"的提示
    assert render_web_search_activity_label({"web_search": {"enabled": False}}) == ""


# ---------------------------------------------------------------------------
# 2. 三层门控一致性
# ---------------------------------------------------------------------------

def test_prompt_injects_both_blocks_when_all_three_gates_open():
    persona = {"name": "T", "web_search": {"style": "phone"}}
    with patch.object(PersonaLoader, "load_active_persona", return_value=persona), \
         patch("services.cognitive.prompt_builder.is_web_search_available", return_value=True):
        prompt = PromptBuilder.build_system_prompt(_payload())

    assert "联网搜索能力" in prompt          # 能力 + 网页内容安全规则
    assert "联网检索的分寸" in prompt        # 角色卡贡献的分寸
    assert "<untrusted_content>" in prompt


def test_prompt_omits_everything_when_persona_disables_web_search():
    persona = {"name": "清朝格格", "web_search": {"enabled": False, "style": "phone"}}
    with patch.object(PersonaLoader, "load_active_persona", return_value=persona), \
         patch("services.cognitive.prompt_builder.is_web_search_available", return_value=True):
        prompt = PromptBuilder.build_system_prompt(_payload())

    assert "联网搜索能力" not in prompt
    assert "联网检索的分寸" not in prompt


def test_prompt_omits_everything_when_global_switch_off():
    persona = {"name": "T", "web_search": {"style": "phone"}}
    with patch.object(PersonaLoader, "load_active_persona", return_value=persona), \
         patch("services.cognitive.prompt_builder.is_web_search_available", return_value=False):
        prompt = PromptBuilder.build_system_prompt(_payload())

    assert "联网搜索能力" not in prompt
    assert "联网检索的分寸" not in prompt


def test_prompt_omits_web_search_block_on_game_turn():
    persona = {"name": "T", "web_search": {"style": "phone"}}
    with patch.object(PersonaLoader, "load_active_persona", return_value=persona), \
         patch("services.cognitive.prompt_builder.is_web_search_available", return_value=True):
        prompt = PromptBuilder.build_system_prompt(_payload("game_turn"))

    assert "联网检索的分寸" not in prompt


def test_tool_visibility_matches_prompt_gating():
    """tools_schema 侧的门控必须与提示词侧同源，否则模型会看到"不存在的工具"。"""
    persona_off = {"name": "T", "web_search": {"enabled": False}}
    persona_on = {"name": "T", "web_search": {"enabled": True}}

    with patch("services.cognitive.cognitive_engine.is_web_search_available", return_value=True), \
         patch("services.cognitive.cognitive_engine.get_web_search_config", return_value=dict(WS_CONFIG)), \
         patch("services.cognitive.cognitive_engine.PersonaLoader") as mock_loader:
        mock_loader.load_active_persona.return_value = persona_on
        assert _web_search_tool_visible(0) is True
        assert _web_search_tool_visible(1) is False, "max_calls_per_turn=1 用完后应摘掉工具"

        mock_loader.load_active_persona.return_value = persona_off
        assert _web_search_tool_visible(0) is False

    with patch("services.cognitive.cognitive_engine.is_web_search_available", return_value=False):
        assert _web_search_tool_visible(0) is False


# ---------------------------------------------------------------------------
# 3. 落盘链路：admin PATCH 与 PersonaLoader 热更新
# ---------------------------------------------------------------------------

@pytest.fixture()
def persona_yaml(tmp_path):
    path = tmp_path / "ws_persona.yaml"
    path.write_text(
        "id: ws_persona\n"
        "name: Test\n"
        "web_search:\n"
        "  enabled: true\n"
        "  style: phone\n"
        "  alias: 翻手机\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_hot_reload_merges_web_search_and_keeps_boolean(persona_yaml, monkeypatch):
    monkeypatch.setattr(PersonaLoader, "_persona_path", classmethod(lambda cls, pid: str(persona_yaml)))
    PersonaLoader.invalidate_cache()

    await PersonaLoader.handle_persona_update(json.dumps({
        "persona_id": "ws_persona",
        "web_search": {"enabled": False, "alias": "查一下"},
    }).encode("utf-8"))

    data = yaml.safe_load(persona_yaml.read_text(encoding="utf-8"))
    assert data["web_search"]["enabled"] is False      # 布尔值必须活下来
    assert data["web_search"]["alias"] == "查一下"
    assert data["web_search"]["style"] == "phone"      # 未提交的子字段不能被抹掉


@pytest.mark.asyncio
async def test_hot_reload_drops_unknown_web_search_subfields(persona_yaml, monkeypatch):
    monkeypatch.setattr(PersonaLoader, "_persona_path", classmethod(lambda cls, pid: str(persona_yaml)))
    PersonaLoader.invalidate_cache()

    await PersonaLoader.handle_persona_update(json.dumps({
        "persona_id": "ws_persona",
        "web_search": {"enabled": True, "api_key": "sk-injected", "evil": {"nested": 1}},
    }).encode("utf-8"))

    data = yaml.safe_load(persona_yaml.read_text(encoding="utf-8"))
    assert data["web_search"].get("api_key") is None
    assert "evil" not in data["web_search"]


@pytest.fixture()
def admin_client(tmp_path):
    from fastapi.testclient import TestClient

    import admin.backend.main as admin_main
    from admin.backend.main import app

    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "ws_persona.yaml").write_text(
        "id: ws_persona\n"
        "name: Test\n"
        "web_search:\n"
        "  enabled: true\n"
        "  style: phone\n"
        "  alias: 翻手机\n"
        "  missed: 没翻到。\n",
        encoding="utf-8",
    )
    with patch.object(admin_main, "ADMIN_SECRET_KEY", ""), \
         patch.object(admin_main, "PERSONA_DIR", persona_dir):
        yield TestClient(app, raise_server_exceptions=False), persona_dir


def _patch_ws(client, payload):
    with patch("admin.backend.main._nats_publish", new_callable=AsyncMock, return_value=True):
        return client.patch("/api/admin/personas/ws_persona", json=payload)


def test_admin_patch_accepts_boolean_enabled_and_persists_it(admin_client):
    client, persona_dir = admin_client
    resp = _patch_ws(client, {"web_search": {"enabled": False}})
    assert resp.status_code == 200

    data = yaml.safe_load((persona_dir / "ws_persona.yaml").read_text(encoding="utf-8"))
    assert data["web_search"]["enabled"] is False
    assert data["web_search"]["style"] == "phone", "只改 enabled 不该抹掉其它子字段"


def test_admin_patch_rejects_non_boolean_enabled(admin_client):
    client, _ = admin_client
    resp = _patch_ws(client, {"web_search": {"enabled": "false"}})
    assert resp.status_code == 400
    assert "boolean" in resp.json()["error"]


def test_admin_patch_rejects_unknown_style_and_subfield(admin_client):
    client, _ = admin_client
    assert _patch_ws(client, {"web_search": {"style": "telepathy"}}).status_code == 400
    assert _patch_ws(client, {"web_search": {"api_key": "sk-x"}}).status_code == 400


def test_admin_get_persona_exposes_web_search(admin_client):
    client, _ = admin_client
    body = client.get("/api/admin/personas/ws_persona").json()
    assert body["web_search"]["style"] == "phone"
