import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class BasePayload(BaseModel):
    event_id: str = ""
    timestamp: float = Field(default_factory=time.time)
    source_component: str = ""


class InboundMessagePayload(BasePayload):
    chat_id: int
    user_id: int
    generation_id: int = 1
    message_id: int
    source_channel: str = "telegram"  # "telegram" | "web"
    raw_text: Optional[str] = None
    file_path: Optional[str] = None
    reply_to_message_id: Optional[int] = None
    media_type: Optional[str] = None  # "voice" | "photo" | None
    voice_transcript: Optional[str] = None
    chat_type: str = "private"
    sender_username: Optional[str] = None
    image_description: Optional[str] = None
    sender_first_name: str = ""
    sender_last_name: Optional[str] = None
    sender_display_name: str = ""


class TickPayload(BasePayload):
    iso_time: str
    time_of_day: str  # "morning" | "afternoon" | "evening" | "night"
    idle_duration_seconds: float
    is_sleep_hours: bool
    tick_counter: int
    emotion_description: str = ""


class EnrichContextReqPayload(BasePayload):
    chat_id: int
    user_id: int
    generation_id: int = 1
    inbound_message: Optional[InboundMessagePayload] = None
    current_state: str
    trigger_type: str  # "user_message" | "proactive" | "tick" | "game_turn"
    emotion_description: str = ""
    personality_description: str = ""
    circadian_description: str = ""
    # source_channel/proactive_reason/is_proactive_opportunity carry a
    # proactive turn's routing/context through memory_hub.py into
    # ReasoningRequestPayload -- without source_channel a proactive turn (no
    # inbound_message to derive it from) falls back to "telegram" in
    # cognitive_engine.py and gets silently dropped if the target was
    # actually a web session.
    source_channel: str = "telegram"  # "telegram" | "web"
    proactive_reason: Optional[str] = None
    is_proactive_opportunity: bool = False


class ReasoningRequestPayload(BasePayload):
    chat_id: int
    user_id: int
    generation_id: int = 1
    system_prompt_override: Optional[str] = None
    short_term_history: List[Dict[str, Any]] = Field(default_factory=list)
    user_profile: Dict[str, Any] = Field(default_factory=dict)
    rag_facts: List[str] = Field(default_factory=list)
    kb_facts: List[str] = Field(default_factory=list)
    agent_self_events: List[Dict[str, Any]] = Field(default_factory=list)
    proactive_reason: Optional[str] = None
    current_emotion: str = "NEUTRAL"
    personality_description: str = ""
    circadian_description: str = ""
    mood_score: float = 1.0
    formatted_time_str: str = ""
    inbound_message: Optional[InboundMessagePayload] = None
    trigger_type: Optional[str] = None  # "user_message" | "proactive" | "tick" | "game_turn"
    source_channel: Optional[str] = None
    is_proactive_opportunity: bool = False


    @field_validator("short_term_history", mode="before")
    @classmethod
    def val_history(cls, v):
        return v if v is not None else []

    @field_validator("user_profile", mode="before")
    @classmethod
    def val_profile(cls, v):
        return v if v is not None else {}

    @field_validator("rag_facts", mode="before")
    @classmethod
    def val_rag(cls, v):
        return v if v is not None else []

    @field_validator("kb_facts", mode="before")
    @classmethod
    def val_kb_facts(cls, v):
        return v if v is not None else []

    @field_validator("agent_self_events", mode="before")
    @classmethod
    def val_self_events(cls, v):
        return v if v is not None else []


class EmotionDeltaPayload(BasePayload):
    chat_id: int
    delta_valence: float = 0.0
    delta_arousal: float = 0.0
    delta_affection: float = 0.0
    is_jealous: bool = False


class EmotionUpdatePayload(BasePayload):
    """A discrete performance emotion for the avatar renderer.

    Unlike EmotionDeltaPayload -- which nudges the slow VAD mood state and is
    only ever a delta -- this carries a named emotion from the renderer's fixed
    vocabulary (happy/sad/angry/think/surprised/awkward/question/curious/
    neutral). The frontend maps it to a one-shot gesture motion through
    settings/mmd/emotion-action-map, which is what lets the character gesture
    in step with what she is saying.
    """
    chat_id: int
    emotion: str
    action: str = ""


class ActionDecisionPayload(BasePayload):
    chat_id: int
    generation_id: int = 1
    source_channel: str = "telegram"  # "telegram" | "web"
    action_type: str  # "send_message" | "CHAT_ACTION" | "send_sticker"
    text_content: Optional[str] = None
    typing_delay: float = 0.0
    media_type: Optional[str] = None  # "voice" | "photo" | None
    reply_to_message_id: Optional[int] = None
    voice_path: Optional[str] = None
    photo_path: Optional[str] = None
    chat_action: Optional[str] = "typing"
    sticker_id: Optional[str] = None
    reaction_emoji: Optional[str] = None
    is_final: bool = False
    # Campus KB citations accumulated across this turn's search_campus_kb
    # tool calls (see cognitive_engine.py's stream_reasoning_loop), only
    # ever set on the turn's true final payload. Each dict mirrors
    # campus_kb_tool.py's fact shape: {content, source, relevance_score}.
    citations: Optional[List[Dict[str, Any]]] = None


