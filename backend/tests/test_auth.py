"""Tests for authentication: token generation, hashing, prefix extraction."""

import pytest
from starlette.requests import Request

from backend.app.auth import (
    _extract_prefix,
    create_admin_session_token,
    generate_reader_token,
    get_admin_auth_mode,
    hash_token,
    is_admin_cookie_secure,
    validate_admin_session_token,
    verify_admin_password,
)
from backend.app.admin_auth_middleware import AdminAuthMiddleware


class TestGenerateReaderToken:
    def test_token_format(self):
        token, prefix = generate_reader_token()
        assert token.startswith("smr_")
        assert prefix.startswith("smr_")
        assert token.startswith(prefix)
        # Token should have three parts: smr, hex prefix, secret
        parts = token.split("_", 2)
        assert len(parts) == 3
        assert parts[0] == "smr"

    def test_tokens_are_unique(self):
        tokens = set()
        for _ in range(50):
            token, _ = generate_reader_token()
            tokens.add(token)
        assert len(tokens) == 50

    def test_prefix_is_stable(self):
        token, prefix = generate_reader_token()
        extracted = _extract_prefix(token)
        assert extracted == prefix


class TestHashToken:
    def test_deterministic(self):
        assert hash_token("test123") == hash_token("test123")

    def test_different_tokens_different_hashes(self):
        assert hash_token("token_a") != hash_token("token_b")

    def test_returns_hex_string(self):
        h = hash_token("test")
        assert len(h) == 64  # SHA256 hex digest
        assert all(c in "0123456789abcdef" for c in h)


class TestExtractPrefix:
    def test_valid_token(self):
        assert _extract_prefix("smr_abcd1234_secret") == "smr_abcd1234"

    def test_invalid_prefix(self):
        assert _extract_prefix("invalid_token") is None

    def test_wrong_scheme(self):
        assert _extract_prefix("xyz_abcd_secret") is None

    def test_too_few_parts(self):
        assert _extract_prefix("smr_only") is None

    def test_empty_string(self):
        assert _extract_prefix("") is None


class TestAdminAuth:
    def test_audiobook_files_require_admin_auth(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "secret")
        audiobook_request = Request(
            {"type": "http", "method": "GET", "path": "/library/audiobooks/1/working.epub", "headers": []}
        )
        cover_request = Request({"type": "http", "method": "GET", "path": "/library/covers/1.jpg", "headers": []})

        assert AdminAuthMiddleware._requires_admin_auth(audiobook_request) is True
        assert AdminAuthMiddleware._requires_admin_auth(cover_request) is False

    def test_verify_admin_password_uses_env(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "secret")

        assert verify_admin_password("secret") is True
        assert verify_admin_password("wrong") is False

    def test_admin_session_token_expires(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "secret")
        token = create_admin_session_token(now=100)

        assert validate_admin_session_token(token, now=101) is True
        assert validate_admin_session_token(token, now=60 * 60 * 24 * 15) is False

    def test_admin_session_token_rejects_tampering(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "secret")
        token = create_admin_session_token(now=100)
        tampered = token.replace(".", "x.", 1)

        assert validate_admin_session_token(tampered, now=101) is False

    def test_invalid_auth_mode_fails_closed(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "pasword")
        with pytest.raises(RuntimeError, match="Invalid STORY_MANAGER_AUTH_MODE"):
            get_admin_auth_mode()

    def test_password_mode_requires_password(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "password")
        monkeypatch.delenv("STORY_MANAGER_ADMIN_PASSWORD", raising=False)
        with pytest.raises(RuntimeError, match="requires STORY_MANAGER_ADMIN_PASSWORD"):
            get_admin_auth_mode()

    def test_secure_cookie_auto_detects_https(self, monkeypatch):
        monkeypatch.delenv("STORY_MANAGER_ADMIN_COOKIE_SECURE", raising=False)
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "scheme": "https"})
        assert is_admin_cookie_secure(request) is True

    def test_secure_cookie_setting_is_validated(self, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_ADMIN_COOKIE_SECURE", "sometimes")
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "scheme": "http"})
        with pytest.raises(RuntimeError, match="Invalid STORY_MANAGER_ADMIN_COOKIE_SECURE"):
            is_admin_cookie_secure(request)
