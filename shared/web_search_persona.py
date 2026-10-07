"""角色卡里的「联网搜索」字段（Layer 2）。

字段形状（config/persona/<id>.yaml）：

```yaml
web_search:
  enabled: true      # 这个人设会不会上网；缺省 = 跟随全局开关
  style: phone       # 预设说法：neutral|phone|divination|library|informant|oracle|custom
  alias: ""          # 你对这个能力的自称（为空则用预设默认）
  missed: ""         # 查不到时的说法（为空则用预设默认）
  searching: ""      # 正在查的时候，界面/字幕上显示什么（为空则用预设默认）
  framing: ""        # 整段自定义「怎么说出口」，覆盖预设的说法
```

职责分工（见 docs/WEB-SEARCH-PLAN.md §5.1）：

- 工具的 `description` 保持**功能性、静态**（决定模型会不会去调，即触发率）；
- 「什么时候该查 / 什么时候绝不能查 / 查到了怎么说出口」写在这里（决定割不割裂人设）。

**为什么必须有一个"不查"的出口**：没有出口的角色一定会为了维持"无所不知"而编造。
所以本模块渲染出来的提示词里，语气化的部分（alias / framing / missed）可以被角色卡覆盖，
但两条行为硬规则（"越界查询"清单与"她自己的世界不查"）**永远附加在后面**，不可被覆盖 ——
这是安全网，不是风格。

本模块同时被 prompt_builder（注入提示词）与 cognitive_engine（工具门控）使用，
保证"模型看不看得见工具"和"提示词里有没有这段说明"永远一致。
"""

import logging
from typing import Any, Dict

logger = logging.getLogger("web_search_persona")

# 预设说法。neutral 是缺省：没填 style 的人设拿到的是一段中性、不带表演色彩的说明，
# 既不会跟任何世界观打架，也能让"该查/不该查"的规则生效。
# 注意：改这里的 key 必须同步 admin/backend/main.py 的 WEB_SEARCH_ALLOWED_STYLES。
STYLE_PRESETS: Dict[str, Dict[str, str]] = {
    "neutral": {
        "label": "中性（不角色化）",
        "alias": "查一下资料",
        "verb": "用你自己的话把结论讲出来就好，不要念网址、不要说「根据搜索结果」这类出戏的词；对方追问来源时再说一句「网上是这么说的」。",
        "missed": "这个确实没查到，别硬编——就说你也不清楚。",
        "searching": "正在查资料…",
    },
    "phone": {
        "label": "随手掏手机（现代日常）",
        "alias": "掏手机查一下",
        "verb": "说成你随手掏出手机翻了一下：「我刚翻了下手机——」。把结论说人话，别念网址。",
        "missed": "我手机上没搜到，回头再帮你留意。",
        "searching": "正在翻手机查资料…",
    },
    "divination": {
        "label": "掐指一算（仙侠 / 神明）",
        "alias": "掐指一算",
        "verb": "说成你在推算天机：「让我卜一卦……」。把查到的结果讲成你算出来的卦象，别暴露「查资料」这件事。",
        "missed": "卦象不明……天机不肯说，这个我真算不出来。",
        "searching": "正在掐指推算…",
    },
    "library": {
        "label": "翻查典籍（学者 / 古典）",
        "alias": "翻翻典籍",
        "verb": "说成你翻了藏书阁的卷宗：「让我查查典籍……」。用书面腔把结论讲出来。",
        "missed": "典籍里没有记载，此事恐怕无从查证。",
        "searching": "正在翻查典籍…",
    },
    "informant": {
        "label": "托人打听（侦探 / 江湖）",
        "alias": "托人打听",
        "verb": "说成你托线人问了一圈：「我让人去打听了一下……」。把结果讲成江湖上的消息。",
        "missed": "线人那边还没信儿，这事暂时打听不到。",
        "searching": "正在托人打听…",
    },
    "oracle": {
        "label": "感知世界（超能力 / 灵媒）",
        "alias": "感知一下",
        "verb": "说成你闭眼感知：「让我听听风里的声音……」。把结果讲成你感知到的碎片。",
        "missed": "世界没有回应……这一段我感知不到。",
        "searching": "正在感应世界…",
    },
    "custom": {
        "label": "完全自定义（自己写 framing）",
        "alias": "",
        "verb": "",
        "missed": "",
        "searching": "正在查阅资料…",
    },
}

DEFAULT_STYLE = "neutral"

