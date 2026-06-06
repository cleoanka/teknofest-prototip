"""
JWT RS256 kimlik doğrulama — ÖTR gereksinimi.

Number Verification başarılıysa RS256 ile imzalanmış token üretilir.
Sonraki isteklerde Authorization: Bearer <token> header'ı ile doğrulanır.

Key kalıcılığı: JWT_PRIVATE_KEY_PATH env var tanımlanmışsa anahtar dosyadan
yüklenir (yeniden başlatmalarda token geçerliliği korunur). Tanımlanmamışsa
her startup'ta yeni anahtar üretilir (geliştirme/test).
"""
from __future__ import annotations

import os
import time
from typing import Optional

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import get_settings

_ALGORITHM = "RS256"
_ISSUER = "5g-roadguard"
_bearer = HTTPBearer(auto_error=False)


def _load_or_generate_private_key(path: Optional[str]):
    """Dosyadan yükle; yoksa üret ve varsa kaydet."""
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    private = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )

    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        pem = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(path, "wb") as f:
            f.write(pem)
        os.chmod(path, 0o600)  # sadece owner okuyabilir

    return private


class JWTManager:
    """RS256 anahtar çifti ile token üretir ve doğrular."""

    def __init__(self) -> None:
        s = get_settings()
        self._private = _load_or_generate_private_key(s.jwt_private_key_path or None)
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

    def public_key_pem(self) -> str:
        """Public key PEM formatında — doğrulama tarafları için."""
        return self._public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()


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
        return get_jwt_manager().verify(creds.credentials)

    if creds is None:
        raise HTTPException(status_code=401, detail="Bearer token gerekli")
    payload = get_jwt_manager().verify(creds.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token")
    return payload
