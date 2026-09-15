import time

import jwt
import pytest
from jwt.exceptions import InvalidTokenError

from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        password = "MySecureP@ss123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)


class TestAccessToken:
    def test_create_and_decode(self):
        subject = "user-uuid-123"
        token = create_access_token(subject, tenant_id="t-1", role="owner")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == subject
        assert payload["type"] == "access"
        assert payload["tenant_id"] == "t-1"
        assert payload["role"] == "owner"
        assert "exp" in payload

    def test_rejects_as_refresh_type(self):
        token = create_access_token("user-uuid-123", tenant_id="t-1", role="viewer")
        with pytest.raises(InvalidTokenError, match='missing the "jti" claim'):
            decode_token(token, expected_type="refresh")


class TestRefreshToken:
    def test_returns_token_and_jti(self):
        token, jti = create_refresh_token(
            "user-uuid-123", tenant_id="t-1", role="admin"
        )
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(jti) == 32  # uuid4 hex

    def test_create_and_decode(self):
        token, jti = create_refresh_token(
            "user-uuid-123", tenant_id="t-1", role="admin"
        )
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "user-uuid-123"
        assert payload["type"] == "refresh"
        assert payload["jti"] == jti
        assert payload["tenant_id"] == "t-1"
        assert payload["role"] == "admin"

    def test_rejects_as_access_type(self):
        token, _ = create_refresh_token("user-uuid-123", tenant_id="t-1", role="viewer")
        with pytest.raises(InvalidTokenError, match="Expected token type 'access'"):
            decode_token(token, expected_type="access")


class TestDecodeToken:
    def test_rejects_expired_token(self):
        from app.config import get_settings

        settings = get_settings()
        payload = {"sub": "user-123", "exp": time.time() - 10, "type": "access"}
        token = jwt.encode(
            payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        with pytest.raises(InvalidTokenError):
            decode_token(token, expected_type="access")

    def test_rejects_missing_required_claims(self):
        from app.config import get_settings

        settings = get_settings()
        # Token without "sub" claim
        payload = {"exp": time.time() + 300, "type": "access"}
        token = jwt.encode(
            payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        with pytest.raises(InvalidTokenError):
            decode_token(token, expected_type="access")

    def test_rejects_tampered_token(self):
        token = create_access_token("user-123", tenant_id="t-1", role="viewer")
        tampered = token[:-4] + "XXXX"
        with pytest.raises(InvalidTokenError):
            decode_token(tampered, expected_type="access")
