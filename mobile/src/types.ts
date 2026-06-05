// Backend FrameResult şemasının mobil tarafı (ai/schema.py ile aynı)
export interface BBox { x1: number; y1: number; x2: number; y2: number; }
export interface Detection { label: string; confidence: number; bbox: BBox; track_id?: number; }
export interface PlateResult { text: string | null; confidence: number; valid_format: boolean; }
export interface Vehicle {
  present: boolean; vtype: string | null; color: string | null;
  plate: PlateResult; speed_kmh: number | null; bbox: BBox | null;
}
export interface DriverState {
  fatigue: boolean; ear: number | null; perclos: number | null;
  phone_use: boolean; smoking: boolean; no_seatbelt: boolean; headphone: boolean;
}
export interface RiskAssessment { score: number; level: string; factors: string[]; }
export interface QoDStatus {
  mode: "NORMAL" | "CRITICAL"; bandwidth_mbps: number;
  active_session_id: string | null; last_trigger_reason: string | null; session_age_s: number;
}
export interface FrameResult {
  frame_id: number; ts: number; mode: "NORMAL" | "CRITICAL"; model_profile: string;
  detections: Detection[]; vehicle: Vehicle; driver: DriverState;
  risk: RiskAssessment; qod: QoDStatus; latency_ms: number; fps: number;
}
