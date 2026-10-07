import time
import re
import json
import uuid
import logging
from typing import List, Dict, Any, Tuple, Optional
from shared.schema.payloads import ReasoningRequestPayload, ActionDecisionPayload, EmotionDeltaPayload, EmotionUpdatePayload, ToolActivityPayload, LifeProposalPayload, FocusCommandPayload
from shared.config_loader import get_config_val
from services.cognitive.providers.factory import ProviderFactory
from services.cognitive.tool_registry import ToolRegistry
from services.cognitive.prompt_builder import PromptBuilder, log_raw_trace
from services.cognitive.tools.validation import is_safe_media_filename
from services.cognitive.tools.web_search_tool import strip_untrusted_envelope
from shared.web_search_config import get_web_search_config, is_web_search_available
from shared.web_search_persona import is_persona_web_search_enabled, render_web_search_activity_label
from shared.life_data_permissions import is_tool_visible as is_life_tool_visible
from shared.persona_loader import PersonaLoader
from services.cognitive.tools.tothestars_tool import (
    PROPOSAL_STATUS,
    apply_life_proposal_edits,
    execute_proposal,
    render_proposal_activity_label,
)
from services.cognitive.tools.focus_tool import (
    clamp_focus_minutes,
    format_focus_datetime,
    record_focus_session,
)
from services.cognitive.mcp.presenter_manager import PresenterSessionManager

logger = logging.getLogger("cognitive_engine")


def _web_search_tool_visible(calls_this_turn: int) -> bool:
    """web_search 这一轮是否该出现在「给模型看的工具表」里。

    每轮重新求值，所以后台改开关 / 填 Key 之后无需重启即刻生效。
    `max_calls_per_turn` 用完后也一并摘掉，避免模型在单轮里反复搜索刷成本。
    注意判定用 is_web_search_available()（开关 **且** 有 Key），不是
    is_web_search_enabled() —— 否则模型会看到一个必然失败的工具并反复重试。
    """
    if not is_web_search_available():
        return False
    # 角色卡级开关（Layer 2）：这个人设是不是"能上网的世界"里的人。
    # 缺省 True（跟随全局开关），所以角色卡没写过该字段时行为不变。
    # PersonaLoader 带进程级缓存，这里每轮调用是纯内存操作。
    if not is_persona_web_search_enabled(PersonaLoader.load_active_persona()):
        return False
    try:
        limit = int(get_web_search_config().get("max_calls_per_turn") or 1)
    except (TypeError, ValueError):
        limit = 1
    return calls_this_turn < max(1, limit)


# ---------------------------------------------------------------------------
# 向着星写入确认协议：用户确实只说了"同意/取消"才算数；其他内容一律按"没回应"
# 处理，提议作废（安全默认），避免把"好烦啊""不用管我"这类话误判成确认。
# 提议本身只登记在引擎内存里、带 TTL，重启即丢，绝不落盘。
# ---------------------------------------------------------------------------

LIFE_PROPOSAL_TTL_SECONDS = 600

# 同一轮里最多保留多少条待确认提议（超出时丢弃最老的）。多条提议会按生成
# 顺序在屏幕上排队，用户逐条点确认/取消。
LIFE_MAX_PENDING_PROPOSALS = 5

# 前端流水线会给每条消息加时间戳前缀（如 "[2026-09-12 18:22] 好"）——确认词
# 判定与哨兵解析都必须先剥掉它，否则"好"永远匹配不上：这是线上"反复说好也不
# 生效"的根因（提议被静默作废，模型只能一遍遍重新提议）。
_LIFE_LEADING_BRACKETS_RE = re.compile(r"^\s*(?:\[[^\]]{0,64}\]\s*)+")
LIFE_DECISION_PREFIX = "【确认框】"


def _strip_leading_brackets(text: str) -> str:
    return _LIFE_LEADING_BRACKETS_RE.sub("", str(text or "")).strip()


