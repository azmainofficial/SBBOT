import sys
import paramiko

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PI_IP = "172.31.17.70"
PI_USER = "sb"
PI_PASS = "123"

DESKTOP_ENTRY_CONTENT = """[Desktop Entry]
Type=Application
Name=ShongiBot 3-Eye Desk Buddy
Comment=ShongiBot AI Voice Robot 3-Eye GUI
Exec=/home/sb/SongiBot/venv/bin/python3 /home/sb/SongiBot/api_robot.py
WorkingDirectory=/home/sb/SongiBot
Terminal=false
X-GNOME-Autostart-enabled=true
"""

ROBOT_SERVICE_CONTENT = """[Unit]
Description=ShongiBot AI Voice Service & 3-Eye GUI
After=network-online.target graphical.target
Wants=network-online.target

[Service]
User=sb
WorkingDirectory=/home/sb/SongiBot
EnvironmentFile=/home/sb/SongiBot/.env
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/sb/.Xauthority
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/sb/SongiBot/venv/bin/python3 /home/sb/SongiBot/api_robot.py
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
"""

def main():
    print("=" * 60)
    print("🚀 Configuring 3-Eye Desk Buddy GUI Auto-Start on Raspberry Pi...")
    print("=" * 60)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_IP, username=PI_USER, password=PI_PASS, timeout=10)

    # 1. Update Desktop Autostart File (~/.config/autostart/shongibot.desktop)
    print("[1] Updating ~/.config/autostart/shongibot.desktop...")
    client.exec_command("mkdir -p /home/sb/.config/autostart")
    sftp = client.open_sftp()
    with sftp.file("/home/sb/.config/autostart/shongibot.desktop", "w") as f:
        f.write(DESKTOP_ENTRY_CONTENT)
    sftp.close()
    print("✅ Desktop Autostart entry updated!")

    # 2. Update Systemd robot.service (/etc/systemd/system/robot.service)
    print("\n[2] Updating /etc/systemd/system/robot.service with DISPLAY=:0...")
    sftp = client.open_sftp()
    with sftp.file("/tmp/robot.service", "w") as f:
        f.write(ROBOT_SERVICE_CONTENT)
    sftp.close()

    client.exec_command(f"echo {PI_PASS} | sudo -S mv /tmp/robot.service /etc/systemd/system/robot.service")
    client.exec_command(f"echo {PI_PASS} | sudo -S chmod 644 /etc/systemd/system/robot.service")
    client.exec_command(f"echo {PI_PASS} | sudo -S systemctl daemon-reload")
    client.exec_command(f"echo {PI_PASS} | sudo -S systemctl enable robot.service")
    client.exec_command(f"echo {PI_PASS} | sudo -S systemctl restart robot.service")
    print("✅ robot.service systemd unit reloaded & enabled!")

    # Verify status
    stdin, stdout, stderr = client.exec_command("systemctl status robot.service --no-pager -l")
    print("\n[STATUS] Current robot.service status:")
    print(stdout.read().decode('utf-8', errors='ignore'))

    client.close()
    print("\n🎉 3-Eye Desk Buddy GUI Auto-Start setup completed!")

if __name__ == "__main__":
    main()
