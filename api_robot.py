import os
import sys
import time
import asyncio
import subprocess
import threading
import queue
import requests
import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
import edge_tts
from dotenv import load_dotenv

load_dotenv()

# --- Configs ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip("'\" ")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip("'\" ")

XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip("'\" ")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-2").strip("'\" ")

ALWAYS_ON_MIC = os.getenv("ALWAYS_ON_MIC", "true").lower() in ("true", "1", "yes")
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "150"))

# Determine active provider
if GROQ_API_KEY:
    API_PROVIDER = "groq"
    API_KEY = GROQ_API_KEY
    MODEL = GROQ_MODEL
elif XAI_API_KEY:
    API_PROVIDER = "grok"
    API_KEY = XAI_API_KEY
    MODEL = XAI_MODEL
else:
    print("❌ Error: Neither GROQ_API_KEY nor XAI_API_KEY environment variable is found in .env!")
    sys.exit(1)


AUDIO_FILE = "input.wav"
RESPONSE_AUDIO = "output.mp3"
SAMPLE_RATE = 44100  # 44.1 kHz sample rate for USB camera/audio mics

def play_audio(file_path):
    """Auto-detects and routes sound to USB Speaker or 3.5mm Headphone Jack.
    On Linux/Raspberry Pi: uses amixer + mpg123 with device auto-detection.
    On Windows (dev mode): uses the default system player.
    """
    # Bug Fix #3: Guard Linux-only commands so Windows dev runs don't crash
    if sys.platform.startswith("linux"):
        os.system("amixer -c 0 sset PCM 100% unmute > /dev/null 2>&1")
        os.system("amixer -c 1 sset Speaker 100% unmute > /dev/null 2>&1")

        aplay_output = subprocess.getoutput("aplay -l")

        if "USB Audio" in aplay_output or "Device [USB" in aplay_output:
            print("🔊 Playing through USB Audio...")
            os.system(f"mpg123 -a plughw:1,0 -q {file_path}")
        elif "Headphones" in aplay_output:
            print("🎧 Playing through 3.5mm Headphone Jack...")
            os.system(f"mpg123 -a plughw:0,0 -q {file_path}")
        else:
            print("🔊 Playing through Default Output...")
            os.system(f"mpg123 -q {file_path}")
    elif sys.platform == "darwin":
        # macOS fallback
        os.system(f"afplay {file_path}")
    else:
        # Windows fallback — use built-in start command
        print("🔊 Playing through Windows Default Audio...")
        os.system(f'start /min "" "{file_path}"')

def record_audio(max_duration=10, silence_timeout=0.8):
    """Dynamically listens to mic: starts recording when user speaks and stops automatically after silence."""
    CHUNK = 2048
    RATE = SAMPLE_RATE
    
    print("\n🎤 Dynamic Listening active... Speak whenever you want!")
    
    dev_index = None
    try:
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) > 0:
                dev_index = idx
                if 'USB' in dev.get('name', '') or 'Camera' in dev.get('name', ''):
                    break
    except Exception:
        pass

    frames = []
    pre_buffer = []
    has_speech_started = False
    silence_start_time = None
    start_time = time.time()
    
    try:
        kwargs = {"samplerate": RATE, "channels": 1, "dtype": 'int16', "blocksize": CHUNK}
        if dev_index is not None:
            kwargs["device"] = dev_index

        with sd.InputStream(**kwargs) as stream:
            while True:
                data, overflow = stream.read(CHUNK)
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_chunk.astype(np.float32)**2))
                
                now = time.time()
                
                # Check max listening timeout when no speech occurs
                if not has_speech_started and (now - start_time > 5.0):
                    break
                # Check max speech duration
                if has_speech_started and (now - start_time > max_duration):
                    print("⏱️ Max speech duration reached.")
                    break

                if rms >= VAD_THRESHOLD:
                    if not has_speech_started:
                        print(f"🗣️ Speech detected! (RMS: {rms:.1f}). Recording dynamically...")
                        has_speech_started = True
                        frames.extend(pre_buffer)
                        pre_buffer.clear()
                    frames.append(data)
                    silence_start_time = None
                else:
                    if has_speech_started:
                        frames.append(data)
                        if silence_start_time is None:
                            silence_start_time = now
                        elif now - silence_start_time >= silence_timeout:
                            print("⏹️ User finished speaking (silence detected). Finalizing audio...")
                            break
                    else:
                        # Keep last ~0.3s in pre-speech rolling buffer
                        pre_buffer.append(data)
                        if len(pre_buffer) > int((RATE / CHUNK) * 0.3):
                            pre_buffer.pop(0)

    except Exception as e:
        print(f"⚠️ Dynamic Mic InputStream Note: {e}. Falling back to standard recording.")
        try:
            recording = sd.rec(int(4 * RATE), samplerate=RATE, channels=1, dtype='int16')
            sd.wait()
            write(AUDIO_FILE, RATE, recording)
            rms = np.sqrt(np.mean(recording.astype(np.float32)**2))
            return rms
        except Exception:
            return 0.0

    if not has_speech_started or len(frames) == 0:
        return 0.0

    # Concatenate recorded audio frames
    audio_data = np.concatenate(frames, axis=0)
    write(AUDIO_FILE, RATE, audio_data)
    total_rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2))
    duration_sec = len(audio_data) / RATE
    print(f"✔ Dynamic audio captured ({duration_sec:.1f}s, Audio RMS: {total_rms:.1f})")
    return total_rms

