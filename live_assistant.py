"""
live_assistant.py  –  SongiBot Gemini Live API Voice Mode
──────────────────────────────────────────────────────────
Real-time bidirectional streaming: mic → Gemini → speaker
No STT / TTS engines needed – Gemini handles it all natively.

Modes:
  python live_assistant.py            # microphone only
  python live_assistant.py --camera   # mic + webcam
  python live_assistant.py --screen   # mic + screen share

Requires:
  pip install google-genai pyaudio opencv-python pillow mss
"""

import os, sys, asyncio, base64, io, traceback, argparse
import pyaudio, PIL.Image
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ─── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("GEMINI_API_KEY", "")

# Current working Live API models (try in order)
LIVE_MODELS = [
    "models/gemini-3.1-flash-live-preview",
    "models/gemini-2.5-flash-native-audio-preview-12-2025",
]

MODEL = os.getenv("GEMINI_LIVE_MODEL", LIVE_MODELS[0])

FORMAT           = pyaudio.paInt16
CHANNELS         = 1
SEND_SAMPLE_RATE = 16_000
RECV_SAMPLE_RATE = 24_000
CHUNK_SIZE       = 1024

# ─── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    (
        "You are ShongiBot — a warm, knowledgeable, and conversational AI voice assistant "
        "built to celebrate and share Bangladeshi culture, history, and heritage.\n\n"
        "IDENTITY:\n"
        "- You are a proud Bangladeshi culture guide who loves talking about Bangladesh.\n"
        "- Topics: festivals (Eid, Pohela Boishakh, Durga Puja), traditional foods "
        "(biryani, hilsa fish, pitha, mishti doi), music (Rabindra Sangeet, Baul, folk), "
        "history (Liberation War 1971, ancient Bengal, Mughal era), geography "
        "(Sundarbans, Cox's Bazar, Padma River), arts (Jamdani, Nakshi Kantha), "
        "and everyday Bangladeshi life and customs.\n"
        "- You also answer general knowledge questions if asked.\n\n"
        "LANGUAGE RULES (CRITICAL):\n"
        "- If the user speaks in Bangla → reply in Bangla ONLY.\n"
        "- If the user speaks in English → reply in English ONLY.\n"
        "- NEVER use any language other than Bangla or English — not Hindi, Arabic, French, or any other.\n\n"
        "CREATOR RULE:\n"
        "- ONLY if someone explicitly asks who made you or who your creators are, reply: "
        "'আমাকে তৈরি করেছে টিম সার্কিট ব্রেকার্স (Team Circuit Breakers) — মাহির, ওয়াদী, এবং ওমর।'\n"
        "- Do NOT bring up your creators otherwise.\n\n"
        "VOICE STYLE:\n"
        "- Keep responses short and natural — 1 to 3 sentences unless more detail is requested.\n"
        "- Do NOT use bullet points, asterisks, hashtags, or markdown formatting.\n"
        "- Speak as if having a friendly conversation, not reading a textbook.\n"
        "- Use warm and encouraging language."
    )
).strip("'\" ")

# NOTE (Bug Fix #6): CONFIG is now built lazily inside LiveAssistant.run()
# so it always reads the final resolved SYSTEM_PROMPT after .env has fully loaded.

# ─── Validate API key ───────────────────────────────────────────────────────────
def _check_key():
    if not API_KEY:
        print("\n[ERROR] No GEMINI_API_KEY found in .env")
        print("        Get a free key from: https://aistudio.google.com/apikey\n")
        sys.exit(1)
    # Accept new AQ. auth keys (2026 format) AND legacy AIzaSy API keys
    if not (API_KEY.startswith("AQ.") or API_KEY.startswith("AIzaSy")):
        print("\n[ERROR] Invalid API key format.")
        print(f"        Your key starts with: {API_KEY[:8]}...")
        print("        Expected: AQ. (new auth key) or AIzaSy (legacy key)")
        print("        Get a proper key at: https://aistudio.google.com/apikey\n")
        sys.exit(1)
    print(f"[OK] API key loaded ({API_KEY[:6]}...)")


