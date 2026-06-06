"""
JWT RS256 kimlik doğrulama — ÖTR gereksinimi.

Number Verification başarılıysa RS256 ile imzalanmış token üretilir.
Sonraki isteklerde Authorization: Bearer <token> header'ı ile doğrulanır.
"""
from __future__ import annotations

import time
from typing import Optional

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import get_settings

_ALGORITHM = "RS256"
_ISSUER = "5g-roadguard"
_bearer = HTTPBearer(auto_error=False)


class JWTManager:
    """RS256 anahtar çifti ile token üretir ve doğrular."""

    def __init__(self) -> None:
        self._private = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        self._public = self._private.public_key()

    def issue(self, sub: str, extra: dict | None = None) -> str:
        s = get_settings()
        now = int(time.time())
        payload = {
            "sub": sub,
            "iss": _ISSUER,
            "iat": now,
            "exp": now + s.jwt_ttl_s,
            **(extra or {}),
        }
        return jwt.encode(payload, self._private, algorithm=_ALGORITHM)

    def decode(self, token: str) -> dict:
        return jwt.decode(
            token,
            self._public,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
        )

    def verify(self, token: str) -> Optional[dict]:
        try:
            return self.decode(token)
        except jwt.PyJWTError:
            return None


_manager: Optional[JWTManager] = None


def get_jwt_manager() -> JWTManager:
    """Modül seviyesi singleton — startup'ta bir kez üretilir."""
    global _manager
    if _manager is None:
        _manager = JWTManager()
    return _manager


async def require_auth(
    creds: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> Optional[dict]:
    """
    FastAPI dependency — REQUIRE_AUTH=true ise Bearer token zorunlu.
    False (varsayılan) ise token yoksa None döner, var ise doğrular.
    """
    s = get_settings()
    if not s.require_auth:
        if creds is None:
            return None
        payload = get_jwt_manager().verify(creds.credentials)
        return payload  # geçersizse None, geçerliyse payload

    if creds is None:
        raise HTTPException(status_code=401, detail="Bearer token gerekli")
    payload = get_jwt_manager().verify(creds.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token")
    return payload
