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

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# FFmpeg path
ffmpeg_path = r"C:\ffmpeg\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(ffmpeg_path):
    raise RuntimeError(f"FFmpeg not found: {ffmpeg_path}")
os.environ["PATH"] = os.path.dirname(ffmpeg_path) + os.pathsep + os.environ.get("PATH", "")
logger.info(f"FFmpeg loaded: {ffmpeg_path}")


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
            logger.exception(f"FATAL ERROR: {e}")
            while True:
                await asyncio.sleep(60)

    async def _run_call(self, ctx: JobContext):
        await ctx.connect(auto_subscribe=True)
        self.room = ctx.room
        logger.info(f"Room joined: {ctx.room.name}")

        # Get caller phone from metadata
        metadata = json.loads(ctx.job.metadata or "{}")
        self.current_phone = metadata.get("phone_number", "5551234567")
        logger.info(f"Call from: {self.current_phone}")

        user = await self._wait_participant(ctx)
        logger.info(f"Customer connected: {user.identity}")

        # Publish agent's voice track
        self.audio_source = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("maya-voice", self.audio_source)
        await ctx.room.local_participant.publish_track(track)
        logger.info("Maya's voice ready")

        # Greeting
        await self.speak("Hey there! Welcome to Glamour Salon, this is Maya! How can I help you today?")

        # Subscribe to customer audio
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
                logger.info("Customer audio active")
                asyncio.create_task(self._capture_and_transcribe(track))

        # Start supervisor callback poller
        self.start_supervisor_callback_poller()

        await asyncio.sleep(2)
        logger.info("Maya is ready and listening")
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
        logger.info("Listening...")
        stream = rtc.AudioStream(track)
        buffer = bytearray()
        silence_dur = 0
        speech_started = False
        min_dur = 1.5
        max_dur = 9.0

        try:
            async for event in stream:
                if self.is_processing:
                    continue

                frame = event.frame if hasattr(event, 'frame') else event
                samples = np.frombuffer(frame.data, dtype=np.int16)

                # Resample if needed
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
                    logger.info(f"Speech detected ({dur:.1f}s) → transcribing...")
                    self.is_processing = True
                    audio_data = bytes(buffer)
                    buffer.clear()
                    speech_started = False
                    asyncio.create_task(self._transcribe_and_respond(audio_data))

        except Exception as e:
            logger.error(f"Audio capture error: {e}", exc_info=True)

    async def _transcribe_and_respond(self, audio_data: bytes):
        try:
            # Convert to WAV
            wav = io.BytesIO()
            import wave
            with wave.open(wav, 'wb') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(16000)
                f.writeframes(audio_data)
            wav.seek(0)

            # Transcribe
            result = await self.groq_client.audio.transcriptions.create(
                file=("speech.wav", wav, "audio/wav"),
                model="whisper-large-v3",
                language="en",
                response_format="text"
            )
            text = result.strip()
            if not text:
                return

            # === FILTER NOISE & NON-QUESTIONS ===
            if len(text) < 4:
                logger.info(f"Too short, ignored: '{text}'")
                return

            noise = {'um', 'uh', 'ah', 'hello', 'hi', 'hey', 'yes', 'no', 'okay', 'you'}
            if text.lower().strip('.,!?') in noise:
                logger.info(f"Noise word ignored: '{text}'")
                return

            question_words = {
                'what', 'when', 'where', 'who', 'how', 'can', 'do', 'does', 'is', 'are',
                'price', 'cost', 'book', 'appointment', 'hours', 'walk', 'service',
                'hair', 'color', 'cut', 'available', 'stylist', 'much'
            }
            words = set(text.lower().split())
<<<<<<< HEAD
=======
            
            # Allow if:
            # 1. Contains question mark
            # 2. Contains question words
            # 3. Has at least 3 words
>>>>>>> 7582d3053c18cdb6b97c31ee2ee0633285cacff0
            if not (words & question_words or text.endswith('?') or len(words) >= 3):
                logger.info(f"Not a real question, ignored: '{text}'")
                return

            logger.info(f"CUSTOMER: {text}")
            reply = await self._get_reply(text)
            logger.info(f"MAYA: {reply}")
            await self.speak(reply)

        except Exception as e:
            logger.error(f"Transcription error: {e}")
        finally:
            await asyncio.sleep(0.5)
            self.is_processing = False

    async def _get_reply(self, question: str) -> str:
