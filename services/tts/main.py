import asyncio
import json

import logging
import os
import time
import base64
import nats
from dotenv import load_dotenv

from shared.subjects import (
    SUBJECT_AUDIO_CHUNK,
    SUBJECT_TTS_STREAM_END,
    SUBJECT_STREAM_CANCEL_REQ,
    SUBJECT_STREAM_CANCEL_ACK,
    SUBJECT_USER_INTERRUPT,
    action_decision_wildcard,
)
from shared.schema.payloads import StreamAudioChunkPayload, ActionDecisionPayload, StreamCancelPayload
from shared.logger import setup_logger
from shared.text_utils import clean_tts_text
from services.tts.cosyvoice_client import CosyVoiceClient
from services.tts.viseme_generator import text_to_visemes
from services.tts.audio_normalizer import add_wav_header

load_dotenv()
logger = setup_logger("tts_service")


async def error_cb(e):
    logger.warning(f"NATS Connection event in TTS service: {e}")


from shared.config_loader import get_config_val


from shared.persona_loader import PersonaLoader
from services.tts.gpt_sovits_client import GPTSoVITSClient
from services.tts.cosyvoice_client import CosyVoiceClient

# Outgoing publish slice length. The sentence is fully buffered first so the
# viseme timeline can be laid out over its TRUE duration; ~200ms keeps caption
# reveal granularity fine while keeping the browser's scheduled-node count low.
PUBLISH_CHUNK_SECONDS = 0.2


async def get_tts_client():
    persona_data = PersonaLoader.load_active_persona()
    provider = persona_data.get("tts", {}).get("provider", "gpt_sovits")
    if provider == "gpt_sovits":
        return GPTSoVITSClient()
    return CosyVoiceClient()