class ActionCompletedPayload(BasePayload):
    chat_id: int
    sent_message_id: Optional[int] = None
    action_decision: ActionDecisionPayload
    status: str  # "success" | "failed"
    sent_time: float = Field(default_factory=time.time)
    error_detail: Optional[str] = None


class ConsolidateMemoryReqPayload(BasePayload):
    user_id: int
    chat_id: int
    messages_to_consolidate: List[Dict[str, Any]] = Field(default_factory=list)
    trigger_reason: str = "memory_full"


class ErrorPayload(BasePayload):
    error_code: str
    error_message: str
    stack_trace: Optional[str] = None
    caused_by_event_id: Optional[str] = None


class StreamChunkPayload(BasePayload):
    chat_id: int
    generation_id: int = 1
    chunk_index: int = 0
    is_final: bool = False
    source_channel: str = "web"
    text_delta: Optional[str] = None
    audio_base64: Optional[str] = None
    sample_rate: Optional[int] = 32000
    format: Optional[str] = "pcm"
    visemes: Optional[List[Dict[str, Any]]] = None
    is_sentence_start: bool = False


StreamAudioChunkPayload = StreamChunkPayload


class STTTranscriptPayload(BasePayload):
    """Published by services/stt on both SUBJECT_STT_STREAM_PARTIAL (mid-utterance,
    no punctuation) and SUBJECT_STT_STREAM_FINAL (punctuation-restored) --
    same shape either way, the subject is what distinguishes them. Mirrors
    Go's schema.STTFinalTranscriptPayload (core/internal/schema/payloads.go)
    field-for-field so WebGateway's handleSTTFinalMsg can unmarshal it."""
    chat_id: int
    generation_id: int = 1
    text: str
    source_channel: str = "web"


class StreamCancelPayload(BasePayload):
    chat_id: int
    generation_id: int = 1
    reason: str = "barge_in_interrupt"
    source_channel: str = "web"


class StreamStateChangePayload(BasePayload):
    chat_id: int
    generation_id: int = 1
    state: str = "IDLE"
    source_channel: str = "web"


class ToolActivityPayload(BasePayload):
    """某个工具正在执行 / 刚执行完的进度信号。

    目前只有联网搜索用到：cognitive_engine 在执行 web_search 之前发一条
    phase="start"，拿到结果之后再发一条 phase="done"。Go 侧把它转成
    `agent.tool_activity` 这个 WS 帧，前端据此显示「正在查阅资料…」的呼吸光提示。

    为什么不动用 `agent.state_change`：那是 Go 侧 CSM 状态机自己的状态，Python
    直接改会和状态机打架；而且"正在查资料"是**工具级的瞬时事件**，不是对话状态。

    `label` 是人设化文案，由角色卡里的 web_search.searching 决定（见
    shared/web_search_persona.py），所以前端不需要自己拼"正在搜索…"这种出戏的字。
    """

    chat_id: int
    tool: str                    # "web_search"
    phase: str = "start"         # "start" | "done"
    label: str = ""              # 人设化文案，如「正在翻手机查资料…」


class LifeProposalPayload(BasePayload):
    """数字人写入提议（确认框）事件。

    phase 语义：
      - pending:    提议刚生成，前端弹出「需要确认」框
      - executing:  用户已点确认，正在写入（前端把按钮置为"执行中"）
      - executed / failed: 写入结果（message 直接展示给用户与模型）
      - cancelled / expired: 用户取消 / 超时或答非所问导致作废（前端关闭卡片）

    params 是完整的待执行参数，前端据此渲染"查看详情/手动编辑"；用户在框里
    改动的字段以白名单合并（services/cognitive/tools/tothestars_tool.py 的
    apply_life_proposal_edits），服务端仍会做最终校验。
    """
    chat_id: int
    proposal_id: str
    phase: str = "pending"
    kind: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    message: str = ""


class FocusCommandPayload(BasePayload):
    """专注模式（番茄钟）的确定性指令：由 cognitive_engine 在用户确认/操作后发出。

    Go 侧 engine.FocusManager 持有计时的唯一真源；每次指令都会换来一条
    `agent.focus.state` 广播（NATS 给认知服务做提示词注入，WS 给前端画倒计时）。
    action 语义：start(minutes) / pause / resume / end。
    """

    chat_id: int
    action: str                  # "start" | "pause" | "resume" | "end"
    minutes: int = 0             # 仅 start 使用，单位分钟
    outcome: str = ""            # 仅 end 使用："completed" | "abandoned"（信息性）


class NoticePayload(BasePayload):
    """轻量 UI 通知：不经过 LLM、不播报，只给前端弹一条低优先级提示。

    目前用于「远程连接」模式的待提交队列补交成功/放弃：这类结果不需要数字人
    开口，也不该占用对话轮次，所以单独走 agent.notice → WS agent.notice。
    """

    level: str = "info"      # "info" | "warn"
    title: str = "向着星"
    message: str = ""


class GameEventPayload(BasePayload):
    """Mirrors Go's schema.GameEventPayload (core/internal/schema/payloads.go).
    Published to SUBJECT_GAME_EVENT by webgateway/game_event_handler.go for
    observability/future consumers -- the UrgeEngine side effect itself
    happens in-process in that Go handler, not via a subscription to this."""
    game: str
    event_type: str
    weight: float = 0.0
    detail: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

