"""
Prometheus özel metrikleri — /metrics endpoint üzerinden Grafana'ya beslenir.

Otomatik HTTP metrikler prometheus-fastapi-instrumentator tarafından eklenir.
Bu modül domain-specific metrikler içerir.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

qod_sessions_total = Counter(
    "qod_sessions_created_total",
    "Oluşturulan CAMARA QoD oturumu sayısı",
)

events_recorded_total = Counter(
    "events_recorded_total",
    "SQLite'a kaydedilen risk olayı sayısı",
)

ws_active_connections = Gauge(
    "ws_active_connections",
    "Anlık aktif WebSocket bağlantısı sayısı",
    labelnames=["endpoint"],
)

frame_inference_ms = Histogram(
    "frame_inference_duration_ms",
    "YZ pipeline çıkarım süresi (ms)",
    buckets=[5, 10, 25, 50, 75, 100, 150, 200, 300, 500],
)

frame_total_latency_ms = Histogram(
    "frame_total_latency_ms",
    "Uçtan uca kare gecikme süresi — client_ts varsa ağ dahil (ms)",
    buckets=[10, 25, 50, 75, 100, 150, 200, 300, 500, 1000],
)
