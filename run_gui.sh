#!/bin/bash
echo "=========================================================="
echo "          ShongiBot — Bangladesh Culture Guide            "
echo "=========================================================="
cd /home/sb/SongiBot

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "[INFO] Activating virtual environment..."
    source venv/bin/activate
fi

echo "[INFO] Launching ShongiBot..."
python3 api_robot.py

echo ""
echo "=========================================================="
echo "Session ended. Press [ENTER] to close this window."
echo "=========================================================="
read
