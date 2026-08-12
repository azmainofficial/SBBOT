# 🤖 ShongiBot: Cloud-Powered Edge AI Voice Robot

[![Raspberry Pi](https://img.shields.io/badge/Hardware-Raspberry%20Pi%204-red.svg)](https://www.raspberrypi.org/)
[![OS](https://img.shields.io/badge/OS-Ubuntu%2024.04%20LTS-orange.svg)](https://ubuntu.com/)
[![Groq](https://img.shields.io/badge/AI%20Engine-Groq%20LPU-blue.svg)](https://groq.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**ShongiBot** is an edge-AI voice-controlled conversational robot running on a **Raspberry Pi 4 Model B (Ubuntu Server 64-bit)**. 

By offloading heavy AI processing to **Groq's Llama 3.1 8B** and **Whisper-Large-v3 APIs**, the robot achieves near-instant response latency (< 1 second) with virtually **0% CPU load** on the Pi.

---

## 🏗️ System Architecture

```text
[ User Speaks ] ──> [ USB Mic (44.1kHz WAV) ]
                           │
                           ▼
                  [ Groq Whisper API ]   (Speech-to-Text)
                           │
                           ▼
               [ Groq Llama 3.1 8B API ]  (Brain / LLM)
                           │
                           ▼
                 [ Microsoft Edge-TTS ]   (Text-to-Speech)
                           │
                           ▼
               [ Universal Audio Router ] (mpg123 -> 3.5mm / USB)
                           │
                           ▼
                  [ Speaker / Headphones ]
```

## ✨ Key Features
* **⚡ Ultra-Low Latency:** Responds in under 1 second using Groq LPUs.
* **🎤 Smart Audio Input:** Captures audio from USB camera mics or external mics at native 44.1 kHz.
* **🔊 Universal Audio Switching:** Auto-detects whether sound should play through USB speakers or the Pi's 3.5mm Headphone Jack.
* **🌐 Multi-Location Wi-Fi Failover:** Uses Netplan to automatically connect to Home, Office, or Mobile Hotspot Wi-Fi networks on boot.
* **🔄 Hands-Free Auto-Boot Service:** Starts automatically upon powering on the Raspberry Pi via systemd background services (headless mode).
* **🗣️ Natural Neural Voices:** Generates realistic spoken answers using Microsoft's Edge-TTS speech engine.

## 🛠️ Hardware Requirements
| Component | Specification |
| :--- | :--- |
| **SBC** | Raspberry Pi 4 Model B (4GB / 8GB RAM) |
| **Cooling** | Active Cooling Fan + Heatsink (Mandatory) |
| **Microphone** | USB Microphone or USB Camera with built-in mic |
| **Audio Output** | 3.5mm Headphones, 3.5mm Speaker, or USB Camera Speaker |
| **Storage** | 32GB+ Class 10 MicroSD Card |
| **Power** | 5V 3A USB-C Power Supply |

## 🚀 Quick Setup Guide

### 1. System Dependencies
Log into your Ubuntu terminal on the Pi and install required packages:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git ffmpeg flac portaudio19-dev libportaudio2 alsa-utils mpg123 rfkill wireless-tools
```

### 2. Multi-Location Wi-Fi (Netplan)
Edit your Netplan configuration to save multiple Wi-Fi access points:
```bash
sudo nano /etc/netplan/50-cloud-init.yaml
```

Add your Wi-Fi networks:
```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      optional: true
      access-points:
        "Home_WiFi_Name":
          password: "Home_WiFi_Password"
        "Office_WiFi_Name":
          password: "Office_WiFi_Password"
        "Mobile_Hotspot_Name":
          password: "Hotspot_Password"
```

Apply the network configuration:
```bash
sudo netplan apply
```

### 3. Python Environment Setup
```bash
mkdir -p ~/shongibot
cd ~/shongibot
python3 -m venv robot_env
source robot_env/bin/activate
pip install groq sounddevice scipy edge-tts
```

## 💻 Python Application Code (`api_robot.py`)
Create `api_robot.py` inside `~/shongibot` (runs the voice loop, supports both Groq and Google Gemini API keys with auto-language voice switching).

## 🔄 Auto-Start on Boot (`systemd` Service)
To allow ShongiBot to run automatically when the Pi powers on:

Create a system service:
```bash
sudo nano /etc/systemd/system/robot.service
```

Add the following config (replace `<YOUR_GROQ_API_KEY>` or other keys with your actual keys):
```ini
[Unit]
Description=ShongiBot AI Voice Service
After=network-online.target
Wants=network-online.target

[Service]
User=sb
WorkingDirectory=/home/sb/SongiBot
EnvironmentFile=/home/sb/SongiBot/.env
ExecStart=/home/sb/SongiBot/venv/bin/python3 /home/sb/SongiBot/api_robot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable robot.service
sudo systemctl start robot.service
```

## 📜 System Operating Rules
1. **Active Cooling Required:** An active cooling fan is required to prevent CPU throttling on the Raspberry Pi 4.
2. **Audio Sample Rate:** Always keep audio recording sample rate set to **44100 Hz** to support USB camera microphones.
3. **Network Credentials:** Keep multiple Wi-Fi profiles configured in Netplan for automatic switching.

## 🛣️ Future Roadmap & Upgrades
- [ ] **Wake Word Integration:** Replace Push-to-Talk with openWakeWord ("Hey Shongi").
- [ ] **Voice Activity Detection (VAD):** Auto-detect when the user stops talking using Silero VAD.
- [ ] **Multimodal Vision:** Add camera vision analysis using Groq Llama 3.2 Vision.
- [ ] **Physical Movement:** Add Pan/Tilt servo motors (PCA9685 I2C) for head movement.

## 📄 License
This project is open-source under the MIT License.
