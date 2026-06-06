import { FrameResult } from "../types";

/** Kamera önizlemesinde gerçekçi görünmesi için sabit bbox koordinatları */
const CAR_BBOX  = { x1: 60,  y1: 90,  x2: 300, y2: 210 };
const FACE_BBOX = { x1: 130, y1: 95,  x2: 210, y2: 175 };
const PHONE_BBOX = { x1: 140, y1: 130, x2: 195, y2: 170 };

function base(overrides: Partial<FrameResult>): FrameResult {
  return {
    frame_id: Math.floor(Math.random() * 10_000),
    ts: Date.now() / 1000,
    mode: "NORMAL",
    model_profile: "yolov8n",
    detections: [
      { label: "vehicle", confidence: 0.91, bbox: CAR_BBOX, track_id: 1 },
    ],
    vehicle: {
      present: true, vtype: "sedan", color: "gri",
      plate: { text: "34 ABC 123", confidence: 0.95, valid_format: true },
      speed_kmh: 72, bbox: CAR_BBOX,
    },
    driver: {
      fatigue: false, ear: 0.31, perclos: 0.08,
      phone_use: false, smoking: false, no_seatbelt: false, headphone: false,
    },
    risk: { score: 0, level: "LOW", factors: [] },
    qod: {
      mode: "NORMAL", bandwidth_mbps: 5,
      active_session_id: null, last_trigger_reason: null, session_age_s: 0,
    },
    latency_ms: 38,
    fps: 4.9,
    ...overrides,
  } as FrameResult;
}

/**
 * 6 karelik senaryo döngüsü.
 * Sırasıyla: normal yol → hız aşımı → dikkat dağınıklığı → QoD tetik → kritik tepe → normale dönüş
 * Her kare 2 saniyede bir gösterilir → tam tur ~12 saniye.
 */
export const MOCK_FRAMES: FrameResult[] = [

  // 1 — Normal, düşük risk
  base({
    risk: { score: 12, level: "LOW", factors: [] },
    vehicle: { present: true, vtype: "sedan", color: "gri",
      plate: { text: "34 ABC 123", confidence: 0.95, valid_format: true },
      speed_kmh: 62, bbox: CAR_BBOX },
  }),

  // 2 — Hız biraz yüksek, orta risk
  base({
    risk: { score: 38, level: "MEDIUM", factors: ["speeding"] },
    vehicle: { present: true, vtype: "SUV", color: "beyaz",
      plate: { text: "06 XY 987", confidence: 0.88, valid_format: true },
      speed_kmh: 98, bbox: CAR_BBOX },
    detections: [
      { label: "vehicle", confidence: 0.94, bbox: CAR_BBOX, track_id: 1 },
    ],
  }),

  // 3 — Telefon kullanımı tespit edildi, yüksek risk
  base({
    risk: { score: 63, level: "HIGH", factors: ["phone_use", "speeding"] },
    vehicle: { present: true, vtype: "sedan", color: "siyah",
      plate: { text: "35 KLM 44", confidence: 0.91, valid_format: true },
      speed_kmh: 105, bbox: CAR_BBOX },
    driver: { fatigue: false, ear: 0.28, perclos: 0.12,
      phone_use: true, smoking: false, no_seatbelt: false, headphone: false },
    detections: [
      { label: "vehicle", confidence: 0.93, bbox: CAR_BBOX, track_id: 1 },
      { label: "phone",   confidence: 0.82, bbox: PHONE_BBOX, track_id: 2 },
    ],
  }),

  // 4 — QoD tetiklendi, kritik eşiğini geçti
  base({
    mode: "CRITICAL",
    risk: { score: 87, level: "CRITICAL", factors: ["fatigue", "phone_use", "speeding"] },
    vehicle: { present: true, vtype: "sedan", color: "siyah",
      plate: { text: "35 KLM 44", confidence: 0.91, valid_format: true },
      speed_kmh: 112, bbox: CAR_BBOX },
    driver: { fatigue: true, ear: 0.19, perclos: 0.38,
      phone_use: true, smoking: false, no_seatbelt: true, headphone: false },
    detections: [
      { label: "vehicle", confidence: 0.96, bbox: CAR_BBOX, track_id: 1 },
      { label: "phone",   confidence: 0.85, bbox: PHONE_BBOX, track_id: 2 },
      { label: "face",    confidence: 0.79, bbox: FACE_BBOX,  track_id: 3 },
    ],
    qod: {
      mode: "CRITICAL", bandwidth_mbps: 20,
      active_session_id: "sess-demo-001", last_trigger_reason: "risk_score_85+", session_age_s: 3,
    },
    fps: 4.7, latency_ms: 28,
  }),

  // 5 — Kritik tepe — tüm etkenler aktif
  base({
    mode: "CRITICAL",
    risk: { score: 96, level: "CRITICAL", factors: ["fatigue", "phone_use", "speeding", "no_seatbelt"] },
    vehicle: { present: true, vtype: "sedan", color: "siyah",
      plate: { text: "35 KLM 44", confidence: 0.91, valid_format: true },
      speed_kmh: 119, bbox: CAR_BBOX },
    driver: { fatigue: true, ear: 0.16, perclos: 0.51,
      phone_use: true, smoking: false, no_seatbelt: true, headphone: false },
    detections: [
      { label: "vehicle", confidence: 0.97, bbox: CAR_BBOX, track_id: 1 },
      { label: "phone",   confidence: 0.88, bbox: PHONE_BBOX, track_id: 2 },
      { label: "face",    confidence: 0.81, bbox: FACE_BBOX,  track_id: 3 },
    ],
    qod: {
      mode: "CRITICAL", bandwidth_mbps: 20,
      active_session_id: "sess-demo-001", last_trigger_reason: "risk_score_85+", session_age_s: 5,
    },
    fps: 4.9, latency_ms: 26,
  }),

  // 6 — Araç çerçeveden çıktı, normale dönüş
  base({
    risk: { score: 14, level: "LOW", factors: [] },
    vehicle: { present: false, vtype: null, color: null,
      plate: { text: null, confidence: 0, valid_format: false },
      speed_kmh: null, bbox: null },
    detections: [],
    qod: {
      mode: "NORMAL", bandwidth_mbps: 5,
      active_session_id: null, last_trigger_reason: "risk_score_85+", session_age_s: 8,
    },
  }),
];
