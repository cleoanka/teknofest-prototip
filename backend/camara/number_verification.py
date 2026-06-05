"""
Mock CAMARA Number Verification API (sessiz SIM doğrulama).

Şartname: "SMS bekleme süresi veya manuel kod girişi olmadan, şebeke tabanlı,
güvenli ve sessiz doğrulama". Bu mock, çekirdek şebekenin SIM↔numara eşleşmesini
arka planda doğrulamasını taklit eder. Final yarışmada Turkcell gerçek doğrulamayı
sağlar; uygulama tarafı aynı arayüzü kullanmaya devam eder.

CAMARA sözleşmesi:
  POST /number-verification:verify   { phoneNumber }  (Authorization: device token)
  -> { devicePhoneNumberVerified: bool }
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional

# Mock operatör kaydı: device_token -> hat numarası (gerçekte çekirdek şebeke bilir)
_MOCK_SIM_REGISTRY: Dict[str, str] = {
    "device-demo-token": "+905551112233",
    "device-guard-01": "+905320001122",
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


@dataclass
class AuthSession:
    token: str
    msisdn: str
    issued_at: float


class MockNumberVerification:
    def __init__(self):
        self._jwt_store: Dict[str, AuthSession] = {}

    def verify(self, device_token: str, claimed_number: str) -> bool:
        """Cihazdaki SIM'in beyan edilen numarayla eşleşip eşleşmediğini döner."""
        registered = _MOCK_SIM_REGISTRY.get(device_token)
        if registered is None:
            return False
        return _normalize_msisdn(registered) == _normalize_msisdn(claimed_number)

    def device_phone_number(self, device_token: str) -> Optional[str]:
        """CAMARA :device-phone-number — SIM'in numarasını şebekeden alır (sessiz)."""
        return _MOCK_SIM_REGISTRY.get(device_token)

    def issue_token(self, msisdn: str) -> str:
        """Doğrulama başarılıysa oturum jetonu (mock JWT) üret."""
        token = uuid.uuid4().hex
        self._jwt_store[token] = AuthSession(token=token, msisdn=msisdn, issued_at=time.time())
        return token

    def validate_token(self, token: str) -> Optional[AuthSession]:
        return self._jwt_store.get(token)