<<<<<<< HEAD
        logger.info(f"Customer: {question}")
        reply = await self._get_intelligent_llm_reply(question)
=======
        # 1. Try KB first
        kb_answer = self.db.get_answer(question)
        if kb_answer:
            logger.info(f"KB HIT: {kb_answer}")
            return kb_answer
>>>>>>> 7582d3053c18cdb6b97c31ee2ee0633285cacff0

        # ONLY escalate if Maya says one of these EXACT natural phrases
        if any(phrase in reply.lower() for phrase in [
            "let me check",
            "i'll check",
            "i'm not sure",
            "let me ask",
            "check with my supervisor",
            "i'll find out"
        ]):
            logger.warning(f"ESCALATING → Maya doesn't know: {question}")
            customer = self.db.get_or_create_customer(self.current_phone, "Customer")
            self.db.create_help_request(question, customer['id'], self.current_phone)
            return "Hold on one sec — let me check that for you with my supervisor!"

        return reply

    async def _get_intelligent_llm_reply(self, question: str) -> str:
        try:
            kb = self.db.get_knowledge_base()
            kb_context = "\n".join([
                f"• {q.strip().capitalize()}: {a.strip()}"
                for q, a in kb.items()
            ])

            system_prompt = f"""You are Maya — the friendliest, most helpful receptionist at Glamour Salon.

You know these facts and ONLY these facts:
{kb_context}

INSTRUCTIONS:
- Answer EVERY question using the facts above when possible
- If someone asks "available Friday" → it means "are you open on Friday?" → answer from hours
- If someone asks about booking, specific stylist availability, or exact time slots → say "Let me check that for you!"
- NEVER say you're closed on days we're open
- NEVER invent stylist names or schedules
- Speak warmly, naturally, like a real person
- Use contractions: we're, you're, it's
- Max 2 sentences

Customer: {question}
Reply as Maya:"""

            response = await self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.8,
                max_tokens=130,
                timeout=8
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"LLM failed: {e}")
            return "Sorry, I'm having a little trouble — can you repeat that?"

    async def speak(self, text: str):
        if not self.audio_source:
            return
        try:
            logger.info(f"TTS → {text[:80]}{'...' if len(text)>80 else ''}")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/audio/speech",
                    headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
                    json={
                        "model": "playai-tts",
                        "input": text,
                        "voice": "Fritz-PlayAI",
                        "response_format": "mp3",
                        "speed": 0.95
                    },
                    timeout=20
                ) as r:
                    if r.status != 200:
                        logger.error(f"TTS failed: {r.status}")
                        return
                    mp3 = await r.read()

            if not mp3:
                return

            # Convert MP3 → PCM
            pcm, _ = ffmpeg.input('pipe:', format='mp3') \
                .output('pipe:', format='s16le', acodec='pcm_s16le', ar=24000, ac=1) \
                .run(input=mp3, capture_stdout=True, capture_stderr=True, quiet=True)

            asyncio.create_task(self._stream_audio(pcm))
            await asyncio.sleep(0.3)

        except Exception as e:
            logger.error(f"TTS error: {e}")

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
                if i % (chunk * 20) == 0:
                    await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Audio streaming error: {e}")

    def start_supervisor_callback_poller(self):
        async def poll():
            while True:
                try:
                    for req in self.db.get_all_requests():
                        if (req['status'] == 'resolved' and
                            req.get('supervisor_answer') and
                            req.get('caller_id')):
                            customer = self.db.get_or_create_customer(self.current_phone)
                            if req['caller_id'] == customer['id']:
                                answer = req['supervisor_answer']
                                logger.info(f"SUPERVISOR ANSWER → {answer}")
                                await self.speak(f"Oh my gosh, great news! My supervisor says: {answer}")
                                with self.db._get_connection() as conn:
                                    conn.execute("UPDATE help_requests SET status = 'delivered' WHERE id = ?", (req['id'],))
                except Exception as e:
                    logger.error(f"Poller error: {e}")
                await asyncio.sleep(2)

        asyncio.create_task(poll())
        logger.info("Supervisor poller active")


# Entry point
async def entrypoint(ctx: JobContext):
    logger.info("Call received — Maya is answering")
    db = Database()
    agent = DirectVoiceAgent(db)
    await agent.handle_call(ctx)
