/**
 * Backend istemcisi.
 *
 * ÖNEMLİ: Telefon ile aynı Wi-Fi'deki Mac'in LAN IP'sini gir (ör. 192.168.1.20).
 * `ipconfig getifaddr en0` ile bulabilirsin. Final yarışmada bu, Turkcell 5G
 * uç noktasına işaret edecek.
 */
export const API_BASE = "http://192.168.1.20:8000"; // <-- Mac LAN IP ile değiştir
export const WS_INGEST = API_BASE.replace(/^http/, "ws") + "/ws/ingest";

export async function silentVerify(deviceToken: string, phoneNumber: string) {
  const r = await fetch(`${API_BASE}/camara/number-verification:verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_token: deviceToken, phone_number: phoneNumber }),
  });
  return r.json() as Promise<{ devicePhoneNumberVerified: boolean; token: string | null }>;
}

export async function fetchEvents(minScore = 30, limit = 20) {
  const r = await fetch(`${API_BASE}/api/events?min_score=${minScore}&limit=${limit}`);
  return r.json();
}

export async function fetchQoDStatus() {
  const r = await fetch(`${API_BASE}/api/qod/status`);
  return r.json();
}

export async function health() {
  const r = await fetch(`${API_BASE}/api/health`);
  return r.json();
}
