/**
 * Backend istemcisi — dinamik sunucu IP destekli.
 * LoginScreen'de sunucu adresi girilir, buradan tüm istemler kullanır.
 *
 * Varsayılan: 192.168.1.20:8000 (aynı Wi-Fi'deki Mac)
 * `ipconfig getifaddr en0` komutu ile Mac LAN IP'sini öğrenebilirsin.
 */
let _base = "http://192.168.1.20:8000";

export function setApiBase(host: string) {
  const cleaned = host.trim().replace(/\/$/, "");
  _base = cleaned.startsWith("http") ? cleaned : `http://${cleaned}`;
}

export function getApiBase() { return _base; }
export function getWsIngest() { return _base.replace(/^http/, "ws") + "/ws/ingest"; }

export async function silentVerify(deviceToken: string, phoneNumber: string) {
  const r = await fetch(`${_base}/camara/number-verification:verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_token: deviceToken, phone_number: phoneNumber }),
  });
  return r.json() as Promise<{ devicePhoneNumberVerified: boolean; token: string | null }>;
}

export async function fetchEvents(minScore = 30, limit = 20) {
  const r = await fetch(`${_base}/api/events?min_score=${minScore}&limit=${limit}`);
  return r.json();
}

export async function fetchQoDStatus() {
  const r = await fetch(`${_base}/api/qod/status`);
  return r.json();
}

export async function health() {
  const r = await fetch(`${_base}/api/health`);
  return r.json();
}