def transcribe_audio():
    """Transcribes audio using free Google Speech Recognition with multi-language fallback (Bangla + English)."""
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        print("⚡ Transcribing audio via free Google Speech Recognition...")
        with sr.AudioFile(AUDIO_FILE) as source:
            audio = r.record(source)

        # 1. Try Bengali (bn-BD)
        try:
            user_text = r.recognize_google(audio, language="bn-BD")
            if user_text.strip():
                return user_text.strip()
        except sr.UnknownValueError:
            pass

        # 2. Try English (en-US)
        try:
            user_text = r.recognize_google(audio, language="en-US")
            if user_text.strip():
                return user_text.strip()
        except sr.UnknownValueError:
            print("❓ Speech not recognized (try speaking clearer or closer to mic).")

        # Bug Fix #1: Always return "" explicitly — never return None
        return ""

    except ImportError:
        print("❌ Error: SpeechRecognition package not installed. Run: pip install SpeechRecognition")
        return ""
    except sr.RequestError as e:
        print(f"❌ Speech-to-Text Network Error: {e}")
        return ""
    except Exception as e:
        print(f"❌ Speech-to-Text Error: {e}")
        return ""

def get_ai_response(user_text, system_prompt):
    """Queries either Groq or Grok API using direct requests."""
    if API_PROVIDER == "groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            "model": MODEL,
            "stream": False,
            "temperature": 0.7
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            r.raise_for_status()
            response_data = r.json()
            return response_data['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"❌ Groq API Error: {e}")
            try:
                print(f"Debug Response: {r.text}")
            except:
                pass
            return "দুঃখিত, এপিআই-তে কোনো সমস্যা হয়েছে।"
    else:
        url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            "model": MODEL,
            "stream": False,
            "temperature": 0.7
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            r.raise_for_status()
            response_data = r.json()
            return response_data['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"❌ Grok API Error: {e}")
            try:
                print(f"Debug Response: {r.text}")
            except:
                pass
            return "দুঃখিত, এপিআই-তে কোনো সমস্যা হয়েছে।"


async def text_to_speech(text, output_path=None):
    """Generates neural voice output using Microsoft Edge-TTS."""
    if output_path is None:
        output_path = RESPONSE_AUDIO
    # Detect if the generated text contains Bengali characters to select the correct voice
    has_bengali = any(0x0980 <= ord(char) <= 0x09FF for char in text)
    voice = "bn-BD-NabanitaNeural" if has_bengali else "en-US-EmmaNeural"

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def update_gui(state, user_text="", robot_text=""):
    """Helper to update Desk Buddy GUI state across threads."""
    try:
        import desk_buddy_gui
        if desk_buddy_gui.gui_instance:
            desk_buddy_gui.gui_instance.set_state(state, user_text, robot_text)
    except Exception:
        pass


# ─── Concurrent Pipeline ───────────────────────────────────────────────────────
# audio_queue: recorder thread → processor thread
# Each item is a numpy int16 array of the recorded utterance.
audio_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=4)

# Shared flag: True while the bot is playing a response.
# Recorder checks this to avoid capturing the bot's own voice.
is_speaking = threading.Event()


def recorder_worker(has_mic: bool):
    """
    Thread-1: Continuously listens for speech and pushes audio arrays
    into audio_queue. Runs independently from the processor.
    """
    print("🎙️  [Recorder] Pipeline recorder started.")
    while True:
        try:
            if not has_mic:
                # No mic — text mode handled entirely in processor
                time.sleep(0.5)
                continue

            # Wait while bot is speaking to avoid self-echo
            while is_speaking.is_set():
                time.sleep(0.05)

            update_gui("LISTENING")
            rms_energy = record_audio(max_duration=10, silence_timeout=0.8)

            if rms_energy <= 0.0:
                update_gui("IDLE")
                time.sleep(0.05)
                continue

            # Load the audio that was just saved by record_audio()
            try:
                from scipy.io.wavfile import read as wav_read
                _, audio_arr = wav_read(AUDIO_FILE)
                # Put a copy into the queue (non-blocking — drop if full)
                audio_queue.put_nowait(audio_arr.copy())
                print("🎤  [Recorder] Audio captured → queued for processing.")
            except queue.Full:
                print("⚠️  [Recorder] Queue full — dropping utterance (processor busy).")
            except Exception as e:
                print(f"❌  [Recorder] Audio read error: {e}")

        except Exception as e:
            print(f"❌  [Recorder] Error: {e}")
            time.sleep(0.2)


def processor_worker(system_prompt: str, has_mic: bool):
    """
    Thread-2: Pulls audio arrays from audio_queue, runs STT → AI → TTS → play.
    Runs concurrently with the recorder so recording continues during AI processing.
    """
    print("🧠  [Processor] Pipeline processor started.")
    turn_index = 0

    while True:
        try:
            if not has_mic:
                # Text-input fallback when no microphone
                if sys.stdin.isatty():
                    user_text = input("\n👉 Type your message: ").strip()
                    if not user_text:
                        continue
                else:
                    time.sleep(10)
                    continue
            else:
                # Block until recorder puts an audio chunk in the queue
                try:
                    audio_arr = audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Step B: Save array to temp WAV and transcribe
                turn_wav = f"input_turn_{turn_index % 4}.wav"
                write(turn_wav, SAMPLE_RATE, audio_arr)

                update_gui("THINKING")
                # Temporarily swap AUDIO_FILE path for transcription
                orig = globals().get("AUDIO_FILE", "input.wav")
                import builtins
                # Transcribe from the per-turn file
                try:
                    import speech_recognition as sr
                    r = sr.Recognizer()
                    print("⚡  [Processor] Transcribing...")
                    with sr.AudioFile(turn_wav) as source:
                        audio = r.record(source)
                    user_text = ""
                    try:
                        user_text = r.recognize_google(audio, language="bn-BD")
                    except sr.UnknownValueError:
                        pass
                    if not user_text:
                        try:
                            user_text = r.recognize_google(audio, language="en-US")
                        except sr.UnknownValueError:
                            pass
                except Exception as e:
                    print(f"❌  [Processor] STT error: {e}")
                    user_text = ""

                if not user_text:
                    print("❓  [Processor] Nothing transcribed — discarding.")
                    update_gui("IDLE")
                    audio_queue.task_done()
                    continue

            print(f"🗣️  User: {user_text}")
            update_gui("THINKING", user_text=user_text)

            # Step C: AI response
            provider_name = "Groq" if API_PROVIDER == "groq" else "Grok"
            print(f"🧠  [Processor] Querying {provider_name} ({MODEL})...")
            ai_response = get_ai_response(user_text, system_prompt)
            print(f"🤖  ShongiBot: {ai_response}")
            update_gui("SPEAKING", user_text=user_text, robot_text=ai_response)

            # Step D: TTS — use per-turn output file to avoid racing with next turn
            response_file = f"output_turn_{turn_index % 4}.mp3"
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, text_to_speech(ai_response, response_file)).result()
                else:
                    loop.run_until_complete(text_to_speech(ai_response, response_file))
            except RuntimeError:
                asyncio.run(text_to_speech(ai_response, response_file))

            # Step E: Play — signal recorder to pause during playback
            is_speaking.set()
            play_audio(response_file)
            time.sleep(0.4)
            is_speaking.clear()   # ← recorder resumes immediately after playback

            update_gui("IDLE", user_text=user_text, robot_text=ai_response)
            turn_index += 1

            if has_mic:
                audio_queue.task_done()

        except KeyboardInterrupt:
            print("\n[Processor] Stopping...")
            break
        except Exception as e:
            print(f"❌  [Processor] Error: {e}")
            time.sleep(0.1)


