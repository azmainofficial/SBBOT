import os
import sys
import paramiko
from dotenv import load_dotenv

# Force UTF-8 encoding for stdout on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Load .env so PI_PASS and other vars are available
load_dotenv()

PI_IP = os.getenv("PI_IP", "172.31.17.70")
PI_USER = os.getenv("PI_USER", "sb")
# Bug Fix #8: Never hardcode credentials in source. Load from .env instead.
PI_PASS = os.getenv("PI_PASS", "")
if not PI_PASS:
    print("[WARNING] PI_PASS not set in .env — SSH authentication may fail.")
REMOTE_DIR = "/home/sb/SongiBot"

FILES_TO_PUSH = [
    "api_robot.py",
    "desk_buddy_gui.py",
    "run_gui.sh",
    ".env",
    ".env.example",
    ".gitignore",
    "live_assistant.py",
    "pi.txt",
    "README.md",
    "requirements.txt",
    "deploy_pi.ps1"
]

def main():
    print("=" * 60)
    print(f"Deploying ShongiBot to Raspberry Pi ({PI_USER}@{PI_IP}:{REMOTE_DIR})...")
    print("=" * 60)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(PI_IP, username=PI_USER, password=PI_PASS, timeout=10)
        print("[OK] SSH Connection Established!")

        sftp = client.open_sftp()

        # Ensure remote directory exists
        try:
            sftp.stat(REMOTE_DIR)
        except IOError:
            print(f"[DIR] Creating remote directory {REMOTE_DIR}...")
            client.exec_command(f"mkdir -p {REMOTE_DIR}")

        # Transfer files
        for filename in FILES_TO_PUSH:
            local_path = os.path.join(os.path.dirname(__file__), filename)
            remote_path = f"{REMOTE_DIR}/{filename}"
            if os.path.exists(local_path):
                print(f"[PUSH] Uploading {filename} -> {remote_path}...")
                sftp.put(local_path, remote_path)

        sftp.close()
        print("\n[OK] All files uploaded successfully!")

        # Verify uploaded .env file contents on Pi
        stdin, stdout, stderr = client.exec_command(f"cat {REMOTE_DIR}/.env")
        env_content = stdout.read().decode('utf-8', errors='ignore')
        print("\n[VERIFY] Remote .env contents:")
        for line in env_content.strip().splitlines():
            if line.startswith("GROQ_API_KEY") or line.startswith("GROQ_MODEL"):
                print(f"   {line}")

        # Ensure USB webcam driver is fix-configured (prevent option driver collision)
        client.exec_command(f"echo {PI_PASS} | sudo -S sh -c 'echo \"blacklist option\" > /etc/modprobe.d/blacklist-option.conf'")
        client.exec_command(f"echo {PI_PASS} | sudo -S modprobe -r option > /dev/null 2>&1")
        client.exec_command(f"echo {PI_PASS} | sudo -S modprobe uvcvideo > /dev/null 2>&1")
        client.exec_command(f"echo {PI_PASS} | sudo -S modprobe snd-usb-audio > /dev/null 2>&1")

        # Ensure flac system dependency is installed for Google SpeechRecognition
        client.exec_command(f"echo {PI_PASS} | sudo -S apt-get install -y flac > /dev/null 2>&1")

        # Check/install requirements in remote venv if needed
        print("\n[REQS] Verifying Python requirements on Pi...")
        stdin, stdout, stderr = client.exec_command(
            f"cd {REMOTE_DIR} && if [ -d venv ]; then ./venv/bin/pip install -r requirements.txt; else pip3 install -r requirements.txt; fi"
        )
        req_out = stdout.read().decode('utf-8', errors='ignore')
        print(req_out if req_out else "Requirements check completed.")

        # 1. Disable boot run (robot.service) so it does not auto-start on boot
        print("\n[DISABLE-BOOT] Disabling and stopping robot.service...")
        client.exec_command(f"echo {PI_PASS} | sudo -S systemctl stop robot.service")
        client.exec_command(f"echo {PI_PASS} | sudo -S systemctl disable robot.service")

        # 2. Disable ~/.config/autostart/shongibot.desktop if exists
        print("[DISABLE-AUTOSTART] Removing autostart entry if exists...")
        client.exec_command("rm -f /home/sb/.config/autostart/shongibot.desktop")

        # 3. Make run_gui.sh executable
        print("[EXEC] Marking run_gui.sh executable...")
        client.exec_command(f"chmod +x {REMOTE_DIR}/run_gui.sh")

        # 4. Create Desktop launcher ShongiBot.desktop on Raspberry Pi Desktop
        print("[DESKTOP] Creating Desktop launcher ShongiBot.desktop...")
        client.exec_command("mkdir -p /home/sb/Desktop")

        desktop_entry = """[Desktop Entry]
Type=Application
Name=ShongiBot
Comment=Launch ShongiBot (Bangladesh Culture Guide)
Exec=/home/sb/SongiBot/run_gui.sh
Icon=utilities-terminal
Terminal=true
Categories=Utility;Development;
Path=/home/sb/SongiBot
"""
        sftp = client.open_sftp()
        try:
            with sftp.file("/home/sb/Desktop/ShongiBot.desktop", "w") as f:
                f.write(desktop_entry)
            print("[OK] ShongiBot.desktop created on Desktop!")
        except Exception as e:
            print(f"[WARNING] Failed to write Desktop shortcut: {e}")
        sftp.close()

        # 5. Make the Desktop shortcut executable
        client.exec_command("chmod +x /home/sb/Desktop/ShongiBot.desktop")
        # For Raspberry Pi OS Desktop (LXDE/Wayfire), mark it as trusted
        client.exec_command("gio set /home/sb/Desktop/ShongiBot.desktop metadata::trusted true >/dev/null 2>&1 || true")

        client.close()
        print("\n[SUCCESS] Deployment & Desktop Shortcut configuration completed successfully!")


    except Exception as e:
        print(f"\n[ERROR] Deployment error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