async def main():
    # 127.0.0.1, not "localhost" -- see docs/SECURITY.md §2.8.
    nats_url = os.getenv("NATS_URL", get_config_val("infrastructure.nats_url", "nats://127.0.0.1:4222"))
    nats_user = os.getenv("NATS_USER")
    nats_password = os.getenv("NATS_PASSWORD")
    if not nats_user or not nats_password:
        logger.error("NATS_USER / NATS_PASSWORD are not set. Refusing to connect to an unauthenticated message bus (see .env.example).")
        return
    try:
        nc = await nats.connect(nats_url, user=nats_user, password=nats_password, error_cb=error_cb, max_reconnect_attempts=10)
        logger.info(f"TTS Service connected to NATS at {nats_url}")
    except Exception as e:
        logger.warning(f"Failed to connect to NATS ({e}). TTS Service exiting gracefully.")
        return

    active_generations: dict[int, int] = {}
    active_tts_tasks: dict[int, tuple[asyncio.Task, asyncio.Event]] = {}
    sentence_queues: dict[int, asyncio.Queue] = {}
    queue_workers: dict[int, asyncio.Task] = {}
    tts_client = await get_tts_client()

    async def cancel_tts_stream(chat_id: int, gen_id: int = 0):
        if gen_id > active_generations.get(chat_id, 0):
            active_generations[chat_id] = gen_id

        if chat_id in sentence_queues:
            q = sentence_queues[chat_id]
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                except Exception:
                    break

        if chat_id in active_tts_tasks:
            task, event = active_tts_tasks[chat_id]
            event.set()
            if not task.done():
                task.cancel()
            logger.info(f"⚡ Cancelled TTS synthesis for chat_id={chat_id} (active_gen={active_generations.get(chat_id)})")

        # Tell WebGateway right away instead of leaving it to find out via its
        # own 2s CANCELLING auto-recovery timer -- that fallback exists for
        # when this service never got the cancel_req at all (crashed, NATS
        # hiccup), not as the *expected* path for the common case where
        # cancellation actually succeeded here in well under a second.
        ack_payload = StreamCancelPayload(
            source_component="tts_service",
            chat_id=chat_id,
            generation_id=active_generations.get(chat_id, gen_id),
            reason="barge_in_interrupt",
            source_channel="web",
        )
        ack_envelope = {
            "id": ack_payload.event_id,
            "subject": SUBJECT_STREAM_CANCEL_ACK,
            "source": "tts_service",
            "payload": ack_payload.model_dump(),
        }
        await nc.publish(SUBJECT_STREAM_CANCEL_ACK, json.dumps(ack_envelope).encode())

    async def synthesize_and_publish_tts(act: ActionDecisionPayload, cancel_event: asyncio.Event):
        chat_id = act.chat_id
        gen_id = getattr(act, "generation_id", 1)
        raw_text = act.text_content or ""
        text = clean_tts_text(raw_text)

        if not text:
            logger.info(f"🧹 Skipped non-pronounceable or pure emoji/code text '{raw_text[:20]}' for chat_id={chat_id}")
            return

        try:
            active_gen = active_generations.get(chat_id, 0)
            if gen_id < active_gen:
                logger.warn(f"🛡️ GPU Conservation Gate: Skipped TTS request for stale sentence (gen_id={gen_id} < active_gen={active_gen})")
                return

            client = await get_tts_client()
            logger.info(f"🎙️ Synthesizing TTS audio ({client.__class__.__name__}) for sentence: '{text[:20]}' (chat_id={chat_id}, gen_id={gen_id})")

            # --- Phase 1: collect the sentence's full PCM --------------------
            # Whole-sentence viseme timing needs the utterance's TRUE total
            # duration, which is only known once synthesis completes. The
            # client already delivers the sentence in ~200ms transport chunks
            # and GPT-SoVITS synthesizes faster than real time, so buffering
            # here costs no perceptible extra first-audio latency.
            pcm = bytearray()
            tts_interrupted = False
            async for audio_bytes, fmt in client.synthesize_stream(text, cancel_event=cancel_event):
                if cancel_event.is_set():
                    logger.info(f"⚡ TTS synthesis interrupted mid-stream for chat_id={chat_id}")
                    tts_interrupted = True
                    break

                # Re-check GPU Conservation Gate during streaming
                if gen_id < active_generations.get(chat_id, 0):
                    logger.info(f"🛡️ GPU Gate: Dropped mid-stream TTS chunk for chat_id={chat_id} (stale gen_id={gen_id})")
                    tts_interrupted = True
                    break

                # Collect raw PCM (strip WAV header if present)
                raw_pcm = audio_bytes[44:] if (fmt == "wav" and len(audio_bytes) > 44 and audio_bytes[:4] == b"RIFF") else audio_bytes
                pcm.extend(raw_pcm)

            if tts_interrupted:
                return
            if not pcm:
                logger.warning(f"⚠️ TTS produced no audio for sentence '{text[:15]}...' (chat_id={chat_id})")
                return
            if gen_id < active_generations.get(chat_id, 0):
                logger.warn(f"🛡️ GPU Gate: Dropped fully-buffered stale sentence for chat_id={chat_id} (stale gen_id={gen_id})")
                return

            sample_rate = getattr(client, "sample_rate", 32000)
            bytes_per_sec = float(sample_rate * 2)
            total_duration_sec = len(pcm) / bytes_per_sec

            # --- Phase 2: one viseme timeline over the real total duration ---
            # Every character's mouth shape is placed at its true proportion of
            # the utterance. The old per-chunk allocation guessed each chunk's
            # share from an estimated chars/sec rate, which drifted: near the
            # end of a sentence the text could run out early and the mouth
            # froze on the last shape (the "张着嘴不动" artifact).
            full_visemes = text_to_visemes(text, total_duration_sec)

            # --- Phase 3: publish fixed ~200ms slices ------------------------
            chunk_bytes = max(2, int(bytes_per_sec * PUBLISH_CHUNK_SECONDS))
            total_bytes = len(pcm)
            raw_pos = 0
            chunk_idx = 0
            for start_byte in range(0, total_bytes, chunk_bytes):
                if cancel_event.is_set():
                    logger.info(f"⚡ TTS publish interrupted for chat_id={chat_id}")
                    break
                if gen_id < active_generations.get(chat_id, 0):
                    logger.info(f"🛡️ GPU Gate: Dropped mid-publish TTS slice for chat_id={chat_id} (stale gen_id={gen_id})")
                    break

                slice_pcm = bytes(pcm[start_byte:start_byte + chunk_bytes])
                chunk_start_sec = start_byte / bytes_per_sec
                chunk_end_sec = (start_byte + len(slice_pcm)) / bytes_per_sec

                visemes = [
                    {**v, "time_offset": round(v["time_offset"] - chunk_start_sec, 3)}
                    for v in full_visemes
                    if chunk_start_sec <= v["time_offset"] < chunk_end_sec
                ]

                # Typewriter caption slice, proportional to this chunk's share
                # of the timeline; the last chunk soaks up any rounding rest.
                if start_byte + chunk_bytes >= total_bytes:
                    target_pos = len(text)
                else:
                    target_pos = round(len(text) * chunk_end_sec / total_duration_sec)
                    target_pos = max(raw_pos, min(target_pos, len(text)))
                text_delta = text[raw_pos:target_pos]
                raw_pos = target_pos

                # Wrap raw PCM slices with a 44-byte RIFF WAV header for
                # browser AudioContext compatibility.
                # NOTICE:
                # Do NOT apply smooth_pcm_chunk_edges() per slice here. The
                # browser schedules these WAV slices back-to-back on the
                # AudioContext clock, so their samples are already sample-
                # contiguous; a per-slice 3ms fade-out+fade-in inserted a
                # ~6ms amplitude notch every ~200ms, heard as a periodic
                # stutter/gating artifact ("一卡一卡").
                # Root cause: fades were a leftover band-aid for boundaries
                # that are actually seamless with gapless scheduling.
                # Removal condition: only reintroduce if a real pop/click is
                # observed at a specific boundary AND confirmed by listening.
                out_bytes = add_wav_header(slice_pcm, sample_rate=sample_rate)

                audio_b64 = base64.b64encode(out_bytes).decode("utf-8")
                chunk_payload = StreamAudioChunkPayload(
                    event_id=act.event_id,
                    source_component="tts_service",
                    chat_id=chat_id,
                    generation_id=gen_id,
                    audio_base64=audio_b64,
                    sample_rate=sample_rate,
                    format="wav",
                    visemes=visemes,
                    text_delta=text_delta,
                    is_sentence_start=(chunk_idx == 0),
                )

                envelope = {
                    "id": act.event_id,
                    "subject": SUBJECT_AUDIO_CHUNK,
                    "source": "tts_service",
                    "payload": chunk_payload.model_dump(),
                }
                await nc.publish(SUBJECT_AUDIO_CHUNK, json.dumps(envelope).encode())
                chunk_idx += 1
                logger.debug(f"Published TTS Audio Chunk #{chunk_idx} ({len(slice_pcm)} bytes, {len(visemes)} visemes) for chat_id={chat_id}")

            if chunk_idx > 0:
                logger.info(f"✅ Completed TTS Audio Synthesis for sentence '{text[:15]}...' ({chunk_idx} chunks, {total_duration_sec:.1f}s) for chat_id={chat_id}")
                try:
                    debug_dir = os.path.join("temp", "tts", "debug")
                    os.makedirs(debug_dir, exist_ok=True)
                    ts = int(time.time() * 1000)
                    debug_path = os.path.join(debug_dir, f"tts_{ts}_{chat_id}.wav")
                    with open(debug_path, "wb") as f:
                        f.write(add_wav_header(bytes(pcm), sample_rate=sample_rate))
                    logger.info(f"💾 Saved TTS debug audio to {debug_path}")
                except Exception as debug_err:
                    logger.debug(f"Failed to save debug TTS audio: {debug_err}")

        except asyncio.CancelledError:
            logger.info(f"⚡ TTS synthesis task for chat_id={chat_id} caught CancelledError & exited cleanly.")
        except Exception as err:
            logger.error(f"Error in TTS synthesis: {err}", exc_info=True)
        finally:
            active_tts_tasks.pop(chat_id, None)

    async def process_sentence_queue(chat_id: int):
        """Processes intra-turn sentences sequentially to prevent self-cancellation."""
        q = sentence_queues[chat_id]
        while True:
            try:
                act, cancel_event = await q.get()
                current_active_gen = active_generations.get(chat_id, 0)
                gen_id = getattr(act, "generation_id", 1)

                if gen_id >= current_active_gen and not cancel_event.is_set():
                    # Register active task for cross-turn cancellation
                    active_task = asyncio.current_task()
                    if active_task:
                        active_tts_tasks[chat_id] = (active_task, cancel_event)

                    await synthesize_and_publish_tts(act, cancel_event)

                    # Publish TTS Stream End strictly when the final sentence of the turn completes
                    if getattr(act, "is_final", False):
                        end_payload = {
                            "event_id": act.event_id,
                            "source_component": "tts_service",
                            "chat_id": chat_id,
                            "generation_id": gen_id,
                            "is_final": True,
                        }
                        envelope = {
                            "id": act.event_id,
                            "subject": SUBJECT_TTS_STREAM_END,
                            "source": "tts_service",
                            "payload": end_payload,
                        }
                        await nc.publish(SUBJECT_TTS_STREAM_END, json.dumps(envelope).encode())
                        logger.info(f"🏁 Published TTS Stream End for chat_id={chat_id}, gen_id={gen_id}")

                q.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in process_sentence_queue for chat_id={chat_id}: {e}")

    async def cancel_handler(msg):
        try:
            data = json.loads(msg.data.decode())
            payload_dict = data.get("payload", {})
            chat_id = payload_dict.get("chat_id", 0)
            gen_id = payload_dict.get("generation_id", 0)
            if chat_id:
                await cancel_tts_stream(chat_id, gen_id)
        except Exception as e:
            logger.warning(f"Error handling stream cancel request in TTS: {e}")

    async def action_decision_handler(msg):
        try:
            data = json.loads(msg.data.decode())
            payload_dict = data.get("payload", {})

            # Channel routing is now handled by NATS itself (subscribed only
            # to agent.action.web.* -- see the subscribe call below). TTS is
            # intentionally web-only (Telegram doesn't get synthesized
            # streaming voice through this pipeline); source_channel is a
            # self-reported payload field, so a mismatch here is a publisher
            # bug worth logging loudly, not a reason to drop a message NATS
            # already routed correctly. The old "telegram" default existed
            # specifically to fail-closed into the drop this replaces.
            src_channel = payload_dict.get("source_channel", "unknown")
            if src_channel != "web":
                logger.error(f"Received ActionDecision on web-channel subject with mismatched source_channel={src_channel!r} (chat_id={payload_dict.get('chat_id')}) -- processing anyway, subject is authoritative post-refactor")

            act = ActionDecisionPayload(**payload_dict)
            text = act.text_content

            if act.action_type in ("send_message", "send_voice") and text:
                gen_id = getattr(act, "generation_id", 1)
                active_gen = active_generations.get(act.chat_id, 0)

                # 🔧 Fix: Only trigger cancellation when new_gen_id > active_gen_id (Cross-Turn User Interrupt)!
                if gen_id > active_gen:
                    logger.info(f"⚡ Cross-Turn Interrupt detected for chat_id={act.chat_id} (new_gen={gen_id} > active_gen={active_gen})")
                    await cancel_tts_stream(act.chat_id, gen_id)
                elif gen_id < active_gen:
                    logger.warn(f"🛡️ Skipped stale sentence at ActionDecision gate for chat_id={act.chat_id} (gen_id={gen_id} < active_gen={active_gen})")
                    return

                # Ensure queue & queue worker exist for chat_id
                if act.chat_id not in sentence_queues:
                    sentence_queues[act.chat_id] = asyncio.Queue()
                    queue_workers[act.chat_id] = asyncio.create_task(process_sentence_queue(act.chat_id))

                cancel_event = asyncio.Event()
                await sentence_queues[act.chat_id].put((act, cancel_event))

        except Exception as err:
            logger.error(f"Error in TTS action_decision_handler: {err}", exc_info=True)

    async def persona_update_handler(msg):
        # gpt_sovits_client.py's synthesize_stream already re-reads
        # PersonaLoader.load_active_persona() fresh on every call (so
        # prompt_audio/prompt_text/prompt_lang/text_lang hot-reload
        # correctly) -- but without this subscription, PersonaLoader's
        # in-process cache inside *this* service never gets invalidated,
        # so it keeps serving whatever was loaded the first time this
        # process needed a persona, no matter how many times the YAML on
        # disk gets patched. Same pattern as services/cognitive/main.py.
        await PersonaLoader.handle_persona_update(msg.data)

    await nc.subscribe(action_decision_wildcard("web"), queue="tts_workers", cb=action_decision_handler)
    await nc.subscribe(SUBJECT_STREAM_CANCEL_REQ, cb=cancel_handler)
    await nc.subscribe(SUBJECT_USER_INTERRUPT, cb=cancel_handler)
    await nc.subscribe("agent.persona.update", cb=persona_update_handler)

    logger.info(f"TTS Service ({tts_client.__class__.__name__}) listening on NATS subjects (Action Decisions & Cancel Control)...")

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
