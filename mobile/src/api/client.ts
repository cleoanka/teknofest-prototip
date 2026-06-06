import { StoredEvent } from "../types";

let _baseUrl = "";
let _token = "";

export function setCredentials(url: string, token: string) {
  _baseUrl = url.replace(/\/+$/, "");
  _token = token;
}

export function getBaseUrl(): string { return _baseUrl; }

export function getWsIngest(): string {
  return _baseUrl.replace(/^https?/, (p) => (p === "https" ? "wss" : "ws")) + "/ws/ingest";
}

// ── Hata tipi ─────────────────────────────────────────────────────────────

export type ApiErrorKind = "network" | "auth" | "server" | "timeout";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly kind: ApiErrorKind = "server",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ── Merkezi fetch sarmalayıcısı ────────────────────────────────────────────

const TIMEOUT_MS = 8_000;

async function apiFetch(url: string, options?: RequestInit): Promise<any> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const r = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options?.headers ?? {}),
        ...(_token ? { Authorization: `Bearer ${_token}` } : {}),
      },
    });
    clearTimeout(timer);

    if (r.status === 401 || r.status === 403) {
      throw new ApiError("Oturum süresi doldu, tekrar giriş yapın.", r.status, "auth");
    }
    if (!r.ok) {
      throw new ApiError(`Sunucu hatası (${r.status})`, r.status, "server");
    }
    return r.json();
  } catch (e) {
    clearTimeout(timer);
    if (e instanceof ApiError) throw e;
    if ((e as any)?.name === "AbortError") {
      throw new ApiError("Bağlantı zaman aşımına uğradı.", undefined, "timeout");
    }
    throw new ApiError(
      "Sunucuya ulaşılamıyor. Wi-Fi bağlantısını kontrol et.",
      undefined,
      "network",
    );
  }
}

// ── API çağrıları ──────────────────────────────────────────────────────────

export async function fetchEvents(minScore = 0, limit = 50): Promise<StoredEvent[]> {
  return apiFetch(`${_baseUrl}/api/events?min_score=${minScore}&limit=${limit}`);
}

export async function verifyConnection(url: string, token: string): Promise<void> {
  const base = url.replace(/\/+$/, "");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5_000);
  try {
    const r = await fetch(`${base}/api/health`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!r.ok) throw new ApiError(`Sunucu hatası (${r.status})`, r.status, "server");
  } catch (e) {
    clearTimeout(timer);
    if (e instanceof ApiError) throw e;
    if ((e as any)?.name === "AbortError") {
      throw new ApiError("Sunucuya ulaşılamadı — zaman aşımı.", undefined, "timeout");
    }
    throw new ApiError(
      "Sunucuya ulaşılamıyor. Wi-Fi bağlantısını kontrol et.",
      undefined,
      "network",
    );
  }
}
