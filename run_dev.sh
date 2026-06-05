#!/usr/bin/env bash
# Geliştirme sunucusu — start / stop / restart / status / logs
set -e
cd "$(dirname "$0")"

PID_FILE=".server.pid"
LOG_FILE="server.log"
CMD="python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"

_setup() {
  if [ ! -d ".venv" ]; then
    echo "» Sanal ortam oluşturuluyor…"
    python3 -m venv .venv
  fi
  source .venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
  export AI_MODE="${AI_MODE:-auto}"
}

_banner() {
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
  echo ""
  echo "════════════════════════════════════════════════════════════════"
  echo "  Akıllı Yol Güvenliği — 5G & YZ Prototip"
  echo "  Web dashboard :  http://localhost:8000/"
  echo "  Telefondan    :  http://${LAN_IP:-<IP>}:8000/  (aynı Wi-Fi)"
  echo "  Sağlık        :  http://localhost:8000/api/health"
  echo "════════════════════════════════════════════════════════════════"
  echo ""
}

_is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-fg}" in

  # ── Arka planda başlat ──────────────────────────────────────────────
  start)
    if _is_running; then
      echo "⚠  Sunucu zaten çalışıyor (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    _setup
    _banner
    echo "» Sunucu arka planda başlatılıyor → log: $LOG_FILE"
    nohup bash -c "source .venv/bin/activate && export AI_MODE=${AI_MODE:-auto} && $CMD" \
      > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if _is_running; then
      echo "✓  Çalışıyor (PID $(cat "$PID_FILE"))"
    else
      echo "✗  Başlatılamadı — son log:"
      tail -20 "$LOG_FILE"
      exit 1
    fi
    ;;

  # ── Durdur ─────────────────────────────────────────────────────────
  stop)
    if _is_running; then
      PID=$(cat "$PID_FILE")
      kill "$PID" 2>/dev/null && echo "✓  Durduruldu (PID $PID)"
      rm -f "$PID_FILE"
    else
      echo "⚠  Çalışan sunucu bulunamadı"
    fi
    ;;

  # ── Yeniden başlat ─────────────────────────────────────────────────
  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;

  # ── Durum ──────────────────────────────────────────────────────────
  status)
    if _is_running; then
      echo "✓  Çalışıyor (PID $(cat "$PID_FILE"))"
      echo "   Log: $LOG_FILE"
    else
      echo "✗  Çalışmıyor"
    fi
    ;;

  # ── Log izle ───────────────────────────────────────────────────────
  logs)
    [ -f "$LOG_FILE" ] && tail -f "$LOG_FILE" || echo "Log dosyası yok: $LOG_FILE"
    ;;

  # ── Ön planda çalıştır (varsayılan / eski davranış) ─────────────────
  fg|"")
    _setup
    _banner
    exec $CMD
    ;;

  *)
    echo "Kullanım: $0 {start|stop|restart|status|logs|fg}"
    echo ""
    echo "  start    — arka planda başlat (log: $LOG_FILE)"
    echo "  stop     — durdur"
    echo "  restart  — yeniden başlat"
    echo "  status   — çalışıyor mu?"
    echo "  logs     — log takibi (tail -f)"
    echo "  fg       — ön planda başlat (varsayılan)"
    exit 1
    ;;
esac
