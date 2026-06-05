#!/usr/bin/env bash
# Geliştirme sunucusu — backend + web dashboard'u tek komutla başlatır.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "» Sanal ortam oluşturuluyor…"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "» Bağımlılıklar kuruluyor (ilk çalıştırmada birkaç dakika sürebilir)…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Akıllı Yol Güvenliği — 5G & YZ Prototip"
echo "  Web dashboard :  http://localhost:8000/"
echo "  Telefondan    :  http://${LAN_IP:-<MAC-IP>}:8000/  (aynı Wi-Fi)"
echo "  Sağlık        :  http://localhost:8000/api/health"
echo "════════════════════════════════════════════════════════════════"
echo ""

# AI_MODE=auto -> ultralytics/easyocr/mediapipe kuruluysa gerçek model, değilse mock
export AI_MODE="${AI_MODE:-auto}"
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
