"""
Mock CAMARA Number Verification API (sessiz SIM doğrulama).

Şartname: "SMS bekleme süresi veya manuel kod girişi olmadan, şebeke tabanlı,
güvenli ve sessiz doğrulama". Bu mock, çekirdek şebekenin SIM↔numara eşleşmesini
arka planda doğrulamasını taklit eder. Final yarışmada Turkcell gerçek doğrulamayı
sağlar; uygulama tarafı aynı arayüzü kullanmaya devam eder.

CAMARA sözleşmesi:
  POST /number-verification:verify   { phoneNumber }  (Authorization: device token)
  -> { devicePhoneNumberVerified: bool, token: <RS256 JWT> }

Token üretimi: backend/auth.py içindeki JWTManager.issue() (RS256) kullanılır.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# Mock operatör kaydı: device_token -> hat numarası (gerçekte çekirdek şebeke bilir)
_MOCK_SIM_REGISTRY: Dict[str, str] = {
    "device-demo-token": "+905551112233",
    "device-guard-01": "+905320001122",
    "device-guard-02": "+905340001133",
}


def _normalize_msisdn(num: str) -> str:
    n = re.sub(r"[^\d+]", "", num or "")
    if n.startswith("0"):
        n = "+90" + n[1:]
    elif n.startswith("90"):
        n = "+" + n
    elif n.startswith("5"):
        n = "+90" + n
    return n


class MockNumberVerification:
    def verify(self, device_token: str, claimed_number: str) -> bool:
        """Cihazdaki SIM'in beyan edilen numarayla eşleşip eşleşmediğini döner."""
        registered = _MOCK_SIM_REGISTRY.get(device_token)
        if registered is None:
            return False
        return _normalize_msisdn(registered) == _normalize_msisdn(claimed_number)

    def device_phone_number(self, device_token: str) -> Optional[str]:
        """CAMARA :device-phone-number — SIM'in numarasını şebekeden alır (sessiz)."""
        return _MOCK_SIM_REGISTRY.get(device_token)
