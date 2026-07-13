"""JWT RS256 kimlik doğrulama testleri."""
import time
import jwt as pyjwt

from backend.auth import get_jwt_manager, JWTManager


def test_jwt_manager_singleton():
    m1 = get_jwt_manager()
    m2 = get_jwt_manager()
    assert m1 is m2


def test_jwt_issue_and_verify():
    mgr = JWTManager()
    token = mgr.issue("+905320001122")
    assert isinstance(token, str)
    assert len(token) > 50  # gerçek JWT

    payload = mgr.verify(token)
    assert payload is not None
    assert payload["sub"] == "+905320001122"
    assert payload["iss"] == "5g-roadguard"


def test_jwt_extra_claims():
    mgr = JWTManager()
    token = mgr.issue("+905551112233", extra={"device": "device-guard-01"})
    payload = mgr.verify(token)
    assert payload["device"] == "device-guard-01"


def test_jwt_expired_token():
    mgr = JWTManager()
    # 1 saniye TTL ile token üret, sonra 2 saniye bekle (mock ile test)
    now = int(time.time())
    expired_payload = {
        "sub": "+905320001122",
        "iss": "5g-roadguard",
        "iat": now - 10,
        "exp": now - 1,  # geçmişte süresi dolmuş
    }
    expired_token = pyjwt.encode(expired_payload, mgr._private, algorithm="RS256")
    result = mgr.verify(expired_token)
    assert result is None


def test_jwt_invalid_signature():
    mgr1 = JWTManager()
    mgr2 = JWTManager()
    # mgr1 ile üretilmiş token mgr2 tarafından doğrulanamaz (farklı anahtar)
    token = mgr1.issue("+905320001122")
    result = mgr2.verify(token)
    assert result is None


def test_jwt_tampered_token():
    mgr = JWTManager()
    token = mgr.issue("+905320001122")
    # Token'ın ortasını değiştir
    parts = token.split(".")
    tampered = parts[0] + ".TAMPERED" + parts[2]
    result = mgr.verify(tampered)
    assert result is None


def test_number_verification_returns_jwt(client):
    """Number Verification endpoint'i geçerli RS256 JWT döndürür."""
    r = client.post(
        "/camara/number-verification:verify",
        json={"device_token": "device-guard-01", "phone_number": "+905320001122"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["devicePhoneNumberVerified"] is True
    assert data["token"] is not None

    # Token geçerli JWT mi?
    mgr = get_jwt_manager()
    payload = mgr.verify(data["token"])
    assert payload is not None
    assert payload["sub"] == "+905320001122"


def test_number_verification_wrong_number_returns_no_token(client):
    r = client.post(
        "/camara/number-verification:verify",
        json={"device_token": "device-guard-01", "phone_number": "+905000000000"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["devicePhoneNumberVerified"] is False
    assert data["token"] is None
