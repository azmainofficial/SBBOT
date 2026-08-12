import os
import sys
import time
import asyncio
import subprocess
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


async def text_to_speech(text):
    """Generates neural voice output using Microsoft Edge-TTS."""
    # Detect if the generated text contains Bengali characters to select the correct voice
    has_bengali = any(0x0980 <= ord(char) <= 0x09FF for char in text)
    voice = "bn-BD-NabanitaNeural" if has_bengali else "en-US-EmmaNeural"
    
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(RESPONSE_AUDIO)

def update_gui(state, user_text="", robot_text=""):
    """Helper to update Desk Buddy GUI state across threads."""
    try:
        import desk_buddy_gui
        if desk_buddy_gui.gui_instance:
            desk_buddy_gui.gui_instance.set_state(state, user_text, robot_text)
    except Exception:
        pass

def main():
    print("=" * 50)
    provider_name = "Groq" if API_PROVIDER == "groq" else "Grok"
    print(f"🤖 ShongiBot {provider_name} Engine Active! (Model: {MODEL})")
    print("=" * 50)


    system_prompt = os.getenv(
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

    # Bug Fix #2: Correctly detect if any microphone/input device is available
    has_mic = False
    try:
        devices = sd.query_devices()
        input_devs = [
            d for d in devices
            if d.get('max_input_channels', 0) > 0
        ]
        if input_devs:
            has_mic = True
        else:
            has_mic = False
    except Exception:
        # If sounddevice itself fails, assume mic present to avoid false text-mode
        has_mic = True

    if not has_mic:
        print("⚠️ Warning: No audio input device (microphone) detected.")
        print("👉 Falling back to Text Input mode. You can type your questions, and ShongiBot will speak the response!")

    update_gui("IDLE")

    while True:
        try:
            user_text = ""
            
            if not has_mic:
                if sys.stdin.isatty():
                    user_text = input("\n👉 Type your message: ").strip()
                    if not user_text:
                        continue
                else:
                    print("Running in headless mode without microphone.")
                    time.sleep(10)
                    continue
            else:
                if not ALWAYS_ON_MIC and sys.stdin.isatty():
                    input("\n👉 Press ENTER to start talking (or Ctrl+C to exit)...")

                # Step A: Dynamic Voice Activity Detection & Recording
                update_gui("LISTENING")
                rms_energy = record_audio(max_duration=10, silence_timeout=0.8)
                if rms_energy <= 0.0:
                    update_gui("IDLE")
                    time.sleep(0.1)
                    continue

                # Step B: Speech-to-Text
                update_gui("THINKING")
                user_text = transcribe_audio()
                if not user_text:
                    print("❓ No speech transcribed. Listening again...")
                    update_gui("IDLE")
                    continue

            print(f"🗣️ User: {user_text}")
            update_gui("THINKING", user_text=user_text)

            # Step C: LLM Brain via AI Provider
            provider_name = "Groq" if API_PROVIDER == "groq" else "Grok"
            print(f"🧠 Processing response via {provider_name} ({MODEL})...")
            ai_response = get_ai_response(user_text, system_prompt)
            print(f"🤖 Robot: {ai_response}")
            update_gui("SPEAKING", user_text=user_text, robot_text=ai_response)

            # Step D: Text-to-Speech
            # Bug Fix #4: Safely run async TTS — avoid RuntimeError if loop already running
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(text_to_speech(ai_response))
                else:
                    loop.run_until_complete(text_to_speech(ai_response))
            except RuntimeError:
                asyncio.run(text_to_speech(ai_response))

            # Step E: Play Audio
            play_audio(RESPONSE_AUDIO)
            time.sleep(0.5)  # Allow ALSA driver to release soundcard locks
            update_gui("IDLE", user_text=user_text, robot_text=ai_response)

        except KeyboardInterrupt:
            print("\nExiting ShongiBot...")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    if sys.stdin.isatty():
        try:
            pids = subprocess.getoutput("pgrep -f api_robot.py").strip().split()
            current_pid = str(os.getpid())
            other_pids = [p for p in pids if p != current_pid]
            if other_pids:
                print("\n⚠️ NOTICE: ShongiBot is currently running as a background service (robot.service).")
                print("👉 To run manually with interactive GUI, stop the background service first:")
                print("   sudo systemctl stop robot.service\n")
        except Exception:
            pass

    enable_gui = "--no-gui" not in sys.argv and os.getenv("ENABLE_GUI", "true").lower() in ("true", "1", "yes")
    fullscreen = "--windowed" not in sys.argv
    
    if enable_gui:
        try:
            import desk_buddy_gui
            print("📺 Launching ShongiBot 3-Eye Desk Buddy GUI...")
            desk_buddy_gui.start_gui_in_main_thread(main, fullscreen=fullscreen)
        except Exception as e:
            print(f"⚠️ GUI Launch info: {e}. Running in console mode.")
            main()
    else:
        main()
