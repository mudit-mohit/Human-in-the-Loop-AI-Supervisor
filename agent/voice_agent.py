import asyncio
import logging
import aiohttp
import os
import io
import numpy as np
import ffmpeg
from livekit.agents import JobContext
from livekit import rtc
from groq import AsyncGroq
from database.db import Database
from config import Config
import json
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ffmpeg_path = r"C:\ffmpeg\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(ffmpeg_path):
    raise RuntimeError(f"FFmpeg not found: {ffmpeg_path}")
os.environ["PATH"] = os.path.dirname(ffmpeg_path) + os.pathsep + os.environ.get("PATH", "")
logger.info(f"FFmpeg: {ffmpeg_path}")


class DirectVoiceAgent:
    def __init__(self, db: Database):
        self.db = db
        self.groq_client = AsyncGroq(api_key=Config.GROQ_API_KEY)
        self.audio_source = None
        self.room = None
        self.is_processing = False
        self.current_phone = None

    async def handle_call(self, ctx: JobContext):
        try:
            await self._run_call(ctx)
        except Exception as e:
            logger.exception(f"FATAL: {e}")
            while True:
                await asyncio.sleep(60)

    async def _run_call(self, ctx: JobContext):
        await ctx.connect(auto_subscribe=True)
        self.room = ctx.room
        logger.info(f"Room: {ctx.room.name}")

        # Parse metadata
        metadata_str = ctx.job.metadata or "{}"
        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            metadata = {}
        self.current_phone = metadata.get("phone_number", "5551234567")
        logger.info(f"Call from: {self.current_phone}")

        user = await self._wait_participant(ctx)
        logger.info(f"User joined: {user.identity}")

        self.audio_source = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("agent", self.audio_source)
        await ctx.room.local_participant.publish_track(track)
        logger.info("Agent track published")

        await self.speak("Hello! Welcome to Glamour Salon. How can I help you today?")

        # Subscribe to user audio
        for participant in ctx.room.remote_participants.values():
            for pub in participant.track_publications.values():
                if pub.kind == rtc.TrackKind.KIND_AUDIO and not pub.subscribed:
                    pub.set_subscribed(True)

        @ctx.room.on("track_published")
        def on_track_published(pub, participant):
            if pub.kind == rtc.TrackKind.KIND_AUDIO:
                pub.set_subscribed(True)

        @ctx.room.on("track_subscribed")
        def on_track_subscribed(track, pub, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity == user.identity:
                logger.info("USER AUDIO READY")
                asyncio.create_task(self._capture_and_transcribe(track))

        # Start in-call poller
        self.start_supervisor_callback_poller()

        await asyncio.sleep(2)
        logger.info("Agent ready")
        while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
            await asyncio.sleep(5)

    async def _wait_participant(self, ctx):
        if ctx.room.remote_participants:
            return list(ctx.room.remote_participants.values())[0]
        fut = asyncio.Future()
        @ctx.room.on("participant_connected")
        def on(p):
            if not fut.done():
                fut.set_result(p)
        return await fut

    async def _capture_and_transcribe(self, track: rtc.RemoteAudioTrack):
        logger.info("Capturing audio...")
        stream = rtc.AudioStream(track)
        buffer = bytearray()
        silence_dur = 0
        speech_started = False
        min_dur = 1.5
        max_dur = 8.0

        try:
            async for event in stream:
                if self.is_processing:
                    continue

                frame = event.frame if hasattr(event, 'frame') else event
                samples = np.frombuffer(frame.data, dtype=np.int16)

                if frame.sample_rate != 16000:
                    factor = 16000 / frame.sample_rate
                    new_len = int(len(samples) * factor)
                    indices = np.linspace(0, len(samples)-1, new_len, dtype=int)
                    samples = samples[indices]

                if frame.num_channels > 1:
                    samples = samples[::frame.num_channels]

                buffer.extend(samples.tobytes())
                energy = np.abs(samples).mean()
                is_speech = energy > 500

                if is_speech:
                    speech_started = True
                    silence_dur = 0
                else:
                    if speech_started:
                        silence_dur += len(samples) / 16000

                dur = len(buffer) / 2 / 16000
                if dur > max_dur:
                    buffer.clear()
                    speech_started = False
                    continue

                if speech_started and dur >= min_dur and silence_dur >= 0.8 and not self.is_processing:
                    logger.info(f"Speech ({dur:.1f}s) → transcribing...")
                    self.is_processing = True
                    audio_data = bytes(buffer)
                    buffer.clear()
                    speech_started = False
                    asyncio.create_task(self._transcribe_and_respond(audio_data))

        except Exception as e:
            logger.error(f"Capture error: {e}", exc_info=True)

    async def _transcribe_and_respond(self, audio_data: bytes):
        try:
            wav = io.BytesIO()
            import wave
            with wave.open(wav, 'wb') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(16000)
                f.writeframes(audio_data)
            wav.seek(0)

            result = await self.groq_client.audio.transcriptions.create(
                file=("q.wav", wav, "audio/wav"),
                model="whisper-large-v3",
                language="en",
                response_format="text"
            )
            text = result.strip()
            if not text:
                return

            # === FILTER 1: Too short ===
            if len(text) < 3:
                logger.info(f"IGNORED (too short): '{text}'")
                return

            # === FILTER 2: Noise words ===
            noise_words = {'you', 'um', 'uh', 'ah', 'hello', 'hi', 'hey', 'yo', 'yes', 'no'}
            if text.lower().strip('.,!?') in noise_words:
                logger.info(f"IGNORED (noise word): '{text}'")
                return

            # === FILTER 3: Not a real question ===
            question_words = {
                'what', 'when', 'where', 'who', 'how', 'can', 'do', 'does', 
                'is', 'are', 'will', 'would', 'could', 'should',
                'price', 'cost', 'book', 'appointment', 'hours',
                'walk', 'service', 'hair', 'color', 'cut', 
                'available', 'availability', 'schedule', 'sara', 'sarah',
                'stylist', 'much', 'many', 'tell', 'need', 'want'
            }
            words = set(text.lower().split())
            
            # Allow if:
            # 1. Contains question mark
            # 2. Contains question words
            # 3. Has at least 3 words
            if not (words & question_words or text.endswith('?') or len(words) >= 3):
                logger.info(f"IGNORED (not a question): '{text}'")
                return

            logger.info(f"USER: '{text}'")
            reply = await self._get_reply(text)
            logger.info(f"AGENT: '{reply}'")
            await self.speak(reply)

        except Exception as e:
            logger.error(f"Transcribe error: {e}")
        finally:
            await asyncio.sleep(0.5)
            self.is_processing = False

    async def _get_reply(self, question: str) -> str:
        # 1. Try KB first
        kb_answer = self.db.get_answer(question)
        if kb_answer:
            logger.info(f"KB HIT: {kb_answer}")
            return kb_answer

        # 2. KB miss → use LLM with KB injected
        logger.info(f"KB MISS → Using LLM with KB context: {question}")
        llm_reply = await self._get_llm_reply(question)
        
        # ✅ FIX: Check if LLM wants to escalate
        if llm_reply:
            logger.info(f"LLM REPLY: {llm_reply}")
            
            # Check if the reply indicates uncertainty or need for escalation
            escalation_phrases = [
                "not sure",
                "check with my supervisor",
                "check with the supervisor",
                "let me check",
                "i don't know",
                "unsure"
            ]
            
            needs_escalation = any(phrase in llm_reply.lower() for phrase in escalation_phrases)
            
            if needs_escalation:
                logger.warning(f"🔺 LLM indicated escalation needed: {question}")
                try:
                    customer = self.db.get_or_create_customer(self.current_phone, "Customer")
                    request_id = self.db.create_help_request(question, customer['id'])
                    logger.info(f"✅ Created help request: {request_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to create help request: {e}", exc_info=True)
                
                return "That's a great question! Let me check with my supervisor and get back to you shortly. Is there anything else I can help you with?"
            
            return llm_reply

        # 3. LLM failed completely → escalate
        logger.warning(f"🔺 LLM failed, escalating: {question}")
        try:
            customer = self.db.get_or_create_customer(self.current_phone, "Customer")
            request_id = self.db.create_help_request(question, customer['id'])
            logger.info(f"✅ Created help request: {request_id}")
        except Exception as e:
            logger.error(f"❌ Failed to create help request: {e}", exc_info=True)
        
        return "That's a great question! Let me check with my supervisor and get back to you shortly."

    async def _get_llm_reply(self, question: str) -> str:
        try:
            kb = self.db.get_knowledge_base()
            kb_text = "\n".join([f"Q: {q}\nA: {a}" for q, a in kb.items()])

            system_prompt = f"""You are a friendly receptionist at Glamour Salon.

OFFICIAL INFORMATION (NEVER contradict this):
{kb_text}

RULES:
- Always use the official answers above
- Never make up prices, hours, or policies
- Answer naturally and conversationally
- If unsure → say: "I'm not sure, let me check with my supervisor."
- Keep answers short

User asked: {question}
"""

            response = await self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.7,
                max_tokens=150
            )
            reply = response.choices[0].message.content.strip()

            # Safety: block known wrong answers
            if any(bad in reply.lower() for bad in ["40", "free", "sunday open", "closed monday"]):
                return None

            return reply

        except Exception as e:
            logger.error(f"LLM error: {e}")
            return None

    
    async def speak(self, text: str):
        if not self.audio_source:
            return
        try:
            logger.info(f"TTS: {text[:100]}...")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/audio/speech",
                    headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
                    json={
                        "model": "playai-tts",
                        "input": text,
                        "voice": "Fritz-PlayAI",
                        "response_format": "mp3",
                        "speed": 0.9
                    },
                    timeout=30
                ) as r:
                    if r.status != 200:
                        return
                    mp3 = await r.read()

            if not mp3:
                return

            pcm, _ = ffmpeg.input('pipe:', format='mp3') \
                .output('pipe:', format='s16le', acodec='pcm_s16le', ar=24000, ac=1) \
                .run(input=mp3, capture_stdout=True, capture_stderr=True, quiet=True)

            asyncio.create_task(self._stream_audio(pcm))
            await asyncio.sleep(0.3)

        except Exception as e:
            logger.error(f"TTS failed: {e}")

    async def _stream_audio(self, pcm: bytes):
        try:
            chunk = 1920
            for i in range(0, len(pcm), chunk):
                data = pcm[i:i+chunk]
                if len(data) < chunk:
                    data += b'\x00' * (chunk - len(data))
                await self.audio_source.capture_frame(rtc.AudioFrame(
                    data=data,
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=960
                ))
                if i % (chunk * 25) == 0:
                    await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Stream error: {e}")

    def start_supervisor_callback_poller(self):
        async def poll():
            while True:
                try:
                    for req in self.db.get_all_requests():
                        if (req['status'] == 'resolved' and 
                            req.get('supervisor_answer') and 
                            req.get('caller_id')):
                            
                            # Check if this is for current caller
                            customer = self.db.get_or_create_customer(self.current_phone, "Customer")
                            if req['caller_id'] == customer['id']:
                                answer = req['supervisor_answer']
                                logger.info(f"SUPERVISOR ANSWER IN CALL → {answer}")
                                await self.speak(f"Great news! My supervisor says: {answer}")
                                
                                # Mark as delivered
                                with self.db._get_connection() as conn:
                                    conn.execute("UPDATE help_requests SET status = 'delivered' WHERE id = ?", (req['id'],))
                except Exception as e:
                    logger.error(f"Poller error: {e}")
                await asyncio.sleep(2)

        asyncio.create_task(poll())
        logger.info("In-call poller started")


async def entrypoint(ctx: JobContext):
    logger.info("Call accepted")
    db = Database()
    agent = DirectVoiceAgent(db)
    await agent.handle_call(ctx)
