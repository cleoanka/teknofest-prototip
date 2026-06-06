/**
 * REST istemcisi — merkezi fetch sarmalayıcı, hata sınıflandırma, token yönetimi.
 * Sunucu adresi ve token modül seviyesinde tutulur; tüm uygulama paylaşır.
 */
import { DEFAULT_API_BASE } from "../config/env";
import type {
  HealthInfo, StatusFrame, Statistics, QoDProof,
  EventRecord, HourlySummary, HeatmapRow, VerifyResponse,
} from "../types/api";

// ── Paylaşılan durum ──────────────────────────────────────────────────────────
let _base = DEFAULT_API_BASE;
let _token: string | null = null;

export function setApiBase(host: string) {
  const cleaned = host.trim().replace(/\/+$/, "");
  _base = cleaned.startsWith("http") ? cleaned : `http://${cleaned}`;
}
export function getApiBase(): string { return _base; }

export function setToken(token: string | null) { _token = token; }
export function getToken(): string | null { return _token; }

/** WS URL'i üret: http→ws, https→wss + token query. */
export function wsUrl(path: string): string {
  const wsBase = _base.replace(/^http/, "ws");
  const q = _token ? `?token=${encodeURIComponent(_token)}` : "";
  return `${wsBase}${path}${q}`;
}

// ── Hata tipleri ──────────────────────────────────────────────────────────────
export type ApiErrorKind = "network" | "timeout" | "auth" | "server" | "parse";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: ApiErrorKind,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ── Çekirdek fetch ────────────────────────────────────────────────────────────
const TIMEOUT_MS = 8000;

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${_base}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(_token ? { Authorization: `Bearer ${_token}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (e: any) {
    clearTimeout(timer);
    if (e?.name === "AbortError") {
      throw new ApiError("Sunucu yanıt vermedi (zaman aşımı).", "timeout");
    }
    throw new ApiError("Sunucuya ulaşılamıyor. Wi-Fi ve sunucu adresini kontrol et.", "network");
  }
  clearTimeout(timer);

  if (res.status === 401 || res.status === 403) {
    throw new ApiError("Yetki hatası — oturum doğrulanamadı.", "auth", res.status);
  }
  if (!res.ok) {
    throw new ApiError(`Sunucu hatası (${res.status}).`, "server", res.status);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("Sunucudan geçersiz yanıt alındı.", "parse");
  }
}

// ── CAMARA Number Verification ────────────────────────────────────────────────
export function verifyNumber(deviceToken: string, phoneNumber: string): Promise<VerifyResponse> {
  return apiFetch<VerifyResponse>("/camara/number-verification:verify", {
    method: "POST",
    body: JSON.stringify({ device_token: deviceToken, phone_number: phoneNumber }),
  });
}

// ── Sistem ────────────────────────────────────────────────────────────────────
export const getHealth   = () => apiFetch<HealthInfo>("/api/health");
export const getQodStatus = () => apiFetch<StatusFrame & { bandwidth_efficiency: number }>("/api/qod/status");
export const getQodProof  = () => apiFetch<QoDProof>("/api/qod/proof");
export const getStatistics = (periodS = 3600) =>
  apiFetch<Statistics>(`/api/statistics?period_s=${periodS}`);

// ── Olaylar ───────────────────────────────────────────────────────────────────
export interface EventQuery {
  limit?: number;
  offset?: number;
  minScore?: number;
  level?: string;
  vtype?: string;
  plate?: string;
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

export function getEvents(q: EventQuery = {}): Promise<EventRecord[]> {
  const p = new URLSearchParams();
  p.set("limit", String(q.limit ?? 50));
  p.set("offset", String(q.offset ?? 0));
  p.set("min_score", String(q.minScore ?? 0));
  if (q.level) p.set("level", q.level);
  if (q.vtype) p.set("vtype", q.vtype);
  if (q.plate) p.set("plate", q.plate);
  p.set("sort_by", q.sortBy ?? "ts");
  p.set("sort_dir", q.sortDir ?? "desc");
  return apiFetch<EventRecord[]>(`/api/events?${p.toString()}`);
}

export const getEventsSummary = (hours = 24) =>
  apiFetch<{ hours: number; summary: HourlySummary[] }>(`/api/events/summary?hours=${hours}`);

export const getHeatmap = (hours = 24) =>
  apiFetch<{ hours: number; levels: string[]; rows: HeatmapRow[]; total_events: number }>(
    `/api/events/heatmap?hours=${hours}`,
  );