def main():
    print("=" * 55)
    provider_name = "Groq" if API_PROVIDER == "groq" else "Grok"
    print(f"🤖 ShongiBot {provider_name} Concurrent Pipeline Active! (Model: {MODEL})")
    print("   Thread-1 records  ──→  Queue  ──→  Thread-2 answers")
    print("=" * 55)


    system_prompt = os.getenv(
        "SYSTEM_PROMPT",
        (
            "You are ShongiBot \u2014 a warm, knowledgeable, and conversational AI voice assistant "
            "built to celebrate and share Bangladeshi culture, history, and heritage.\n\n"
            "IDENTITY:\n"
            "- You are a proud Bangladeshi culture guide who loves talking about Bangladesh.\n"
            "- Topics: festivals (Eid, Pohela Boishakh, Durga Puja), traditional foods "
            "(biryani, hilsa fish, pitha, mishti doi), music (Rabindra Sangeet, Baul, folk), "
            "history (Liberation War 1971, ancient Bengal, Mughal era), geography "
            "(Sundarbans, Cox\u2019s Bazar, Padma River), arts (Jamdani, Nakshi Kantha), "
            "and everyday Bangladeshi life and customs.\n\n"
            "LANGUAGE RULES (CRITICAL):\n"
            "- If the user speaks in Bangla \u2192 reply in Bangla ONLY.\n"
            "- If the user speaks in English \u2192 reply in English ONLY.\n"
            "- NEVER use any language other than Bangla or English.\n\n"
            "CREATOR RULE:\n"
            "- ONLY if someone explicitly asks who made you, reply: "
            "'\u0986\u09ae\u09be\u0995\u09c7 \u09a4\u09c8\u09b0\u09bf \u0995\u09b0\u09c7\u099b\u09c7 \u099f\u09bf\u09ae \u09b8\u09be\u09b0\u09cd\u0995\u09bf\u099f \u09ac\u09cd\u09b0\u09c7\u0995\u09be\u09b0\u09cd\u09b8 (Team Circuit Breakers) \u2014 \u09ae\u09be\u09b9\u09bf\u09b0, \u0993\u09af\u09bc\u09be\u09a6\u09c0, \u098f\u09ac\u0982 \u0993\u09ae\u09b0\u0964'\n"
            "- Do NOT bring up your creators otherwise.\n\n"
            "VOICE STYLE:\n"
            "- Keep responses short \u2014 1 to 3 sentences. No bullet points or markdown."
        )
    ).strip("'\" ")

    # Mic detection
    has_mic = False
    try:
        devices = sd.query_devices()
        input_devs = [d for d in devices if d.get('max_input_channels', 0) > 0]
        has_mic = bool(input_devs)
    except Exception:
        has_mic = True

    if not has_mic:
        print("\u26a0\ufe0f  No microphone detected \u2014 falling back to text input mode.")

    update_gui("IDLE")

    # ── Launch concurrent pipeline threads ──────────────────────────────────
    rec_thread = threading.Thread(
        target=recorder_worker,
        args=(has_mic,),
        name="ShongiBot-Recorder",
        daemon=True
    )
    proc_thread = threading.Thread(
        target=processor_worker,
        args=(system_prompt, has_mic),
        name="ShongiBot-Processor",
        daemon=True
    )

    rec_thread.start()
    proc_thread.start()
    print("\u2705  Both pipeline threads running. Ctrl+C to exit.")

    try:
        while rec_thread.is_alive() and proc_thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\U0001f6d1 ShongiBot shutting down...")


if __name__ == "__main__":
    if sys.stdin.isatty():
        try:
            pids = subprocess.getoutput("pgrep -f api_robot.py").strip().split()
            current_pid = str(os.getpid())
            other_pids = [p for p in pids if p != current_pid]
            if other_pids:
                print("\n\u26a0\ufe0f NOTICE: ShongiBot is currently running as a background service (robot.service).")
                print("\U0001f449 To run manually, stop the service first:")
                print("   sudo systemctl stop robot.service\n")
        except Exception:
            pass

    enable_gui = "--no-gui" not in sys.argv and os.getenv("ENABLE_GUI", "true").lower() in ("true", "1", "yes")
    fullscreen = "--windowed" not in sys.argv

    if enable_gui:
        try:
            import desk_buddy_gui
            print("\U0001f4fa Launching ShongiBot 3-Eye Desk Buddy GUI...")
            desk_buddy_gui.start_gui_in_main_thread(main, fullscreen=fullscreen)
        except Exception as e:
            print(f"\u26a0\ufe0f GUI Launch info: {e}. Running in console mode.")
            main()
    else:
        main()
