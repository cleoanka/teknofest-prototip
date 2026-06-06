from backend.camara.number_verification import MockNumberVerification


def test_silent_verify_match():
    nv = MockNumberVerification()
    assert nv.verify("device-guard-01", "+905320001122") is True
    # numara formatı normalize edilir (0532... da kabul)
    assert nv.verify("device-guard-01", "05320001122") is True


def test_silent_verify_mismatch():
    nv = MockNumberVerification()
    assert nv.verify("device-guard-01", "+905550000000") is False
    assert nv.verify("bilinmeyen-token", "+905320001122") is False


def test_token_issue_and_validate():
    """Token üretimi artık RS256 JWT ile backend/auth.py üzerinden yapılıyor."""
    from backend.auth import JWTManager
    mgr = JWTManager()
    token = mgr.issue("+905320001122")
    assert mgr.verify(token) is not None
    assert mgr.verify("gecersiz") is None


def test_api_endpoint(client):
    r = client.post("/camara/number-verification:verify",
                    json={"device_token": "device-guard-01", "phone_number": "+905320001122"})
    assert r.status_code == 200
    body = r.json()
    assert body["devicePhoneNumberVerified"] is True
    assert body["token"]

    r2 = client.post("/camara/number-verification:verify",
                     json={"device_token": "device-guard-01", "phone_number": "+900000000000"})
    assert r2.json()["devicePhoneNumberVerified"] is False