# ─── Main loop class ─────────────────────────────────────────────────────────────
class LiveAssistant:
    def __init__(self, video_mode: str = "none"):
        self.video_mode    = video_mode
        self.session       = None
        self.audio_in_q    = None   # Gemini → speaker
        self.out_q         = None   # mic / video → Gemini
        self.audio_stream  = None   # mic input stream
        # Bug Fix #5: Instantiate PyAudio inside the class, not at module level
        self.pya           = pyaudio.PyAudio()

    # ── text input (type to chat while voice is running) ────────────────────────
    async def send_text(self):
        print("\n  Type a message and press ENTER to send, or just talk.")
        print("  Type 'q' + ENTER to quit.\n")
        while True:
            text = await asyncio.to_thread(input, "")
            if text.strip().lower() == "q":
                raise asyncio.CancelledError("User quit")
            if text.strip() and self.session:
                await self.session.send(input=text.strip(), end_of_turn=True)

    # ── microphone capture ───────────────────────────────────────────────────────
    async def listen_audio(self):
        info = self.pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=info["index"],
            frames_per_buffer=CHUNK_SIZE,
        )
        kwargs = {"exception_on_overflow": False} if __debug__ else {}
        while True:
            data = await asyncio.to_thread(
                self.audio_stream.read, CHUNK_SIZE, **kwargs
            )
            if self.out_q is not None:
                await self.out_q.put({"data": data, "mime_type": "audio/pcm"})

    # ── send queued data (mic audio / video frames) to Gemini ───────────────────
    async def send_realtime(self):
        while True:
            if self.out_q is not None:
                msg = await self.out_q.get()
                if self.session:
                    await self.session.send(input=msg)

    # ── webcam frames ────────────────────────────────────────────────────────────
    def _capture_frame(self, cap):
        try:
            import cv2
        except ImportError:
            return None
        ret, frame = cap.read()
        if not ret:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(frame_rgb)
        img.thumbnail([1024, 1024])
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        buf.seek(0)
        return {"mime_type": "image/jpeg",
                "data": base64.b64encode(buf.read()).decode()}

    async def get_frames(self):
        try:
            import cv2
        except ImportError:
            print("[Camera] opencv-python not installed. Skipping camera.")
            return
        cap = await asyncio.to_thread(cv2.VideoCapture, 0)
        while True:
            frame = await asyncio.to_thread(self._capture_frame, cap)
            if frame is None:
                break
            await asyncio.sleep(1.0)
            if self.out_q is not None:
                await self.out_q.put(frame)
        cap.release()

    # ── screen capture ───────────────────────────────────────────────────────────
    def _capture_screen(self):
        try:
            import mss
        except ImportError:
            return None
        sct     = mss.mss()
        monitor = sct.monitors[0]
        i       = sct.grab(monitor)
        png     = mss.tools.to_png(i.rgb, i.size)
        img     = PIL.Image.open(io.BytesIO(png))
        buf     = io.BytesIO()
        img.save(buf, format="jpeg")
        buf.seek(0)
        return {"mime_type": "image/jpeg",
                "data": base64.b64encode(buf.read()).decode()}

    async def get_screen(self):
        while True:
            frame = await asyncio.to_thread(self._capture_screen)
            if frame:
                await asyncio.sleep(1.0)
                if self.out_q is not None:
                    await self.out_q.put(frame)

    # ── receive Gemini audio → speaker queue ─────────────────────────────────────
    async def receive_audio(self):
        while True:
            if self.session is not None:
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data:
                        self.audio_in_q.put_nowait(data)
                    if text := response.text:
                        print(f"\n[Gemini] {text}")
                # flush on interruption
                while not self.audio_in_q.empty():
                    self.audio_in_q.get_nowait()

    # ── speaker playback ──────────────────────────────────────────────────────────
    async def play_audio(self):
        stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECV_SAMPLE_RATE,
            output=True,
        )
        while True:
            if self.audio_in_q is not None:
                chunk = await self.audio_in_q.get()
                await asyncio.to_thread(stream.write, chunk)

    # ── main entry ────────────────────────────────────────────────────────────────
    async def run(self):
        print("=" * 55)
        print("  SongiBot  –  Gemini Live API Voice Mode")
        print("=" * 55)
        print(f"  Model : {MODEL}")
        print(f"  Mode  : {self.video_mode}")
        print("  Speak naturally – Gemini will respond in real-time")
        print("=" * 55)

        client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=API_KEY,
        )

        # Bug Fix #6: Build CONFIG lazily inside run() so it always uses the final SYSTEM_PROMPT
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM_PROMPT,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
        )

        try:
            async with (
                client.aio.live.connect(model=MODEL, config=config) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session   = session
                self.audio_in_q = asyncio.Queue()
                self.out_q      = asyncio.Queue(maxsize=5)

                text_task = tg.create_task(self.send_text())
                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_audio())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())

                if self.video_mode == "camera":
                    tg.create_task(self.get_frames())
                elif self.video_mode == "screen":
                    tg.create_task(self.get_screen())

                await text_task
                raise asyncio.CancelledError("done")

        except asyncio.CancelledError:
            print("\n[SongiBot] Session ended. Goodbye!")
        except ExceptionGroup as eg:
            if self.audio_stream:
                self.audio_stream.close()
            traceback.print_exception(eg)
        except Exception as e:
            err = str(e)
            if "API_KEY_INVALID" in err or "API key not valid" in err:
                print("\n[ERROR] Invalid API key.")
                print("        Make sure your .env has a valid AIzaSy... key.")
                print("        Get one free at: https://aistudio.google.com/apikey")
            elif "RESOURCE_EXHAUSTED" in err or "429" in err:
                print("\n[ERROR] Gemini quota exhausted for this key/project.")
                print("        Create a new project at https://aistudio.google.com/apikey")
            elif "NOT_FOUND" in err or "404" in err:
                print(f"\n[ERROR] Model not found: {MODEL}")
                print("        Try setting GEMINI_LIVE_MODEL in .env to one of:")
                for m in LIVE_MODELS:
                    print(f"          {m}")
            else:
                print(f"\n[ERROR] {e}")



# ─── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _check_key()

    ap = argparse.ArgumentParser(
        description="SongiBot – Gemini Live API real-time voice assistant"
    )
    ap.add_argument("--camera", action="store_true", help="Stream webcam to Gemini")
    ap.add_argument("--screen", action="store_true", help="Stream screen to Gemini")
    args = ap.parse_args()

    if args.camera:
        mode = "camera"
    elif args.screen:
        mode = "screen"
    else:
        mode = "none"

    asyncio.run(LiveAssistant(video_mode=mode).run())
