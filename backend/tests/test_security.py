import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_argon2id_and_salted(self) -> None:
        first, second = hash_password("s3cret-pass"), hash_password("s3cret-pass")
        assert first.startswith("$argon2id$")
        assert first != second  # random salt
        assert "s3cret-pass" not in first

    def test_verify_correct_and_wrong_password(self) -> None:
        hashed = hash_password("s3cret-pass")
        assert verify_password("s3cret-pass", hashed) is True
        assert verify_password("S3cret-pass", hashed) is False
        assert verify_password("", hashed) is False

    def test_verify_against_missing_or_corrupt_hash_is_false(self) -> None:
        assert verify_password("anything", None) is False
        assert verify_password("anything", "not-a-hash") is False

    def test_fresh_hash_needs_no_rehash(self) -> None:
        assert password_needs_rehash(hash_password("s3cret-pass")) is False


class TestAccessTokens:
    def test_round_trip(self) -> None:
        user_id = uuid.uuid4()
        token, expires_at = create_access_token(user_id, "FACULTY")
        claims = decode_access_token(token)
        assert claims.user_id == user_id
        assert claims.role == "FACULTY"
        assert abs((claims.expires_at - expires_at).total_seconds()) < 1

    def test_expired_token_rejected(self) -> None:
        token, _ = create_access_token(uuid.uuid4(), "ADMIN", expires_delta=timedelta(seconds=-5))
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)

    def test_tampered_token_rejected(self) -> None:
        token, _ = create_access_token(uuid.uuid4(), "FACULTY")
        header, payload, signature = token.split(".")
        forged = jwt.encode(
            {**jwt.decode(token, options={"verify_signature": False}), "role": "ADMIN"},
            "attacker-secret-attacker-secret-attacker",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged)
        with pytest.raises(InvalidTokenError):
            decode_access_token(f"{header}.{payload}.{signature[::-1]}")

    def test_alg_none_rejected(self) -> None:
        unsigned = jwt.encode(
            {"sub": str(uuid.uuid4()), "role": "ADMIN", "type": "access", "iat": 0, "exp": 2**31},
            key=None,
            algorithm="none",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(unsigned)

    def test_wrong_token_type_rejected(self) -> None:
        settings = get_settings()
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "role": "ADMIN", "type": "refresh", "iat": 0, "exp": 2**31},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError, match="Not an access token"):
            decode_access_token(token)

    def test_missing_claims_rejected(self) -> None:
        settings = get_settings()
        token = jwt.encode({"sub": "x", "exp": 2**31}, settings.jwt_secret_key, algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)

    def test_garbage_rejected(self) -> None:
        with pytest.raises(InvalidTokenError):
            decode_access_token("not.a.jwt")


class TestRefreshTokens:
    def test_opaque_unique_and_hashed(self) -> None:
        a, b = generate_refresh_token(), generate_refresh_token()
        assert a != b and len(a) >= 60
        assert hash_refresh_token(a) == hash_refresh_token(a)
        assert hash_refresh_token(a) != a and len(hash_refresh_token(a)) == 64