# 行为硬规则。{alias} / {verb} / {missed} 会被角色卡的值替换；
# 其余部分不可被角色卡覆盖。
_POLICY_TEMPLATE = (
    "你确实能知道现实世界里正在发生的事（在你的人设里，这个本事叫「{alias}」）。"
    "用它的时候，守住下面的分寸：\n"
    "· 该查：对方明确让你去查（「查一下」「搜一下」「看看最新」），"
    "或者答案依赖现实世界中当前/会变的信息（天气、价格、新闻、赛况、政策、版本号、某人的近况等），而你没有把握。\n"
    "· 不该查（以下情况一律不查）：\n"
    "  1. 关于【你自己的世界、经历、记忆和感受】的一切——那些是你亲历的，不需要查，也绝不能去查；"
    "别人提起它们时，你要凭记忆回答。\n"
    "  2. 对方在跟你谈感情、求安慰、撒娇、闹别扭、开玩笑、闲聊、起名字、写东西的时候——别掏工具。\n"
    "  3. 你自己已经知道、而且答案不会变的时候——宁可凭记忆直接回答，也别为了「显得严谨」而去查。\n"
    "· 怎么说出口：{verb}\n"
    "· 查不到的时候：{missed}"
)


def _as_bool(value: Any, default: bool = True) -> bool:
    """YAML 里写成 true / "false" / 1 / "on" 都要能正确解释。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in ("1", "true", "yes", "on"):
            return True
        if stripped in ("0", "false", "no", "off"):
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_web_search_settings(persona_data: Any) -> Dict[str, Any]:
    """把角色卡里的 web_search 段归一化成全部字段都存在、类型正确的字典。

    缺省语义（很重要）：
    - `enabled` 缺省为 True —— 也就是"跟随全局开关"。角色卡没写过这个字段时，
      全局开关打开就该能用；否则用户打开全局开关却发现所有人设都没反应。
    - `style` 缺省为 neutral（中性说明，不带任何表演色彩）。
    - `style` 填了未知值、或填了 custom 却没写 framing 时，退回 neutral，
      而不是让整段说明消失（规则比风格重要）。
    """
    raw = persona_data.get("web_search") if isinstance(persona_data, dict) else None
    raw = raw if isinstance(raw, dict) else {}

    framing = _as_str(raw.get("framing"))
    style = _as_str(raw.get("style")).lower()
    if style not in STYLE_PRESETS:
        style = "custom" if framing else DEFAULT_STYLE
    if style == "custom" and not framing:
        style = DEFAULT_STYLE

    preset = STYLE_PRESETS[style]
    return {
        "enabled": _as_bool(raw.get("enabled"), True),
        "style": style,
        "alias": _as_str(raw.get("alias")) or preset["alias"],
        "missed": _as_str(raw.get("missed")) or preset["missed"],
        "searching": _as_str(raw.get("searching")) or preset["searching"],
        "framing": framing,
    }


def is_persona_web_search_enabled(persona_data: Any) -> bool:
    """这个人设是否允许联网（角色卡级开关）。缺省 True。"""
    return bool(normalize_web_search_settings(persona_data)["enabled"])


def render_web_search_persona_prompt(persona_data: Any) -> str:
    """渲染角色卡贡献的那段「联网分寸」提示词。

    人设关闭联网时返回空串——调用方据此**同时**撤掉提示词与工具，两者必须一致。
    """
    settings = normalize_web_search_settings(persona_data)
    if not settings["enabled"]:
        return ""

    preset = STYLE_PRESETS[settings["style"]]
    # framing 存在时覆盖预设的说法（保留 alias/missed 兜底），这就是"整段自定义"。
    verb = settings["framing"] or preset["verb"] or STYLE_PRESETS[DEFAULT_STYLE]["verb"]
    missed = settings["missed"] or preset["missed"] or STYLE_PRESETS[DEFAULT_STYLE]["missed"]

    body = _POLICY_TEMPLATE.format(
        alias=settings["alias"] or STYLE_PRESETS[DEFAULT_STYLE]["alias"],
        verb=verb,
        missed=missed,
    )
    return f"[联网检索的分寸]（在你的人设里，这个本事叫「{settings['alias'] or STYLE_PRESETS[DEFAULT_STYLE]['alias']}」）\n{body}"


def render_web_search_activity_label(persona_data: Any) -> str:
    """渲染「正在查资料…」这一行提示文案（Layer 4，前端呼吸光提示用）。

    这是**界面文案**，不是提示词，所以它跟 alias/framing 一样属于"说法"，
    由角色卡决定 —— 芙宁娜显示「正在翻手机查资料…」，古代剑客显示「正在翻查典籍…」，
    前端不需要自己拼一句出戏的"正在搜索互联网…"。

    人设关闭联网时返回空串：关掉联网的角色不该出现"正在查资料"的提示。
    """
    settings = normalize_web_search_settings(persona_data)
    if not settings["enabled"]:
        return ""
    preset = STYLE_PRESETS[settings["style"]]
    return (
        settings["searching"]
        or preset["searching"]
        or STYLE_PRESETS[DEFAULT_STYLE]["searching"]
    )


def describe_persona_web_search(persona_data: Any) -> str:
    """一行中文摘要，用于日志与设置页提示。"""
    settings = normalize_web_search_settings(persona_data)
    if not settings["enabled"]:
        return "角色卡联网: 已关闭（这个人设不上网）"
    return (
        f"角色卡联网: 已开启 (style={settings['style']}, "
        f"alias={settings['alias'] or '(预设默认)'})"
    )
