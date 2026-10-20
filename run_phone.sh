#!/data/data/com.termux/files/usr/bin/bash
# הרצה בטלפון (Termux)

echo "[*] מתקין פייתון..."
pkg install -y python

echo "[*] מתקין חבילות..."
pip install --upgrade pip
pip install requests

echo "[*] מפעיל..."
cd "$(dirname "$0")"
python bomber.py
