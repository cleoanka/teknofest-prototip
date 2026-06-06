/**
 * Sessiz kimlik doğrulama (CAMARA Number Verification).
 *
 * Akış: uygulama açılışında bir kez çağrılır. Cihazın SIM'i (mock'ta gömülü
 * device_token/phone_number) şebeke üzerinden doğrulanır. Kullanıcı HİÇBİR ŞEY
 * girmez. Başarılıysa RS256 JWT alınır ve sonraki tüm REST/WS çağrılarında kullanılır.
 *
 * Soft fallback davranışı için bkz. config/env.ts → AUTH.softFallback.
 */
import { AUTH } from "../config/env";
import { verifyNumber, setToken, ApiError } from "./client";

export type AuthMode =
  | "verified"            // gerçek doğrulama başarılı, token alındı
  | "fallback-unverified" // doğrulama reddedildi ama fallback ile geçildi
  | "fallback-offline";   // sunucuya ulaşılamadı ama fallback ile geçildi

export interface AuthOk {
  ok: true;
  mode: AuthMode;
  token: string | null;
}
export interface AuthFail {
  ok: false;
  reason: string;
  kind: ApiErrorKind | "rejected";
}
export type AuthResult = AuthOk | AuthFail;

// client.ts'deki ApiErrorKind'i tekrar import etmemek için lokal alias
type ApiErrorKind = "network" | "timeout" | "auth" | "server" | "parse";

/**
 * Sessiz doğrulamayı yürütür. Sonuç UI'ya hangi modda olduğumuzu bildirir,
 * böylece fallback devredeyse kullanıcı/geliştirici uyarılabilir.
 */
export async function silentVerify(): Promise<AuthResult> {
  try {
    const res = await verifyNumber(AUTH.deviceToken, AUTH.phoneNumber);

    if (res.devicePhoneNumberVerified && res.token) {
      setToken(res.token);
      return { ok: true, mode: "verified", token: res.token };
    }

    // Sunucuya ulaşıldı ama doğrulama reddedildi (SIM eşleşmedi vb.)
    setToken(null);
    if (AUTH.softFallback) {
      return { ok: true, mode: "fallback-unverified", token: null };
    }
    return { ok: false, reason: "Numara doğrulanamadı (SIM eşleşmedi).", kind: "rejected" };
  } catch (e) {
    // Ağ / sunucu / zaman aşımı hatası
    setToken(null);
    const kind = e instanceof ApiError ? e.kind : "network";
    const msg = e instanceof ApiError ? e.message : "Beklenmeyen doğrulama hatası.";
    if (AUTH.softFallback) {
      return { ok: true, mode: "fallback-offline", token: null };
    }
    return { ok: false, reason: msg, kind };
  }
}

/** Fallback modunda mıyız? Sistem sekmesindeki uyarı rozeti için. */
export function isFallbackMode(mode: AuthMode): boolean {
  return mode !== "verified";
}
