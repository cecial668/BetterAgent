"""Tests for the [emotion:xxx] performance tags that drive avatar gestures.

The tag is a stage direction the persona asks the model to emit inline
(e.g. "[emotion:think]嗯……让我想想。"). cognitive_engine.py has to do two
things with it: capture it so the renderer can play a gesture motion, and
make sure it never reaches TTS or the displayed text.
"""
import pytest

from services.cognitive.cognitive_engine import (
    CognitiveEngine,
    SentenceSegmenter,
    parse_act_emotion_from_text,
)
from shared.schema.payloads import (
    ActionDecisionPayload,
    EmotionUpdatePayload,
    InboundMessagePayload,
    ReasoningRequestPayload,
)


@pytest.mark.parametrize(("text", "expected"), [
    # canonical forms
    ("嗯……[emotion:happy]当然可以。", "happy"),
    ("[emotion:think]让我想想。", "think"),
    ("【emotion:curious】哦？", "curious"),
    ("[ACT:sad]原来如此。", "sad"),
    ("[心情:surprised]什么？", "surprised"),
    ("[emotion:SURPRISED]", "surprised"),
    # synonyms folded onto the canonical vocabulary
    ("[emotion:surprise]", "surprised"),
    ("[emotion:shy]", "awkward"),
    ("[emotion:thinking]", "think"),
    ("[emotion:confused]", "question"),
    ("[emotion:joyful]", "happy"),
    # last tag wins, so a mid-reply change of mood is honoured
    ("[emotion:happy]嘿嘿[emotion:awkward]……", "awkward"),
    # Markdown link / numbered list must not be mistaken for a tag
    ("见[文档](https://example.com) [emotion:curious]", "curious"),
    ("[1] 第一点 [emotion:angry]", "angry"),
    # nothing to see here
    ("普通的一句话，没有标签。", None),
    ("[emotion:banana]", None),        # not in the vocabulary
    ("[心情:思考]", None),              # Chinese value, only Latin names accepted
    ("", None),
    (None, None),
])
def test_parse_act_emotion_from_text(text, expected):
    assert parse_act_emotion_from_text(text) == expected


def test_segmenter_captures_and_strips_tag():
    """The tag is recorded on the segmenter but never lands in spoken text."""
    segmenter = SentenceSegmenter()
    spoken = []
    for piece in ["嗯……", "[emoti", "on:happy]", "本神当然", "赏脸啦。"]:
        spoken.extend(segmenter.push(piece))
    spoken.extend(segmenter.flush())

    assert segmenter.last_act_emotion == "happy"
    assert spoken == ["嗯，本神当然赏脸啦。"]
    for sentence in spoken:
        assert "emotion" not in sentence
        assert "[" not in sentence


def test_segmenter_keeps_last_tag_across_the_turn():
    segmenter = SentenceSegmenter()
    for piece in ["[emotion:think]嗯……", "让我想想。", "[emotion:awkward]别、别笑。"]:
        segmenter.push(piece)
    segmenter.flush()

    assert segmenter.last_act_emotion == "awkward"


class _StubProvider:
    """Replays canned text deltas in place of a real LLM stream."""

    def __init__(self, deltas):
        self._deltas = deltas

    async def generate_stream(self, messages=None, tools_schema=None, system_prompt=None, cancel_event=None):
        for delta in self._deltas:
            yield {"type": "text", "delta": delta}


class _StubToolRegistry:
    def get_all_schemas(self):
        return []

    def get_game_schemas(self):
        return []

    def get_tool(self, _name):
        return None


class _StubPresenterManager:
    def get_active_tool_schemas(self, _chat_id):
        return []


def _build_engine(deltas):
    engine = object.__new__(CognitiveEngine)
    engine.default_provider = _StubProvider(deltas)
    engine.tool_registry = _StubToolRegistry()
    engine.presenter_manager = _StubPresenterManager()
    engine.get_valid_vision_frame = lambda _chat_id: None
    return engine


def _build_payload():
    chat_id = 424242
    return ReasoningRequestPayload(
        event_id="test-event",
        chat_id=chat_id,
        user_id=1,
        trigger_type="user_message",
        source_channel="web",
        short_term_history=[{"role": "user", "content": "你在想什么？"}],
        inbound_message=InboundMessagePayload(
            chat_id=chat_id,
            user_id=1,
            message_id=1,
            source_channel="web",
            raw_text="你在想什么？",
        ),
    )


async def _run_turn(deltas):
    engine = _build_engine(deltas)
    payload = _build_payload()
    acts = []
    async for act in engine.stream_reasoning_loop(payload):
        acts.append(act)
    return acts


@pytest.mark.asyncio
async def test_stream_reasoning_loop_emits_emotion_update():
    acts = await _run_turn(["[emotion:think]嗯……", "让我想想，", "这件事要从五百年前讲起。"])
    emotions = [a for a in acts if isinstance(a, EmotionUpdatePayload)]
    sentences = [a for a in acts if isinstance(a, ActionDecisionPayload) and a.text_content]

    assert [e.emotion for e in emotions] == ["think"]
    assert "".join(s.text_content for s in sentences) == "嗯，让我想想，这件事要从五百年前讲起。"
    for s in sentences:
        assert "emotion" not in s.text_content


@pytest.mark.asyncio
async def test_stream_reasoning_loop_emits_one_update_per_change():
    acts = await _run_turn([
        "[emotion:happy]真的吗？",
        "那可太有戏剧性了。",
        "[emotion:awkward]（别过脸）……才、才不是高兴。",
    ])
    emotions = [a.emotion for a in acts if isinstance(a, EmotionUpdatePayload)]
    # ''happy'' fires once even though the tag sits in the buffer for several
    # deltas; ''awkward'' fires when the mood actually changes.
    assert emotions == ["happy", "awkward"]


@pytest.mark.asyncio
async def test_stream_reasoning_loop_is_silent_without_tags():
    acts = await _run_turn(["本神今日心情不错。"])
    assert [a for a in acts if isinstance(a, EmotionUpdatePayload)] == []