def parse_life_decision(text: str) -> Optional[Dict[str, Any]]:
    """解析前端确认框发来的决策哨兵。

    格式：`【确认框】{"v":1,"id":"<proposal_id>","action":"confirm"|"cancel","edits":{...}}`
    时间戳前缀先剥掉；解析失败返回 None（按"没回应"处理，绝不猜测）。
    """
    raw = _strip_leading_brackets(text)
    if not raw.startswith(LIFE_DECISION_PREFIX):
        return None
    try:
        data = json.loads(raw[len(LIFE_DECISION_PREFIX):].strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    action = str(data.get("action") or "")
    proposal_id = str(data.get("id") or "").strip()
    if action not in ("confirm", "cancel") or not proposal_id:
        return None
    edits = data.get("edits")
    if not isinstance(edits, dict):
        edits = {}
    return {"id": proposal_id, "action": action, "edits": edits}

_LIFE_CONFIRM_PHRASES = {
    "好", "好的", "好呀", "可以", "行", "没问题", "确认", "确认一下", "就这样",
    "就这么办", "听你的", "嗯", "嗯嗯", "对", "是的", "是", "ok", "okay", "yes",
    "执行", "照做", "去吧", "去", "写", "加", "来吧",
}
_LIFE_CANCEL_PHRASES = {
    "取消", "算了", "不用", "先不", "先不要", "不要", "别", "别了", "不写", "不加",
    "不去了", "no", "不了",
}
_LIFE_POLITE_SUFFIXES = ("谢谢", "谢谢你", "了", "吧", "呀", "哦", "啊", "呢", "哟", "哈", "啦")


def _strip_polite_suffixes(text: str) -> str:
    changed = True
    while changed and text:
        changed = False
        for suffix in _LIFE_POLITE_SUFFIXES:
            if len(text) > len(suffix) and text.endswith(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


FOCUS_CONTROL_PREFIX = "【专注】"


def parse_focus_control(text: str) -> Optional[Dict[str, Any]]:
    """解析前端专注挂件发来的控制哨兵。

    格式：`【专注】{"v":1,"action":"pause"|"resume"|"abandon"|"finish", ...}`
    finish 可带 category / description / planned_minutes（引擎缓存的 state 优先）。
    时间戳前缀先剥掉；解析失败返回 None（按普通消息处理）。
    """
    raw = _strip_leading_brackets(text)
    if not raw.startswith(FOCUS_CONTROL_PREFIX):
        return None
    try:
        data = json.loads(raw[len(FOCUS_CONTROL_PREFIX):].strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    action = str(data.get("action") or "")
    if action not in ("pause", "resume", "abandon", "finish"):
        return None
    return {
        "action": action,
        "category": str(data.get("category") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "planned_minutes": data.get("planned_minutes"),
    }


def detect_life_action_confirmation(text: str) -> Optional[bool]:
    """判断用户消息是对写入提议的确认(True)/取消(False)/无回应(None)。

    只认短而明确的整句（"好的""可以""取消吧"……）；长句、疑问、新指令
    一律返回 None —— 提议按安全默认作废，模型需要的话会重新提议。
    """
    normalized = re.sub(r"[\s，。！!？?~～、,.…]+", "", _strip_leading_brackets(text))
    if not normalized or len(normalized) > 12:
        return None
    lookup = normalized.lower()
    stripped = _strip_polite_suffixes(normalized).lower()
    if lookup in _LIFE_CANCEL_PHRASES or stripped in _LIFE_CANCEL_PHRASES:
        return False
    if lookup in _LIFE_CONFIRM_PHRASES or stripped in _LIFE_CONFIRM_PHRASES:
        return True
    return None


def parse_thought_and_clean_text(raw_text: str) -> Tuple[str, str]:
    if not raw_text:
        return "", ""

    thought = ""
    match = re.search(r"<(?:thought|think)>(.*?)</(?:thought|think)>", raw_text, re.DOTALL)
    if match:
        thought = match.group(1).strip()
        clean_text = re.sub(r"<(?:thought|think)>.*?</(?:thought|think)>", "", raw_text, flags=re.DOTALL).strip()
    else:
        clean_text = raw_text.strip()

    # 1. Strip ReAct / JSON action and tool blocks
    clean_text = re.sub(r"\{\s*\"action\"\s*:\s*\"[^\"]+\".*?\}", "", clean_text, flags=re.DOTALL)
    clean_text = re.sub(r"\{\s*\"(action_type|action|sticker_id|prompt)\"[\s\S]*?\}", "", clean_text)
    
    # 2. Strip Python pseudocode calls like print(telegram_action(...)) or print(...)
    clean_text = re.sub(r"print\s*\(\s*(?:telegram_action|generate_image|generate_tts_speech)[\s\S]*?\)", "", clean_text)
    clean_text = re.sub(r"print\s*\([^)]*\)", "", clean_text)

    # 3. Strip stray XML function calling tags like </function_call>, <function_call>, </function_c etc.
    clean_text = re.sub(r"</?function_call[^>]*>", "", clean_text)
    clean_text = re.sub(r"</?function_c[^>]*>", "", clean_text)
    clean_text = re.sub(r"</?[a-zA-Z0-9_]+_action[^>]*>", "", clean_text)

    # 4. Strip stray protocol tags
    clean_text = re.sub(r"\[(?:emotion|action):[^\]]+\]", "", clean_text)

    return thought, clean_text.strip()


def clean_action_descriptions(text: str) -> str:
    """
    Zero Hardcoding Structural Protection Algorithm:
    1. Mask Markdown Links: [title](url) -> __MD_LINK_X__
    2. Mask Numbered/Bullet Lists: (1), (a), [1], (一) -> __NUM_LIST_X__
    3. Universal Clean: Strip remaining action/gesture parens (（...）, (...), 【...】, [...], *...*)
    4. Restore Placeholders
    """
    if not text:
        return ""
    placeholders = {}

    def mask_md_link(match):
        key = f"__MD_LINK_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    masked = re.sub(r"\[[^\]]+\]\([^\)]+\)", mask_md_link, text)

    def mask_num_list(match):
        key = f"__NUM_LIST_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    masked = re.sub(r"[\(\（\[【]\s*([0-9a-zA-Z一二三四五六七八九十]+)\s*[\)\）\]】]", mask_num_list, masked)

    # Clean remaining stage directions / action descriptions
    cleaned = re.sub(r"（[^）]*）", "", masked)
    cleaned = re.sub(r"\([^\)]*\)", "", cleaned)
    cleaned = re.sub(r"【[^】]*】", "", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\*[^\*]*\*", "", cleaned)

    for key, original in placeholders.items():
        cleaned = cleaned.replace(key, original)

    return cleaned.strip()


def parse_emotion_delta_from_text(text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Parses [EMOTION_DELTA: ...] from text tail and returns (clean_text, delta_dict).
    Example tag: [EMOTION_DELTA: d_valence=+0.1, d_arousal=0.0, d_affection=+0.5, is_jealous=false]
    """
    if not text:
        return text, None

    pattern = r"\[EMOTION_DELTA:\s*(.*?)\]"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return text, None

    raw_delta_str = match.group(1)
    clean_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    delta_data = {
        "delta_valence": 0.0,
        "delta_arousal": 0.0,
        "delta_affection": 0.0,
        "is_jealous": False,
    }

    pairs = re.findall(r"(d_valence|d_arousal|d_affection|valence|arousal|affection|is_jealous)\s*=\s*([^\s,]+)", raw_delta_str, re.IGNORECASE)
    for k, v in pairs:
        k_lower = k.lower()
        if "valence" in k_lower:
            try:
                delta_data["delta_valence"] = float(v)
            except ValueError:
                pass
        elif "arousal" in k_lower:
            try:
                delta_data["delta_arousal"] = float(v)
            except ValueError:
                pass
        elif "affection" in k_lower:
            try:
                delta_data["delta_affection"] = float(v)
            except ValueError:
                pass
        elif "jealous" in k_lower:
            delta_data["is_jealous"] = v.lower() in ("true", "1", "yes")

    return clean_text, delta_data


# Discrete performance tags: [emotion:happy] / [act:happy] / 【心情:happy】.
#
# Unlike [EMOTION_DELTA: ...] (which nudges the slow VAD mood state), these are
# one-shot stage directions: the renderer maps the value to a gesture motion, so
# it has to be one of the names in the frontend's fixed Emotion vocabulary. Every
# bracketed block is stripped out of the spoken text by clean_action_descriptions
# below, so the tag is never read aloud -- it only has to be *captured* before
# that stripping happens.
_ACT_TAG_PATTERN = re.compile(
    r"[\[【]\s*(?:emotion|emotions|心情|act)\s*[:：]\s*([A-Za-z_]+)\s*[\]】]",
    re.IGNORECASE,
)

# Model-facing synonyms folded onto the canonical names shared with
# frontend/packages/stage-ui-mmd/src/constants/emotions.ts. Anything not listed
# here is dropped, so a stray [emotion:...] from some other convention can never
# reach the renderer and be mistaken for a motion name.
_ACT_EMOTION_ALIASES = {
    "happy": "happy", "joy": "happy", "joyful": "happy", "glad": "happy",
    "excited": "happy", "proud": "happy", "smile": "happy", "smug": "happy",
    "sad": "sad", "unhappy": "sad", "down": "sad", "depressed": "sad",
    "sorrow": "sad", "lonely": "sad", "disappointed": "sad",
    "angry": "angry", "mad": "angry", "furious": "angry", "annoyed": "angry",
    "upset": "angry", "pout": "angry",
    "think": "think", "thinking": "think", "thoughtful": "think",
    "surprised": "surprised", "surprise": "surprised", "shocked": "surprised",
    "startled": "surprised",
    "awkward": "awkward", "shy": "awkward", "embarrassed": "awkward",
    "flustered": "awkward", "sheepish": "awkward",
    "question": "question", "confused": "question", "puzzled": "question",
    "doubt": "question",
    "curious": "curious", "curiosity": "curious", "interested": "curious",
    "neutral": "neutral", "calm": "neutral", "normal": "neutral", "idle": "neutral",
}


def parse_act_emotion_from_text(text: str) -> Optional[str]:
    """Returns the last canonical emotion named by a performance tag, else None."""
    if not text:
        return None
    for raw in reversed(_ACT_TAG_PATTERN.findall(text)):
        canonical = _ACT_EMOTION_ALIASES.get(raw.strip().lower())
        if canonical:
            return canonical
    return None


class SentenceSegmenter:
    """
    Sentence-level punctuation segmenter with <think>/<thought> & JSON streaming barrier FSM.
    Prevents mental thoughts (<think>...</think>, <thought>...</thought>), JSON tool calls, and action descriptions from leaking to TTS/NATS!
    """

    PUNCTUATIONS = set(["。", "！", "？", "~", "\n", "；", "，", ".", "!", "?", ";", ","])

    def __init__(self):
        self.buffer = ""
        self.in_thought = False
        self.last_emotion_delta: Optional[Dict[str, Any]] = None
        self.last_act_emotion: Optional[str] = None

    def push(self, delta: str) -> List[str]:
        if not delta:
            return []

        self.buffer += delta

        # Parse and strip emotion delta if fully closed in buffer
        if "[EMOTION_DELTA:" in self.buffer.upper():
            self.buffer, delta_data = parse_emotion_delta_from_text(self.buffer)
            if delta_data:
                self.last_emotion_delta = delta_data

        # Capture (not remove) any performance tag before
        # clean_action_descriptions() strips every [...] block further down.
        # Scanning the cumulative buffer means a tag split across two deltas
        # is still seen once its closing bracket arrives.
        act_emotion = parse_act_emotion_from_text(self.buffer)
        if act_emotion:
            self.last_act_emotion = act_emotion

        # 1. Thought / Think Tag Streaming Barrier FSM
        if "<think>" in self.buffer or "<thought>" in self.buffer:
            self.in_thought = True

        if self.in_thought:
            if "</think>" in self.buffer:
                self.buffer = re.sub(r"[\s\S]*?</think>", "", self.buffer).lstrip()
                self.in_thought = False
            elif "</thought>" in self.buffer:
                self.buffer = re.sub(r"[\s\S]*?</thought>", "", self.buffer).lstrip()
                self.in_thought = False
            else:
                # Still inside thinking block, suppress streaming output
                return []

        # 2. JSON Code Block Barrier Check
        if "```" in self.buffer or re.search(r'\{\s*"\w+"', self.buffer):
            if "}" in self.buffer or "```" in self.buffer:
                self.buffer = re.sub(r"```(?:json)?[\s\S]*?```", "", self.buffer)
                self.buffer = re.sub(r"\{\s*\"[^\"]+\"[\s\S]*?\}", "", self.buffer).lstrip()

        # 3. Clean fully closed action descriptions from buffer
        self.buffer = clean_action_descriptions(self.buffer)

        # 4. Unclosed Action Parenthesis Barrier Check
        # Action tags like (摸摸头) or [伸懒腰] are short (<20 chars) without sentence-ending punctuation.
        # If text after unclosed paren contains sentence punctuation (。, ！, ？, \n) or exceeds 20 chars,
        # treat it as normal text so real-time streaming output is never stalled!
        def _is_short_unclosed(open_p: str, close_p: str) -> bool:
            if open_p in self.buffer and close_p not in self.buffer:
                idx = self.buffer.rfind(open_p)
                tail = self.buffer[idx:]
                # Special case for EMOTION_DELTA metadata tag: hold buffer until fully closed with ]
                if "[EMOTION" in tail.upper():
                    return True
                if len(tail) > 20 or any(p in tail for p in ("。", "！", "？", "\n")):
                    return False
                return True
            return False

        has_unclosed_paren = (
            _is_short_unclosed("（", "）") or
            _is_short_unclosed("(", ")") or
            _is_short_unclosed("【", "】") or
            _is_short_unclosed("[", "]") or
            (self.buffer.count("`") % 2 == 1 and len(self.buffer) - self.buffer.rfind("`") <= 30)
        )
        if has_unclosed_paren:
            return []

        # 4.5 Sanitize multi-dot ellipses in buffer before slicing (e.g. '......', '...', '…')
        self.buffer = re.sub(r"\.{2,}", "，", self.buffer)
        self.buffer = re.sub(r"…+", "，", self.buffer)

        # 5. Sentence Punctuation Slicing for User-Facing Text
        sentences = []
        idx = 0
        for i, char in enumerate(self.buffer):
            if char in self.PUNCTUATIONS:
                if char == "." and i > 0 and self.buffer[i - 1].isalnum() and (
                    i + 1 >= len(self.buffer) or self.buffer[i + 1].isalnum()
                ):
                    continue

                chunk = self.buffer[idx:i + 1].strip()
                if char in (",", "，") and len(chunk) < 15:
                    continue
                raw_sentence = chunk
                if raw_sentence:
                    sentence = re.sub(r"</?(?:thought|think)>", "", raw_sentence).strip()
                    sentence = clean_action_descriptions(sentence)
                    if sentence:
                        sentences.append(sentence)
                idx = i + 1

        if idx > 0:
            self.buffer = self.buffer[idx:]

        return sentences

    def flush(self) -> List[str]:
        """Flushes remaining text in buffer upon stream completion."""
        if self.in_thought:
            return []

        act_emotion = parse_act_emotion_from_text(self.buffer)
        if act_emotion:
            self.last_act_emotion = act_emotion

        cleaned = self.buffer
        if "</think>" in cleaned:
            cleaned = re.sub(r"[\s\S]*?</think>", "", cleaned)
        if "</thought>" in cleaned:
            cleaned = re.sub(r"[\s\S]*?</thought>", "", cleaned)
        cleaned = re.sub(r"```(?:json)?[\s\S]*?```", "", cleaned)
        cleaned = re.sub(r"\{\s*\"[^\"]+\"[\s\S]*?\}", "", cleaned).strip()
        cleaned = re.sub(r"</?(?:thought|think)>", "", cleaned).strip()

        cleaned, delta_data = parse_emotion_delta_from_text(cleaned)
        if delta_data:
            self.last_emotion_delta = delta_data

        cleaned = clean_action_descriptions(cleaned)

        self.buffer = ""
        return [cleaned] if cleaned else []


class CognitiveEngine:

    # Bounds the "call tool -> feed result back -> generate again" loop in
    # stream_reasoning_loop so a tool-happy model can't spin forever.
    MAX_TOOL_ROUNDS = int(get_config_val("llm.max_tool_rounds", 8))

    # Higher budget for trigger_type == "game_turn" -- a single combat turn
    # can legitimately need many sts2_play_card/sts2_end_turn round trips in
    # a row. Raising this does NOT increase watchdog-trip risk: every round
    # already emits a heartbeat chunk unconditionally (see the comment
    # further down where it's yielded), which keeps re-arming Go's sliding
    # 30s StreamingTTS watchdog regardless of total round count -- it only
    # affects worst-case total wall-clock time for one turn, which is fine
    # since no synchronous human is blocking on a game turn the way they are
    # on a chat reply.
    MAX_GAME_TOOL_ROUNDS = int(get_config_val("game_watcher.sts2.max_tool_rounds", 20))

    # STS2 tools whose index argument shifts as earlier same-type actions in
    # the same batch execute (AGENTS.md's "play/claim right-to-left, highest
    # index first" rule). Letting the model batch several of these into one
    # response (see prompt_builder.py's game_turn guidance) only saves real
    # round trips if batching is actually SAFE regardless of what order the
    # model happened to list them in -- see _reorder_index_shifting_calls.
    STS2_INDEX_SHIFT_FIELDS = {
        "sts2_play_card": "card_index",
        "play_card": "card_index",
        "sts2_claim_reward": "index",
        "claim_reward": "index",
        "sts2_select_card_reward": "card_index",
        "select_card_reward": "card_index",
    }

    STS2_TURN_TERMINATING_TOOLS = {
        "sts2_end_turn", "end_turn",
        "sts2_choose_map_node", "choose_map_node",
    }

    def __init__(self, default_provider_name: Optional[str] = None):
        self.presenter_manager = PresenterSessionManager(
            server_commands=self._load_presenter_server_commands(),
            idle_timeout_seconds=get_config_val("mcp.presenter.idle_timeout_seconds", 600),
        )
        self.tool_registry = ToolRegistry(presenter_manager=self.presenter_manager)
        self._resolve_default_provider(default_provider_name)
        self.latest_vision_frames: Dict[int, Dict[str, Any]] = {}
        # chat_id -> {"proposal": {...}, "created_at": ts}。写入提议只在内存里
        # 等一次用户回应：确认才执行，取消/超时/答非所问一律作废。
        self._pending_life_actions: Dict[int, Dict[str, Any]] = {}
        # chat_id -> 最近一次 agent.focus.state 广播（Go 的 FocusManager 是计时
        # 唯一真源；这里只缓存用于提示词注入与完成结算，重启后由心跳广播补齐）。
        self._focus_states: Dict[int, Dict[str, Any]] = {}

    def refresh_default_provider(self, default_provider_name: Optional[str] = None) -> None:
        """Re-resolve the default LLM provider from current config.

        Call after ProviderFactory.invalidate_cache() (e.g. on
        agent.config.reloaded) so a BYOK API key / default provider change
        made in the admin panel takes effect without restarting this
        service -- self.default_provider is otherwise only ever resolved
        once, at __init__.
        """
        self._resolve_default_provider(default_provider_name)

    def _resolve_default_provider(self, default_provider_name: Optional[str] = None) -> None:
        if not default_provider_name:
            default_provider_name = get_config_val("llm.default_provider", "gemini")
        self.default_provider = ProviderFactory.get_provider(default_provider_name)
        self.providers = {
            default_provider_name: self.default_provider,
        }

    @staticmethod
    def _load_presenter_server_commands() -> Dict[str, List[str]]:
        import sys
        commands: Dict[str, List[str]] = {}
        for target in ("ppt", "vscode"):
            cmd = get_config_val(f"mcp.presenter.{target}.command")
            if cmd:
                cmd_list = list(cmd)
                if cmd_list and cmd_list[0] in ("python", "python3"):
                    cmd_list[0] = sys.executable
                commands[target] = cmd_list
        return commands

    def update_vision_frame(self, chat_id: int, image_base64: str, source_type: str = "screen", format: str = "jpeg"):
        self.latest_vision_frames[chat_id] = {
            "image_base64": image_base64,
            "source_type": source_type,
            "format": format,
            "timestamp": time.time(),
        }

    def get_valid_vision_frame(self, chat_id: int) -> Optional[Dict[str, Any]]:
        frame = self.latest_vision_frames.get(chat_id)
        if not frame:
            return None
        # TTL check: 30 seconds max to prevent stale zombie frames & privacy leaks
        if time.time() - frame.get("timestamp", 0) > 30.0:
            logger.info(f"⏳ Vision frame for chat_id={chat_id} expired (>30s TTL), purging stale frame.")
            del self.latest_vision_frames[chat_id]
            return None
        return frame

    @staticmethod
    def _build_local_tool_action(
        tool_name: str,
        tool_output: Dict[str, Any],
        payload: ReasoningRequestPayload,
        gen_id: int,
        src_channel: str,
    ) -> Optional[ActionDecisionPayload]:
        """
        Maps a *fire-and-forget* local embodiment tool's output onto a
        structured ActionDecisionPayload. Only TTS/image/telegram_action live
        here -- they don't need their result shown back to the model, so no
        round trip is required (the model's own text from this same
        generation round is used as the accompanying message). Returns None
        for anything else (e.g. presenter_mode, MCP tools), signalling the
        caller that this call instead needs the round-trip path.
        """
        if tool_name == "generate_tts_speech":
            return ActionDecisionPayload(
                event_id=payload.event_id,
                source_component="cognitive_engine",
                chat_id=payload.chat_id,
                generation_id=gen_id,
                source_channel=src_channel,
                action_type="send_voice",
                voice_path=tool_output.get("voice_path"),
                text_content=tool_output.get("text"),
                media_type="voice",
                chat_action="record_audio",
            )
        if tool_name == "generate_image":
            return ActionDecisionPayload(
                event_id=payload.event_id,
                source_component="cognitive_engine",
                chat_id=payload.chat_id,
                generation_id=gen_id,
                source_channel=src_channel,
                action_type="send_photo",
                photo_path=tool_output.get("photo_path"),
                text_content=None,  # Caption will come from LLM text response below
                media_type="photo",
            )
        if tool_name == "telegram_action":
            return ActionDecisionPayload(
                event_id=payload.event_id,
                source_component="cognitive_engine",
                chat_id=payload.chat_id,
                generation_id=gen_id,
                source_channel=src_channel,
                action_type=tool_output.get("action_type", "send_message"),
                sticker_id=tool_output.get("sticker_id"),
                reaction_emoji=tool_output.get("reaction_emoji"),
            )
        if tool_name == "query_companion_stats":
            # 读类工具：直接把结果作为最终答复发给用户，不 round-trip，
            # 这样不依赖 provider 的 round-trip 格式（qwen/Gemini 都适用）。
            return ActionDecisionPayload(
                event_id=payload.event_id,
                source_component="cognitive_engine",
                chat_id=payload.chat_id,
                generation_id=gen_id,
                source_channel=src_channel,
                action_type="send_message",
                text_content=tool_output.get("answer") or tool_output.get("message") or "查询完成",
                is_final=True,
            )
        if tool_name == "get_recommendations":
            recs = tool_output.get("recommendations") or []
            text = "\n".join(f"· {r}" for r in recs) if recs else "暂时没有特别的推荐喵～"
            return ActionDecisionPayload(
                event_id=payload.event_id,
                source_component="cognitive_engine",
                chat_id=payload.chat_id,
                generation_id=gen_id,
                source_channel=src_channel,
                action_type="send_message",
                text_content=text,
                is_final=True,
            )
        return None

    @classmethod
    def _reorder_index_shifting_calls(cls, pending_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        A batched round of tool calls (e.g. several sts2_play_card calls
        requested in one LLM response, see prompt_builder.py's game_turn
        guidance encouraging exactly this) is only safe to execute as-given
        if the model's card_index/index values were all computed against the
        SAME pre-batch snapshot -- but playing/claiming index N shifts every
        higher index left for whatever comes after it (AGENTS.md's own
        warning). Re-sorting each STS2_INDEX_SHIFT_FIELDS tool's calls into
        descending-index order removes the model's need to reason about that
        ordering itself, which is what actually makes batching worthwhile:
        without this, a naive batch would need to fall back to one call at a
        time anyway to stay correct, defeating the round-trip savings.

        Preserves the original list's interleaving: each STS2_INDEX_SHIFT_FIELDS
        tool's calls are reordered only among themselves and reinserted at the
        same slots they originally occupied, so a non-index-shifting call
        (e.g. sts2_use_potion) sitting between two play_card calls keeps its
        original relative position. Calls to other tools are untouched.
        """
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for call in pending_calls:
            name = call.get("name")
            if name in cls.STS2_INDEX_SHIFT_FIELDS:
                buckets.setdefault(name, []).append(call)

        for name, field in cls.STS2_INDEX_SHIFT_FIELDS.items():
            bucket = buckets.get(name)
            if bucket and len(bucket) > 1:
                bucket.sort(key=lambda c: (c.get("args") or {}).get(field) or 0, reverse=True)

        cursor = {name: 0 for name in buckets}
        reordered = []
        for call in pending_calls:
            name = call.get("name")
            if name in buckets:
                reordered.append(buckets[name][cursor[name]])
                cursor[name] += 1
            else:
                reordered.append(call)
        return reordered

    @staticmethod
    def _append_tool_round_trip(
        messages: List[Dict[str, Any]],
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_output: Dict[str, Any],
        thought_signature: Optional[bytes] = None,
        reasoning_content: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Appends a (function_call, function_response) turn pair so the next
        generate_stream() round shows the model what the tool actually
        returned, instead of it improvising -- this is what makes
        ppt_get_slide_text-style read tools ground the model's narration in
        real content. See GeminiProvider._messages_to_contents.
        """
        messages = list(messages)
        fc_meta: Dict[str, Any] = {"name": tool_name, "args": tool_args}
        if thought_signature:
            fc_meta["thought_signature"] = thought_signature
        model_meta: Dict[str, Any] = {"function_call": fc_meta}
        # DeepSeek thinking 模式：请求带 tools 时，带 tool_calls 的 assistant 消息
        # 必须把这轮的思考过程一并回传，否则下一轮 HTTP 400。放在 metadata 的兄弟
        # 键上（而不是塞进 fc_meta），因为 fc_meta 是"这次调用"的描述，而
        # reasoning 属于"这条消息"。OpenAIProvider._build_messages 读的就是这里。
        if reasoning_content:
            model_meta["reasoning_content"] = reasoning_content
        messages.append({
            "role": "model",
            "content": "",
            "metadata": model_meta,
        })
        messages.append({
            "role": "user",
            "content": "",
            "metadata": {"function_response": {"name": tool_name, "response": tool_output}},
        })
        return messages

    def _unknown_tool_error(self, chat_id: int, tool_name: str) -> Dict[str, Any]:
        """
        Builds the round-trip error payload for a tool name that matched
        neither the local ToolRegistry nor an active presenter session.

        This is the LLM's *only* recovery signal for two very different
        situations: it hallucinated a plausible-but-wrong name for a real
        presenter tool (e.g. "vscode_search_content" instead of
        "vscode_search"), or it tried to use a presenter tool before ever
        calling presenter_mode(activate). A bare "unknown tool" string gives
        it nothing to act on and the model tends to narrate the failure to
        the user instead of self-correcting -- so tell it explicitly what IS
        available (or how to make something available) in the same turn.
        """
        active_names = [s["name"] for s in self.presenter_manager.get_active_tool_schemas(chat_id)]
        if active_names:
            detail = (
                f"unknown tool '{tool_name}'. It does not exist -- do not retry it. "
                f"Tools currently available in this session: {', '.join(active_names)}."
            )
        else:
            detail = (
                f"unknown tool '{tool_name}'. No presenter session is active for this chat, so no "
                "ppt_*/vscode_* tool exists yet. Call presenter_mode(action='activate', "
                "target='ppt' or 'vscode', root_path=<deck or workspace directory>) first, then retry "
                "using one of the tool names it reports as available."
            )
        return {"error": True, "detail": detail}

    # ---------- 向着星写入确认协议 ----------

    @staticmethod
    def _is_proposal_tool(tool_name: str) -> bool:
        """写入/开始类提议工具：只登记待确认，绝不在工具调用里直接执行。

        既包含向着星写提议，也包含专注模式（番茄钟）的启动提议 —— 后者的
        "执行"不是数据库写入，而是把确认结果转成 FocusCommandPayload。
        """
        return tool_name.startswith("tothestars_propose_") or tool_name == "focus_propose_session"

    def _pending_queue(self, chat_id: int, create: bool = False) -> List[Dict[str, Any]]:
        """当前 chat 的待确认提议队列（按生成顺序，队首 = 弹窗当前显示的那条）。

        结构：``{chat_id: [{"proposal": {...}, "created_at": ts}, ...]}``。
        兼容旧版单条 dict（若测试或旧状态直接注入了 dict，会在读取时包成队列）。
        """
        pending_map = getattr(self, "_pending_life_actions", None)
        if pending_map is None:
            # 兼容测试里的 object.__new__ 构造（不跑 __init__）。
            pending_map = self._pending_life_actions = {}
        raw = pending_map.get(chat_id)
        if raw is None:
            if not create:
                return []
            raw = []
            pending_map[chat_id] = raw
        elif isinstance(raw, dict):
            raw = [raw]
            pending_map[chat_id] = raw
        return raw

    def _store_pending_queue(self, chat_id: int, queue: List[Dict[str, Any]]) -> None:
        pending_map = getattr(self, "_pending_life_actions", None)
        if pending_map is None:
            pending_map = self._pending_life_actions = {}
        if queue:
            pending_map[chat_id] = queue
        else:
            pending_map.pop(chat_id, None)

    def _capture_life_proposal(self, payload: ReasoningRequestPayload, tool_output: Dict[str, Any]):
        """提议工具的输出进不了执行：只登记待确认状态 + 返回前端确认框事件。

        返回 (给模型看的工具结果, LifeProposalPayload 事件)；非提议输出返回 None。
        模型看到的仍是"等待确认"；真正的确认由前端确认框（或语音/打字兜底）完成，
        真正的写入只发生在 _settle_pending_life_action。
        """
        if not isinstance(tool_output, dict) or tool_output.get("status") != PROPOSAL_STATUS:
            return None
        proposal = dict(tool_output.get("proposal") or {})
        proposal["id"] = uuid.uuid4().hex[:12]
        queue = self._pending_queue(payload.chat_id, create=True)
        queue.append({
            "proposal": proposal,
            "created_at": time.time(),
        })
        if len(queue) > LIFE_MAX_PENDING_PROPOSALS:
            dropped = queue.pop(0)
            logger.warning(
                f"⚠️ [写入确认] chat_id={payload.chat_id} 待确认提议超过 {LIFE_MAX_PENDING_PROPOSALS} 条，"
                f"最老的一条 #{((dropped.get('proposal') or {}).get('id') or '?')} 被丢弃"
            )
        logger.info(
            f"📝 [写入确认] chat_id={payload.chat_id} 生成提议 #{proposal['id']}: "
            f"{proposal.get('summary')!r}（未执行，等待确认框；当前待确认 {len(queue)} 条）"
        )
        return (
            {
                "status": "awaiting_user_confirmation",
                "summary": proposal.get("summary") or "",
                "instruction": (
                    "提议已经生成，并已在对方的屏幕上弹出「需要确认」确认框"
                    "（对方可以在框里查看详情、手动改字段）。请用你自己的口吻一句话说清你要做什么，"
                    "并请对方在确认框里点「确认」或「取消」。不要再要求对方打字回复「好」。"
                    "如果本轮生成了多条提议，确认框会按顺序逐条弹出，请提醒对方逐条确认。"
                ),
            },
            self._life_proposal_event(payload.chat_id, proposal["id"], "pending", proposal),
        )

    @staticmethod
    def _life_proposal_event(
        chat_id: int,
        proposal_id: str,
        phase: str,
        proposal: Optional[Dict[str, Any]],
        message: str = "",
    ) -> LifeProposalPayload:
        proposal = proposal or {}
        return LifeProposalPayload(
            event_id=f"life-proposal-{proposal_id or 'unknown'}-{phase}",
            source_component="cognitive_engine",
            chat_id=chat_id,
            proposal_id=str(proposal_id or ""),
            phase=phase,
            kind=str(proposal.get("kind") or ""),
            params=proposal.get("params") or {},
            summary=str(proposal.get("summary") or ""),
            message=message,
        )

    async def _settle_pending_life_action(self, payload: ReasoningRequestPayload, messages: List[Dict[str, Any]]):
        """LLM 调用前结算待确认提议：确认则确定性执行，否则作废。

        两种确认来源：
        - 前端确认框按钮：哨兵文本（parse_life_decision），可携带手改字段；
        - 语音 / 打字："好"/"取消" 等短句兜底（时间戳前缀会被剥掉）。
        执行不经过模型决策（模型看不到任何写执行工具）；结果既以系统事件追加进
        messages（由模型说给用户听），也以 LifeProposalPayload 事件通知前端关闭
        或更新确认框。本方法是 async generator。
        """
        queue = self._pending_queue(payload.chat_id)
        if not queue:
            return
        if payload.trigger_type not in (None, "user_message"):
            # 主动/游戏回合不结算提议：原样保留，等下一次用户消息再处理。
            return

        # 先扫一遍超时项：每条独立作废并通知前端收起对应确认框。
        now = time.time()
        active: List[Dict[str, Any]] = []
        for entry in queue:
            proposal = entry.get("proposal") or {}
            if now - float(entry.get("created_at") or 0) > LIFE_PROPOSAL_TTL_SECONDS:
                yield self._life_proposal_event(
                    payload.chat_id, str(proposal.get("id") or ""), "expired", proposal, "提议已超时作废",
                )
            else:
                active.append(entry)
        self._store_pending_queue(payload.chat_id, active)
        queue = active
        if not queue:
            messages.append({"role": "user", "content": (
                "[系统事件] 待确认的写入提议已超时自动作废，没有产生任何修改。"
                "如果对方仍然需要，请重新生成提议。"
            )})
            return

        inbound_text = (
            payload.inbound_message.raw_text
            if payload.inbound_message and payload.inbound_message.raw_text
            else ""
        )

        sentinel = parse_life_decision(inbound_text)
        edits: Dict[str, Any] = {}
        if sentinel is not None:
            entry = next(
                (item for item in queue if str((item.get("proposal") or {}).get("id") or "") == sentinel["id"]),
                None,
            )
            if entry is None:
                # 点的是已失效 / 不属于当前队列的确认框：不执行，只通知前端关掉那张
                # 旧卡片；其余待确认提议原样保留。
                yield self._life_proposal_event(payload.chat_id, sentinel["id"], "expired", None, "这张确认框已经失效")
                return
            queue.remove(entry)
            self._store_pending_queue(payload.chat_id, queue)
            decision = sentinel["action"] == "confirm"
            edits = sentinel["edits"]
        else:
            decision_opt = detect_life_action_confirmation(inbound_text)
            if decision_opt is None:
                # 用户没在回应任何确认（可能在聊别的）：所有待确认按安全默认作废，
                # 并逐条关闭前端确认框。
                for entry in queue:
                    proposal = entry.get("proposal") or {}
                    yield self._life_proposal_event(
                        payload.chat_id, str(proposal.get("id") or ""), "expired", proposal,
                        "提议已作废，如需继续请再说一次",
                    )
                self._store_pending_queue(payload.chat_id, [])
                return
            decision = decision_opt
            # 文字「好 / 取消」有歧义：只作用于最早的一条（即弹窗当前显示的那条）。
            entry = queue.pop(0)
            self._store_pending_queue(payload.chat_id, queue)

        pending = entry
        proposal = pending.get("proposal") or {}
        proposal_id = str(proposal.get("id") or "")
        kind = str(proposal.get("kind") or "")

        if decision is False:
            logger.info(f"↩️ [写入确认] chat_id={payload.chat_id} 用户取消提议 #{proposal_id}")
            messages.append({"role": "user", "content": (
                "[系统事件] 对方刚刚取消了写入提议，没有产生任何修改。请自然回应，不要反复道歉或追问。"
            )})
            yield self._life_proposal_event(payload.chat_id, proposal_id, "cancelled", proposal, "已取消")
            return

        # 确认执行：先合并确认框里的手改字段（白名单 + 归一化；服务端仍会完整校验）。
        params = apply_life_proposal_edits(kind, proposal.get("params") or {}, edits)

        # 专注提议不是向着星写入：确认后转成确定性的 FocusCommandPayload，
        # 由 Go 的 FocusManager 起计时；完成结算在总结弹窗提交时才真正落库。
        if kind == "focus.start":
            minutes = clamp_focus_minutes((params or {}).get("minutes", 60))
            logger.info(f"🎯 [专注模式] chat_id={payload.chat_id} 用户已确认，启动 {minutes} 分钟番茄钟")
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方已在确认框点了「确认」，番茄钟已启动：专注 {minutes} 分钟。"
                "请用你自己的口吻一句话确认并简短鼓励，然后安静下来，不要再找新话题。"
            )})
            yield FocusCommandPayload(chat_id=payload.chat_id, action="start", minutes=minutes)
            yield self._life_proposal_event(
                payload.chat_id, proposal_id, "executed", proposal, f"已开始 {minutes} 分钟专注",
            )
            return

        logger.info(
            f"✅ [写入确认] chat_id={payload.chat_id} 用户已确认，开始执行 #{proposal_id}: {proposal.get('summary')!r}"
        )
        yield self._life_proposal_event(payload.chat_id, proposal_id, "executing", proposal, "正在执行…")
        yield ToolActivityPayload(
            event_id=payload.event_id,
            source_component="cognitive_engine",
            chat_id=payload.chat_id,
            tool=f"tothestars:{kind}",
            phase="start",
            label=render_proposal_activity_label(kind),
        )
        result = await execute_proposal(kind, params)
        yield ToolActivityPayload(
            event_id=payload.event_id,
            source_component="cognitive_engine",
            chat_id=payload.chat_id,
            tool=f"tothestars:{kind}",
            phase="done",
            label="",
        )
        if result.get("status") == "success":
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方已在确认框点了「确认」，写入已经真实执行成功：{result.get('message')}。"
                "请用你的口吻简短告知结果，不要再复述一遍提议。"
            )})
            yield self._life_proposal_event(
                payload.chat_id, proposal_id, "executed", proposal, str(result.get("message") or "执行成功"),
            )
        elif result.get("status") == "queued":
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方已确认，但向着星暂时没连上，这次写入已先暂存，之后会自动补交："
                f"{result.get('message')}。请用你的口吻简短说明「先替你记下了，恢复后自动补上」，"
                "不要说成失败，也不要让对方再操作一遍。"
            )})
            yield self._life_proposal_event(
                payload.chat_id, proposal_id, "executed", proposal, str(result.get("message") or "已暂存待补交"),
            )
        else:
            reason = result.get("error") or result.get("message") or "未知原因"
            logger.warning(f"❌ [写入确认] chat_id={payload.chat_id} 执行失败: {reason}")
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方已在确认框点了「确认」，但写入执行失败：{reason}。"
                "请如实告知对方这次没有写成功，不要假装完成。"
            )})
            yield self._life_proposal_event(payload.chat_id, proposal_id, "failed", proposal, str(reason))

    # ---------- 专注模式（番茄钟） ----------

    def update_focus_state(self, state: Dict[str, Any]) -> None:
        """缓存 Go 广播的 agent.focus.state（idle 时清除）。

        Go 的 FocusManager 是计时唯一真源；本缓存只服务于提示词注入与完成
        结算。认知服务重启后靠 Go 的周期心跳广播在数秒内补齐。
        """
        try:
            chat_id = int((state or {}).get("chat_id") or 0)
        except (TypeError, ValueError):
            return
        if not chat_id:
            return
        states = getattr(self, "_focus_states", None)
        if states is None:
            states = self._focus_states = {}
        if str(state.get("phase") or "") == "idle":
            states.pop(chat_id, None)
            return
        states[chat_id] = state

    def _focus_state_for(self, chat_id: int) -> Optional[Dict[str, Any]]:
        states = getattr(self, "_focus_states", None)
        if states is None:
            states = self._focus_states = {}
        return states.get(chat_id)

    def _focus_mode_hint(self, chat_id: int) -> Optional[str]:
        """专注中给模型的整轮行为约束：对无关话题表现出被打扰的反感。"""
        state = self._focus_state_for(chat_id)
        if not state:
            return None
        phase = str(state.get("phase") or "")
        if phase not in ("running", "paused"):
            return None
        remaining_minutes = max(0, int(state.get("remaining_seconds") or 0) // 60)
        timing = "（当前处于暂停中）" if phase == "paused" else f"（还剩约 {remaining_minutes} 分钟）"
        return (
            "[专注模式] 对方正在番茄钟专注中" + timing + "。只有对方主动开口时才回应：\n"
            "1. 与正在专注的事无关的闲聊、消遣、玩乐或额外请求：简短、明显不耐烦地表达反感与抗拒，"
            "可以责备两句提醒他/她回到专注，但不要辱骂、更不要顺着聊下去。\n"
            "2. 与专注内容相关、或真正要紧的事：照常回应，但要短，尽快让对方回到手头的事。\n"
            "3. 不要主动开启新话题，不要撒娇或拉长对话。"
        )

    async def _handle_focus_control(self, payload: ReasoningRequestPayload, messages: List[Dict[str, Any]]):
        """结算前端专注挂件的控制哨兵（暂停/继续/放弃/完成），async generator。

        控制动作不经过模型决策：确定性地转成 FocusCommandPayload 交给 Go 的
        FocusManager，结算结果作为系统事件注入，由模型用角色口吻说一句
        （暂停的谅解 / 放弃的失望 / 完成后的针对内容鼓励）。
        """
        inbound_text = (
            payload.inbound_message.raw_text
            if payload.inbound_message and payload.inbound_message.raw_text
            else ""
        )
        control = parse_focus_control(inbound_text)
        if control is None:
            return

        action = control["action"]
        chat_id = payload.chat_id
        state = self._focus_state_for(chat_id) or {}
        planned = 0
        try:
            planned = int(state.get("planned_minutes") or control.get("planned_minutes") or 0)
        except (TypeError, ValueError):
            planned = 0

        if action == "pause":
            yield FocusCommandPayload(chat_id=chat_id, action="pause")
            messages.append({"role": "user", "content": (
                "[系统事件] 对方刚刚暂停了番茄钟。可以简短回应一句（比如「歇口气也好」），"
                "但不要展开长聊，也别让他/她忘了回到专注。"
            )})
            return

        if action == "resume":
            remaining_minutes = max(0, int(state.get("remaining_seconds") or 0) // 60)
            yield FocusCommandPayload(chat_id=chat_id, action="resume")
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方结束暂停、回到了专注（还剩约 {remaining_minutes} 分钟）。"
                "简短打气一句即可，不要展开话题。"
            )})
            return

        if action == "abandon":
            remaining_seconds = max(0, int(state.get("remaining_seconds") or 0))
            done_minutes = max(0, planned - remaining_seconds // 60) if planned else 0
            yield FocusCommandPayload(chat_id=chat_id, action="end", outcome="abandoned")
            self.update_focus_state({"chat_id": chat_id, "phase": "idle"})
            detail = f"（原计划 {planned} 分钟，大约只坚持了 {done_minutes} 分钟）" if planned else ""
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方在半途结束了这次专注，半途而废{detail}。"
                "请表达明确的失望与一点责备——像对他/她有期待的人那样，1~2 句即可；"
                "不要辱骂、不要长篇说教，也不要假装无所谓。"
            )})
            return

        # action == "finish"：用户在总结弹窗里确认了内容，确定性写入向着星。
        category = control.get("category") or "未分类"
        description = control.get("description") or ""
        try:
            started_epoch = float(state.get("started_at_unix") or 0)
        except (TypeError, ValueError):
            started_epoch = 0.0

        yield FocusCommandPayload(chat_id=chat_id, action="end", outcome="completed")
        self.update_focus_state({"chat_id": chat_id, "phase": "idle"})

        if planned <= 0 or started_epoch <= 0:
            # 罕见：认知服务重启且心跳还没补齐状态，宁可不写、不编造时间。
            messages.append({"role": "user", "content": (
                "[系统事件] 对方提交了专注总结，但我这边丢失了这次专注的计时信息，没能记录。"
                "请如实道歉说明，并先肯定他/她坚持完成的事实，不要假装已经记上。"
            )})
            return

        duration_seconds = planned * 60
        result = await record_focus_session(
            started_at=format_focus_datetime(started_epoch),
            ended_at=format_focus_datetime(started_epoch + duration_seconds),
            planned_minutes=planned,
            duration_seconds=duration_seconds,
            category=category,
            description=description,
        )

        if result.get("status") == "success":
            done_text = f"「{description}」" if description else "（对方没有填写具体内容）"
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方提交了这次专注的总结：分类「{category}」，完成内容{done_text}；"
                f"本次专注 {planned} 分钟，今天累计专注约 {result.get('today_minutes', 0)} 分钟。"
                "请围绕这个具体内容给出具体、真诚的鼓励来为这次专注收尾（1~2 句），"
                "点出他/她完成的事；不要说空泛的「真棒」，也不要重新汇报数据。"
            )})
        elif result.get("status") == "queued":
            done_text = f"「{description}」" if description else ""
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方提交了这次专注的总结（分类「{category}」{done_text}），"
                "但向着星暂时没连上，记录已先暂存、之后会自动补交。"
                "请先围绕这个内容给出真诚的鼓励收尾，再顺口说明「记录我先收着，恢复后自动补上」，"
                "不要说成没记上，也不要让对方重新提交。"
            )})
        else:
            messages.append({"role": "user", "content": (
                f"[系统事件] 对方提交了专注总结，但写入向着星失败：{result.get('error')}。"
                "请如实告知这次没能记上，表达遗憾，但先肯定他/她真的专注了这么久。"
            )})

    async def execute_reasoning_loop(
            self, payload: ReasoningRequestPayload
    ) -> List[ActionDecisionPayload]:
        # Lazy Evaluation & Token Conservation: If triggered by routine TICK and no proactive flag, skip LLM call
        if payload.trigger_type == "tick" and not getattr(payload, "is_proactive_opportunity", False):
            logger.debug(f"Tick event for chat_id={payload.chat_id} skipped LLM reasoning (Lazy Evaluation Token Conservation)")
            return []

        # Fast-Path System Command Handlers
        inbound_text = (payload.inbound_message.raw_text.strip()
                        if payload.inbound_message and payload.inbound_message.raw_text
                        else "")

        # Resolve source_channel up front (same precedence as the main path
        # below) -- these fast-path replies bypass the main construction
        # block entirely, so without this they'd fall back to
        # ActionDecisionPayload's pydantic default ("telegram"), which is
        # wrong for a web user typing e.g. "/health" and gets the reply
        # silently dropped by every channel adapter's filter.
        fast_path_src_channel = payload.source_channel or (
            payload.inbound_message.source_channel
            if payload.inbound_message and getattr(payload.inbound_message, "source_channel", None)
            else "telegram"
        )

        cmd = inbound_text.lower()
        if cmd == "/ping":
            return [
                ActionDecisionPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    source_channel=fast_path_src_channel,
                    action_type="send_message",
                    text_content="pong 🏓 (BetterAgent 系统运行正常！)",
                    chat_action="typing",
                )
            ]
        elif cmd in ("/health", "/status"):
            history_len = len(payload.short_term_history)
            rag_count = len(payload.rag_facts)
            status_text = (
                f"📊 **BetterAgent 健康度指标**\n\n"
                f"• **系统状态**: 正常在线 🟢\n"
                f"• **触发模式**: {payload.trigger_type or 'user_message'}\n"
                f"• **短期记忆缓冲**: {history_len} 条\n"
                f"• **RAG 检索事实数**: {rag_count} 条\n"
                f"• **当前状态**: {payload.current_emotion or '正常'}\n"
            )
            return [
                ActionDecisionPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    source_channel=fast_path_src_channel,
                    action_type="send_message",
                    text_content=status_text,
                    chat_action="typing",
                )
            ]
        elif cmd == "/help":
            help_text = (
                "📋 **BetterAgent 指令与交互说明** 📋\n\n"
                "• `/ping` - 探针基础存活检测\n"
                "• `/health` 或 `/status` - 查看系统健康度与情绪参数\n"
                "• `/help` - 显示此帮助信息\n\n"
                "💡 **日常互动**: 直接发文字聊天、求抱抱、夸奖我，或者让我画图、发语音包~"
            )
            return [
                ActionDecisionPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    source_channel=fast_path_src_channel,
                    action_type="send_message",
                    text_content=help_text,
                    chat_action="typing",
                )
            ]

        # Already resolved above (fast_path_src_channel) using the same
        # precedence -- reuse it instead of recomputing.
        src_channel = fast_path_src_channel

        # Channel-Aware Tools: Filter schemas depending on channel (Exclude telegram_action on Web)
        all_schemas = self.tool_registry.get_all_schemas()
        if payload.trigger_type == "game_turn":
            all_schemas = all_schemas + self.tool_registry.get_game_schemas()

        allow_proactive_image = get_config_val("tools.image_gen.allow_proactive", False)
        tools_schema = []
        for t in all_schemas:
            t_name = t.get("name")
            if src_channel == "web" and t_name == "telegram_action":
                continue
            if payload.trigger_type == "proactive" and t_name == "generate_image" and not allow_proactive_image:
                continue
            if t_name == "web_search" and not _web_search_tool_visible(0):
                continue
            # 向着星工具族：按类别权限门控（hidden 类目 = 模型看不见该工具）。
            if not is_life_tool_visible(t_name):
                continue
            tools_schema.append(t)

        system_prompt = PromptBuilder.build_system_prompt(payload)
        messages = PromptBuilder.build_messages(payload)

        # 写入确认协议：结算上一轮遗留的待确认提议。非流式路径没有实时事件
        # 通道，执行结果只注入 messages（事件被直接丢弃）。
        async for _ in self._settle_pending_life_action(payload, messages):
            pass

        # Token Explosion Protection: Strip vision_frame metadata from ALL past history messages
        for msg in messages:
            if isinstance(msg.get("metadata"), dict) and "vision_frame" in msg["metadata"]:
                del msg["metadata"]["vision_frame"]

        # Attach latest Vision Frame ONLY to the last User message if within 30s TTL
        vision_frame = self.get_valid_vision_frame(payload.chat_id)
        if vision_frame and messages:
            if "metadata" not in messages[-1]:
                messages[-1]["metadata"] = {}
            messages[-1]["metadata"]["vision_frame"] = vision_frame
            logger.info(f"📷 Attached fresh Vision Frame ({vision_frame.get('source_type')}) to latest LLM message for chat_id={payload.chat_id}")

        # Run LLM reasoning
        result = await self.default_provider.generate(
            messages=messages,
            tools_schema=tools_schema,
            system_prompt=system_prompt,
        )

        actions: List[ActionDecisionPayload] = []
        tool_calls = result.get("tool_calls", [])
        raw_text = result.get("text", "")

        # Fallback: Parse embedded ReAct / JSON image/tool calls from text if native tool_calls is empty
        if not tool_calls:
            import json
            if '"action":' in raw_text and '"action_input":' in raw_text:
                try:
                    json_match = re.search(r"\{\s*\"action\"\s*:\s*\"([^\"]+)\".*?\"action_input\"\s*:\s*(.*?)\s*\}", raw_text, re.DOTALL)
                    if json_match:
                        act_name = json_match.group(1)
                        act_input_str = json_match.group(2).strip()
                        if act_input_str.startswith('"') and act_input_str.endswith('"'):
                            try:
                                act_input_str = json.loads(act_input_str)
                            except Exception:
                                pass
                        act_args = json.loads(act_input_str) if isinstance(act_input_str, str) and act_input_str.startswith('{') else {"prompt": act_input_str}
                        tool_calls = [{"name": act_name, "args": act_args}]
                except Exception as pe:
                    logger.warning(f"Failed to parse ReAct JSON tool call: {pe}")
            elif '"prompt":' in raw_text and ('"category":' in raw_text or '"style":' in raw_text):
                try:
                    img_match = re.search(r"\{\s*\"prompt\"\s*:[\s\S]*?\}", raw_text)
                    if img_match:
                        img_args = json.loads(img_match.group(0))
                        tool_calls = [{"name": "generate_image", "args": img_args}]
                except Exception as pe:
                    logger.warning(f"Failed to parse embedded image JSON: {pe}")

        # Determine source_channel & generation_id from payload. Prefer the
        # top-level source_channel (set for every turn, including proactive
        # ones with no inbound_message) over the inbound_message-derived value.
        src_channel = payload.source_channel or "telegram"
        gen_id = getattr(payload, "generation_id", 1)
        if payload.inbound_message:
            if not payload.source_channel and getattr(payload.inbound_message, "source_channel", None):
                src_channel = payload.inbound_message.source_channel
            if getattr(payload.inbound_message, "generation_id", None):
                gen_id = payload.inbound_message.generation_id

        # Execute any tool calls from LLM
        for call in tool_calls:
            tool_name = call.get("name")
            tool_args = call.get("args", {})
            tool = self.tool_registry.get_tool(tool_name)
            if tool:
                tool_output = await tool.execute(**tool_args)
                # 写入提议只登记待确认状态，绝不在这里执行（本路径也没有
                # 回环/事件能力，下一轮用户消息或确认框会走确认协议）。
                if self._is_proposal_tool(tool_name):
                    captured = self._capture_life_proposal(payload, tool_output)
                    if captured is not None:
                        logger.info("写入提议已登记，等待前端确认框/用户确认（非流式路径不追加工具回环）")
                    continue
                action = self._build_local_tool_action(tool_name, tool_output, payload, gen_id, src_channel)
                if action is not None:
                    actions.append(action)

        # Main text response payload
        raw_text = result.get("text", "")

        # Parse embedded sticker JSON blocks if any
        sticker_match = re.search(r"\{\s*\"(action_type|action)\"\s*:\s*\"(sticker|send_sticker)\".*?\"sticker_id\"\s*:\s*\"([^\"]+)\"\s*\}", raw_text, re.DOTALL)
        if not sticker_match:
            sticker_match = re.search(r"\{\s*\"sticker_id\"\s*:\s*\"([^\"]+)\"\s*\}", raw_text, re.DOTALL)

        if sticker_match:
            sticker_id = sticker_match.group(3) if len(sticker_match.groups()) >= 3 else sticker_match.group(1)
            # This path bypasses TelegramActionTool entirely (it's a
            # fallback for when the model leaks a tool-call-shaped JSON blob
            # into plain text instead of using real function calling), so it
            # must apply the same untrusted-filename check independently.
            # See docs/SECURITY.md.
            if is_safe_media_filename(sticker_id):
                actions.append(
                    ActionDecisionPayload(
                        event_id=payload.event_id,
                        source_component="cognitive_engine",
                        chat_id=payload.chat_id,
                        generation_id=gen_id,
                        source_channel=src_channel,
                        action_type="send_sticker",
                        sticker_id=sticker_id,
                    )
                )
            else:
                logger.warning(f"Rejected unsafe sticker_id parsed from raw LLM text: {sticker_id!r}")

        # Robustly clean markdown code blocks and multi-line JSON objects from text response
        cleaned_raw_text = re.sub(r"```(?:json)?\s*[\s\S]*?```", "", raw_text, flags=re.MULTILINE)
        cleaned_raw_text = re.sub(r"\{\s*\"(action_type|action|sticker_id)\"[\s\S]*?\}", "", cleaned_raw_text)
        cleaned_raw_text = cleaned_raw_text.strip()

        thought, clean_text = parse_thought_and_clean_text(cleaned_raw_text)

        logger.info(
            f"\n=======================================================\n"
            f"📥 [CognitiveEngine] LLM Raw Response Parsed (ChatID={payload.chat_id}):\n"
            f"-------------------------------------------------------\n"
            f"• Raw Text Output : {raw_text!r}\n"
            f"• CoT Thought     : {thought or '(None)'}\n"
            f"• Clean User Text : {clean_text!r}\n"
            f"• Tool Calls      : {tool_calls}\n"
            f"======================================================="
        )

        if clean_text:
            actions.append(
                ActionDecisionPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    generation_id=gen_id,
                    source_channel=src_channel,
                    action_type="send_message",
                    text_content=clean_text,
                    chat_action="typing",
                ))

        return actions

    async def stream_reasoning_loop(
        self,
        payload: ReasoningRequestPayload,
        cancel_event: Optional[Any] = None,
    ):
        """
        Yields sentence-level ActionDecisionPayload chunks in real-time as LLM streams text deltas.
        Supports cancellation via cancel_event.

        Also drives a bounded (MAX_TOOL_ROUNDS) tool-call round trip: a fire-and-
        forget local tool (TTS/image/telegram_action) maps straight to an
        ActionDecisionPayload with no round trip, same as before. Anything else
        -- presenter_mode, or an active presenter's MCP tools (ppt_*/vscode_*) --
        has its result fed back into `messages` and triggers another
        generate_stream() round, so the model's next text is grounded in the
        real tool result instead of guessed.
        """
        if payload.trigger_type == "tick" and not getattr(payload, "is_proactive_opportunity", False):
            return

        # See execute_reasoning_loop's equivalent block above for why
        # source_channel must be preferred over inbound_message -- a
        # proactive turn (trigger_type == "proactive") always has
        # inbound_message = None.
        src_channel = payload.source_channel or "telegram"
        gen_id = getattr(payload, "generation_id", 1)
        if payload.inbound_message:
            if not payload.source_channel and getattr(payload.inbound_message, "source_channel", None):
                src_channel = payload.inbound_message.source_channel
            if getattr(payload.inbound_message, "generation_id", None):
                gen_id = payload.inbound_message.generation_id

        system_prompt = PromptBuilder.build_system_prompt(payload)
        messages = PromptBuilder.build_messages(payload)

        for msg in messages:
            if isinstance(msg.get("metadata"), dict) and "vision_frame" in msg["metadata"]:
                del msg["metadata"]["vision_frame"]

        vision_frame = self.get_valid_vision_frame(payload.chat_id)
        if vision_frame and messages:
            if "metadata" not in messages[-1]:
                messages[-1]["metadata"] = {}
            messages[-1]["metadata"]["vision_frame"] = vision_frame

        # 写入确认协议：上一轮若留了待确认提议且用户刚回复了确认/取消，
        # 在这里确定性结算（执行不经过模型决策），并把结果作为系统事件
        # 注入对话，由模型用角色口吻说给用户听。
        async for _life_event in self._settle_pending_life_action(payload, messages):
            yield _life_event

        # 专注模式：先结算挂件控制哨兵（暂停/继续/放弃/完成）；不是哨兵的回合
        # 则按需注入专注中行为约束（对无关话题抗拒、不主动开新话题）。
        _inbound_text = (
            payload.inbound_message.raw_text
            if payload.inbound_message and payload.inbound_message.raw_text
            else ""
        )
        _is_focus_control = parse_focus_control(_inbound_text) is not None
        async for _focus_event in self._handle_focus_control(payload, messages):
            yield _focus_event
        if not _is_focus_control:
            _focus_hint = self._focus_mode_hint(payload.chat_id)
            if _focus_hint:
                messages.append({"role": "user", "content": _focus_hint})

        segmenter = SentenceSegmenter()
        # Campus KB facts retrieved by search_campus_kb calls this turn (any
        # round), carried on the turn's true final ActionDecisionPayload --
        # see the tool-execution loop below and the final-flush section.
        collected_citations: List[Dict[str, Any]] = []
        # 本轮已经发起过的 web_search 次数（见 tools.web_search.max_calls_per_turn）。
        # 下一轮的门控读它，用完就把工具从 schema 里摘掉。
        web_search_calls = 0
        # Last performance tag already published this turn, so a tag that
        # stays in the buffer across several deltas only fires one gesture.
        emitted_act_emotion: Optional[str] = None

        max_rounds = self.MAX_GAME_TOOL_ROUNDS if payload.trigger_type == "game_turn" else self.MAX_TOOL_ROUNDS

        try:
            for round_idx in range(max_rounds):
                # Recomputed every round, not just once up front: a
                # presenter_mode(activate) call in round N must make its
                # ppt_*/vscode_* tools visible to round N+1 in this same
                # turn, not just to some future reasoning call. sts2_* game
                # tools follow the same pattern, gated on trigger_type
                # instead of live session state -- Go decides a game turn is
                # happening before any LLM call occurs, so there's no
                # LLM-initiated toggle to track here (see
                # ToolRegistry.get_game_schemas).
                all_schemas = self.tool_registry.get_all_schemas() + self.presenter_manager.get_active_tool_schemas(payload.chat_id)
                if payload.trigger_type == "game_turn":
                    all_schemas = all_schemas + self.tool_registry.get_game_schemas()

                allow_proactive_image = get_config_val("tools.image_gen.allow_proactive", False)
                tools_schema = []
                for t in all_schemas:
                    t_name = t.get("name")
                    if src_channel == "web" and t_name == "telegram_action":
                        continue
                    if payload.trigger_type == "proactive" and t_name == "generate_image" and not allow_proactive_image:
                        continue
                    if t_name == "web_search" and not _web_search_tool_visible(web_search_calls):
                        continue
                    # 向着星工具族：每轮重读权限（后台改完配置热更新即生效）。
                    if not is_life_tool_visible(t_name):
                        continue
                    tools_schema.append(t)

                stream_gen = self.default_provider.generate_stream(
                    messages=messages,
                    tools_schema=tools_schema,
                    system_prompt=system_prompt,
                    cancel_event=cancel_event,
                )

                pending_calls: List[Dict[str, Any]] = []
                cancelled = False
                round_raw_text = ""
                # DeepSeek thinking 模式：把本轮思考过程带回给下一轮（见
                # OpenAIProvider._supports_reasoning_passthrough）。
                round_reasoning = ""

                async for event in stream_gen:
                    if cancel_event and cancel_event.is_set():
                        logger.info(f"⚡ stream_reasoning_loop cancelled for chat_id={payload.chat_id}")
                        cancelled = True
                        break

                    if event.get("type") == "tool_calls":
                        pending_calls.extend(event.get("calls", []))
                        # 同一轮里的多个工具调用共用这一份 reasoning_content，
                        # 它们最终会被写进同一条带 tool_calls 的 assistant 消息。
                        if event.get("reasoning_content"):
                            round_reasoning = event.get("reasoning_content")
                        continue

                    if event.get("type") == "thinking_delta":
                        thinking_text = event.get("text", "")
                        if thinking_text:
                            round_raw_text += f"<thought>{thinking_text}</thought>"
                            segmenter.push(f"<thought>{thinking_text}</thought>")
                        continue

                    delta_str = event.get("delta", "")
                    round_raw_text += delta_str
                    sentences = segmenter.push(delta_str)
                    if segmenter.last_act_emotion and segmenter.last_act_emotion != emitted_act_emotion:
                        emitted_act_emotion = segmenter.last_act_emotion
                        # Emitted before the sentence itself: the renderer needs
                        # the gesture queued while she is still speaking it.
                        yield EmotionUpdatePayload(
                            event_id=payload.event_id,
                            source_component="cognitive_engine",
                            chat_id=payload.chat_id,
                            emotion=emitted_act_emotion,
                        )
                    for s in sentences:
                        sentence_str = s.strip()
                        if sentence_str:
                            yield ActionDecisionPayload(
                                event_id=payload.event_id,
                                source_component="cognitive_engine",
                                chat_id=payload.chat_id,
                                generation_id=gen_id,
                                source_channel=src_channel,
                                action_type="send_message",
                                text_content=sentence_str,
                                chat_action="typing",
                                is_final=False,
                            )

                if cancelled:
                    return

                thought, clean_text = parse_thought_and_clean_text(round_raw_text)
                raw_summary = (
                    f"• Raw Text Output : {round_raw_text!r}\n"
                    f"• CoT Thought     : {thought or '(None)'}\n"
                    f"• Clean User Text : {clean_text!r}\n"
                    f"• Pending Tools   : {pending_calls}"
                )
                log_raw_trace("RAW_RESPONSE", payload.chat_id, f"Stream Round {round_idx+1}", raw_summary)
                logger.info(f"📥 [CognitiveEngine Stream Round {round_idx+1}] Raw response parsed for ChatID={payload.chat_id} -> logged to raw_prompts_and_responses.log")

                if not pending_calls:
                    break

                # Heartbeat: a round that produced only tool_calls (no text) is
                # about to spend real time executing them -- MCP tool calls can
                # involve a subprocess cold start, and each further
                # generate_stream() round is its own LLM round trip -- with
                # nothing published to NATS in between, Go core's per-chat
                # watchdog (ThinkingTimeoutDuration / whatever window a prior
                # chunk set) has no way to know this turn is still alive and
                # will force the state machine back to IDLE mid-turn (see
                # engine/state_machine.go's deadman switch). This empty,
                # non-final chunk carries no visible text -- WebGateway/gotd
                # adapter only forward non-empty TextContent to the user -- but
                # both still extend the watchdog window on any non-final
                # ActionDecision, which is exactly what's needed here.
                yield ActionDecisionPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    generation_id=gen_id,
                    source_channel=src_channel,
                    action_type="send_message",
                    text_content="",
                    chat_action="typing",
                    is_final=False,
                )

                needs_another_round = False
                has_terminating_tool = False
                if payload.trigger_type == "game_turn":
                    pending_calls = self._reorder_index_shifting_calls(pending_calls)
                for call in pending_calls:
                    tool_name = call.get("name")
                    if tool_name in self.STS2_TURN_TERMINATING_TOOLS:
                        has_terminating_tool = True
                    tool_args = call.get("args", {}) or {}
                    tool = self.tool_registry.get_tool(tool_name)

                    if tool is not None:
                        if tool_name in ("add_schedule", "query_schedule", "query_companion_stats", "get_recommendations"):
                            # 陪伴类工具必须用真实的 chat_id（Go Core 已把它折叠进
                            # WebNamespaceOffset），而不是模型猜的值——否则会查/写到
                            # 错误的 id 下，前端和数字人都对不上。
                            tool_args = dict(tool_args)
                            tool_args["chat_id"] = payload.chat_id
                        if tool_name == "web_search":
                            # Layer 4：一次搜索要花 3~8 秒，这段时间浏览器那边收不到
                            # 任何东西，看起来像卡死。先发一条"开始查"的进度事件，前端
                            # 据此显示带呼吸光的提示。文案来自角色卡（render_...
                            # _activity_label），所以是"正在翻手机查资料…"而不是出戏的
                            # "正在搜索互联网…"。
                            yield ToolActivityPayload(
                                event_id=payload.event_id,
                                source_component="cognitive_engine",
                                chat_id=payload.chat_id,
                                tool="web_search",
                                phase="start",
                                label=render_web_search_activity_label(PersonaLoader.load_active_persona()),
                            )

                        if tool_name == "presenter_mode":
                            tool_output = await tool.execute(**tool_args, chat_id=payload.chat_id)
                        else:
                            tool_output = await tool.execute(**tool_args)

                        # 写入提议：只登记待确认状态（模型看到的是"等待确认"），
                        # 并把确认框事件发给前端；真正的写入在用户确认后执行。
                        if self._is_proposal_tool(tool_name):
                            captured = self._capture_life_proposal(payload, tool_output)
                            if captured is not None:
                                tool_output, proposal_event = captured
                                yield proposal_event

                        if tool_name == "web_search":
                            web_search_calls += 1
                            logger.info(
                                f"🔎 [CognitiveEngine] 本轮决定联网搜索: query={(tool_args.get('query') or '')!r} "
                                f"(第 {web_search_calls} 次, status={tool_output.get('status')})"
                            )
                            # 搜索结束，撤掉前端的呼吸光提示（失败也要撤，否则会一直转）。
                            yield ToolActivityPayload(
                                event_id=payload.event_id,
                                source_component="cognitive_engine",
                                chat_id=payload.chat_id,
                                tool="web_search",
                                phase="done",
                                label="",
                            )

                        if tool_name in ("search_campus_kb", "web_search") and tool_output.get("status") == "success":
                            for fact in tool_output.get("facts", []):
                                citation = dict(fact)
                                if tool_name == "web_search":
                                    # <untrusted_content> 信封只给模型看；「参考资料」
                                    # 面板要的是剥掉标签的干净文本。
                                    citation["content"] = strip_untrusted_envelope(str(citation.get("content", "")))
                                if not citation.get("content"):
                                    continue
                                if not any(existing.get("content") == citation.get("content") for existing in collected_citations):
                                    collected_citations.append(citation)

                        action = self._build_local_tool_action(tool_name, tool_output, payload, gen_id, src_channel)
                        if action is not None:
                            yield action
                        else:
                            messages = self._append_tool_round_trip(messages, tool_name, tool_args, tool_output, thought_signature=call.get("thought_signature"), reasoning_content=round_reasoning)
                            needs_another_round = True
                    else:
                        mcp_output = await self.presenter_manager.call_tool(payload.chat_id, tool_name, tool_args)
                        if mcp_output is None:
                            logger.warning(f"Received unknown tool call from LLM: {tool_name!r} (chat_id={payload.chat_id})")
                            mcp_output = self._unknown_tool_error(payload.chat_id, tool_name)
                        messages = self._append_tool_round_trip(messages, tool_name, tool_args, mcp_output, thought_signature=call.get("thought_signature"), reasoning_content=round_reasoning)
                        needs_another_round = True

                if has_terminating_tool:
                    # Defensive State Check: verify if end_turn actually succeeded in transitioning state.
                    # If state still shows player turn with play phase, end_turn failed or was blocked; do not terminate loop yet.
                    last_battle = {}
                    for call in pending_calls:
                        if call.get("name") in ("sts2_end_turn", "end_turn"):
                            # Check messages or tool_output
                            pass
                    logger.info(f"🛑 Terminating game tool executed for chat_id={payload.chat_id}, exiting stream_reasoning_loop cleanly")
                    needs_another_round = False

                if not needs_another_round:
                    break
            else:
                # Round budget exhausted while a tool call still needed a
                # round trip -- without this, the turn would just end here:
                # segmenter.flush() has nothing in it (every round so far was
                # tool_calls, no text), so the user gets a silent empty
                # final marker and no reply at all. Force one last round
                # with tools_schema=[] -- the model literally cannot call
                # another tool, so it must wrap up in plain text using
                # whatever it already learned from the tool results appended
                # to `messages` across the rounds above.
                logger.warning(f"stream_reasoning_loop hit its round budget ({max_rounds}, trigger_type={payload.trigger_type!r}) for chat_id={payload.chat_id}, forcing text-only wrap-up round")
                wrapup_stream = self.default_provider.generate_stream(
                    messages=messages,
                    tools_schema=[],
                    system_prompt=system_prompt,
                    cancel_event=cancel_event,
                )
                async for event in wrapup_stream:
                    if cancel_event and cancel_event.is_set():
                        logger.info(f"⚡ stream_reasoning_loop cancelled during wrap-up for chat_id={payload.chat_id}")
                        return
                    if event.get("type") == "tool_calls":
                        continue  # tools_schema=[] should preclude this; ignore defensively
                    sentences = segmenter.push(event.get("delta", ""))
                    for s in sentences:
                        sentence_str = s.strip()
                        if sentence_str:
                            yield ActionDecisionPayload(
                                event_id=payload.event_id,
                                source_component="cognitive_engine",
                                chat_id=payload.chat_id,
                                generation_id=gen_id,
                                source_channel=src_channel,
                                action_type="send_message",
                                text_content=sentence_str,
                                chat_action="typing",
                                is_final=False,
                            )

            final_sentences = segmenter.flush()
            final_clean = [s.strip() for s in final_sentences if s and s.strip()]

            if final_clean:
                total_final = len(final_clean)
                for i, sentence in enumerate(final_clean):
                    is_last = (i == total_final - 1)
                    yield ActionDecisionPayload(
                        event_id=payload.event_id,
                        source_component="cognitive_engine",
                        chat_id=payload.chat_id,
                        generation_id=gen_id,
                        source_channel=src_channel,
                        action_type="send_message",
                        text_content=sentence,
                        chat_action="typing",
                        is_final=is_last,
                        citations=collected_citations if is_last and collected_citations else None,
                    )
            else:
                # If no sentence emitted in flush, emit empty final marker payload
                yield ActionDecisionPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    generation_id=gen_id,
                    source_channel=src_channel,
                    action_type="send_message",
                    text_content="",
                    chat_action="typing",
                    is_final=True,
                    citations=collected_citations if collected_citations else None,
                )

            # Fallback for a tag that only ever showed up in the tail of the
            # stream (e.g. the wrap-up round), so it is never dropped.
            if segmenter.last_act_emotion and segmenter.last_act_emotion != emitted_act_emotion:
                emitted_act_emotion = segmenter.last_act_emotion
                yield EmotionUpdatePayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    emotion=emitted_act_emotion,
                )

            if segmenter.last_emotion_delta:
                yield EmotionDeltaPayload(
                    event_id=payload.event_id,
                    source_component="cognitive_engine",
                    chat_id=payload.chat_id,
                    delta_valence=segmenter.last_emotion_delta.get("delta_valence", 0.0),
                    delta_arousal=segmenter.last_emotion_delta.get("delta_arousal", 0.0),
                    delta_affection=segmenter.last_emotion_delta.get("delta_affection", 0.0),
                    is_jealous=segmenter.last_emotion_delta.get("is_jealous", False),
                )
        except Exception as err:
            logger.error(f"Error in stream_reasoning_loop: {err}", exc_info=True)
            fallback_gen_id = gen_id if ('gen_id' in locals() and isinstance(gen_id, int)) else (payload.generation_id if payload.generation_id else 1)
            yield ActionDecisionPayload(
                event_id=payload.event_id,
                source_component="cognitive_engine",
                chat_id=payload.chat_id,
                generation_id=fallback_gen_id,
                source_channel=src_channel if 'src_channel' in locals() else payload.source_channel,
                action_type="send_message",
                text_content="",
                chat_action="",
                is_final=True,
            )
