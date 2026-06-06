/**
 * Backend şemasının (ai/schema.py) TypeScript yansıması.
 * WS /ws/ingest ve REST /api/* yanıtları bu tiplere uyar.
 */

export type Mode = "NORMAL" | "CRITICAL";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface BBox { x1: number; y1: number; x2: number; y2: number; }

export interface Detection {
  label: string;
  confidence: number;
  bbox: BBox;
  track_id?: number | null;
  attributes?: Record<string, string>;
}

export interface PlateResult {
  text: string | null;
  confidence: number;
  valid_format: boolean;
}

export interface DriverState {
  fatigue: boolean;
  ear: number | null;
  perclos: number | null;
  phone_use: boolean;
  smoking: boolean;
  no_seatbelt: boolean;
  headphone: boolean;
  passenger_phone: boolean;
}

export interface Vehicle {
  present: boolean;
  track_id?: number | null;
  vtype: string | null;
  color: string | null;
  plate: PlateResult;
  speed_kmh: number | null;
  bbox: BBox | null;
  plate_bbox?: BBox | null;
  driver_bbox?: BBox | null;
  passenger_bbox?: BBox | null;
  swerving?: boolean;
}

export interface RiskAssessment {
  score: number;
  level: RiskLevel | string;
  factors: string[];
}

export interface QoDStatus {
  mode: Mode;
  bandwidth_mbps: number;
  active_session_id: string | null;
  last_trigger_reason: string | null;
  session_age_s: number;
}

/** WS /ws/ingest üzerinden her karede dönen ana mesaj. */
export interface FrameResult {
  frame_id: number;
  ts: number;
  mode: Mode;
  model_profile: string;
  detections: Detection[];
  vehicle: Vehicle;
  driver: DriverState;
  risk: RiskAssessment;
  qod: QoDStatus;
  latency_ms: number;
  total_latency_ms: number;
  fps: number;
}

/** /api/events ile dönen kalıcı olay kaydı. */
export interface EventRecord {
  id: number | null;
  ts: number;
  plate: string | null;
  vtype: string | null;
  speed_kmh: number | null;
  risk_score: number;
  risk_level: RiskLevel | string;
  factors: string;       // virgülle ayrık
  mode: string;
  snapshot?: string | null;
}

/** /ws/status — 1 sn aralıkla yayınlanan sistem durumu. */
export interface StatusFrame {
  ts: number;
  qod_mode: Mode;
  bandwidth_mbps: number;
  active_session_id: string | null;
  event_count: number;
  ws_connections: number;
  bandwidth_efficiency: number;
  uptime_s: number;
}

/** /api/health */
export interface HealthInfo {
  status: string;
  ai_mode: string;
  detector: string;
  qod_mode: Mode;
  version: string;
  uptime_s: number;
  event_count: number;
  ws_connections: number;
}

/** /api/statistics */
export interface Statistics {
  count?: number;
  high_risk_count?: number;
  avg_speed_kmh?: number | null;
  level_distribution?: Record<string, number>;
  qod_trigger_count: number;
  bandwidth_efficiency: number;
  qod_mode: Mode;
  bandwidth_mbps: number;
  [k: string]: unknown;
}

/** /api/qod/proof — %40 bant verimliliği kanıtı (jüri kriteri). */
export interface QoDProof {
  criterion: string;
  target_efficiency_pct: number;
  measured_efficiency_pct: number;
  meets_criterion: boolean;
  total_qod_cycles: number;
  critical_mode_cycles: number;
  normal_mode_cycles: number;
  normal_bandwidth_mbps: number;
  critical_bandwidth_mbps: number;
  current_mode: Mode;
  active_session_id: string | null;
  camara_mode: string;
  qod_triggers: string[];
}

/** /api/events/summary — saatlik özet satırı. */
export interface HourlySummary {
  hour_offset?: number;
  hour?: string;
  count: number;
  avg_score?: number | null;
  max_score?: number | null;
  [k: string]: unknown;
}

/** /api/events/heatmap satırı. */
export interface HeatmapRow {
  hour_offset: number;
  LOW: number;
  MEDIUM: number;
  HIGH: number;
  CRITICAL: number;
}

/** Number Verification yanıtı. */
export interface VerifyResponse {
  devicePhoneNumberVerified: boolean;
  token: string | null;
}
