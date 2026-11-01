"""Admin login hardening: byte-safe comparison, per-client backoff, and session revocation."""

import logging

import pytest

from backend.app import auth
from backend.app.auth import (
    LoginThrottle,
    create_admin_session_token,
    get_admin_session_epoch,
    revoke_admin_sessions,
    validate_admin_session_token,
    verify_admin_password,
    warn_if_admin_auth_disabled,
)


@pytest.fixture
def password_auth(monkeypatch):
    monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "password")
    monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "sécret-密码")
    monkeypatch.delenv("STORY_MANAGER_ADMIN_SESSION_SECRET", raising=False)


class TestPasswordComparison:
    def test_non_ascii_passwords_compare_without_raising(self, password_auth):
        assert verify_admin_password("sécret-密码") is True
        assert verify_admin_password("sécret-密") is False
        assert verify_admin_password("ünïcode") is False

    def test_non_ascii_login_attempt_is_401_not_500(self, app_client, password_auth):
        response = app_client.post("/api/auth/login", json={"password": "wröng"})
        assert response.status_code == 401

    def test_non_ascii_cookie_signature_is_rejected(self, password_auth):
        token = create_admin_session_token(now=100)
        payload = token.split(".", 1)[0]
        assert validate_admin_session_token(f"{payload}.ü", now=101) is False


class TestSessionEpoch:
    def test_token_is_bound_to_epoch(self, password_auth):
        token = create_admin_session_token(now=100, epoch=3)
        assert validate_admin_session_token(token, now=101, epoch=3) is True
        assert validate_admin_session_token(token, now=101, epoch=4) is False

    def test_password_change_revokes_tokens_even_with_session_secret(self, monkeypatch, password_auth):
        monkeypatch.setenv("STORY_MANAGER_ADMIN_SESSION_SECRET", "dedicated-secret")
        token = create_admin_session_token(now=100)
        assert validate_admin_session_token(token, now=101) is True

        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "rotated")
        assert validate_admin_session_token(token, now=101) is False

    @pytest.mark.asyncio
    async def test_revoke_creates_and_advances_epoch(self, db):
        assert await get_admin_session_epoch(db) == 0
        assert await revoke_admin_sessions(db) == 1
        assert await revoke_admin_sessions(db) == 2
        assert await get_admin_session_epoch(db) == 2

    def test_logout_revokes_previously_issued_cookie(self, app_client, password_auth):
        login = app_client.post("/api/auth/login", json={"password": "sécret-密码"})
        assert login.status_code == 200
        stolen_cookie = login.cookies[auth.ADMIN_AUTH_COOKIE]
        assert app_client.get("/api/books").status_code == 200

        assert app_client.post("/api/auth/logout").status_code == 200
        app_client.cookies.set(auth.ADMIN_AUTH_COOKIE, stolen_cookie)
        assert app_client.get("/api/books").status_code == 401
        assert app_client.get("/api/auth/status").json()["authenticated"] is False

        app_client.cookies.clear()
        relogin = app_client.post("/api/auth/login", json={"password": "sécret-密码"})
        assert relogin.status_code == 200
        assert app_client.get("/api/books").status_code == 200

    def test_unauthenticated_logout_does_not_revoke_sessions(self, app_client, password_auth):
        login = app_client.post("/api/auth/login", json={"password": "sécret-密码"})
        cookie = login.cookies[auth.ADMIN_AUTH_COOKIE]
        app_client.cookies.clear()

        assert app_client.post("/api/auth/logout").status_code == 200
        app_client.cookies.set(auth.ADMIN_AUTH_COOKIE, cookie)
        assert app_client.get("/api/books").status_code == 200


class TestLoginThrottle:
    def test_backoff_doubles_after_free_attempts(self):
        throttle = LoginThrottle(free_attempts=2, base_lockout_seconds=1, max_lockout_seconds=8)
        for _ in range(2):
            throttle.record_failure("1.2.3.4", now=0)
        assert throttle.retry_after("1.2.3.4", now=0) == 0

        throttle.record_failure("1.2.3.4", now=0)
        assert throttle.retry_after("1.2.3.4", now=0) == 1
        throttle.record_failure("1.2.3.4", now=1)
        assert throttle.retry_after("1.2.3.4", now=1) == 2
        for _ in range(5):
            throttle.record_failure("1.2.3.4", now=10)
        assert throttle.retry_after("1.2.3.4", now=10) == 8
        assert throttle.retry_after("5.6.7.8", now=10) == 0

    def test_success_and_quiet_period_reset_history(self):
        throttle = LoginThrottle(free_attempts=0, base_lockout_seconds=4, reset_after_seconds=60)
        throttle.record_failure("client", now=0)
        assert throttle.retry_after("client", now=0) == 4
        throttle.record_success("client")
        assert throttle.retry_after("client", now=0) == 0

        throttle.record_failure("client", now=0)
        throttle.record_failure("client", now=0)
        assert throttle.retry_after("client", now=0) == 8
        throttle.record_failure("client", now=100)
        assert throttle.retry_after("client", now=100) == 4

    def test_tracked_clients_are_bounded(self):
        throttle = LoginThrottle(max_tracked_clients=3)
        for index in range(10):
            throttle.record_failure(f"client-{index}", now=index)
        assert len(throttle._failures) <= 3

    def test_login_endpoint_returns_429_with_retry_after(self, app_client, password_auth):
        for _ in range(auth.admin_login_throttle.free_attempts):
            assert app_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert app_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401

        locked = app_client.post("/api/auth/login", json={"password": "sécret-密码"})
        assert locked.status_code == 429
        assert int(locked.headers["Retry-After"]) >= 1


class TestDisabledMode:
    def test_disabled_mode_still_serves_admin_api_and_login(self, app_client, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "disabled")
        monkeypatch.delenv("STORY_MANAGER_ADMIN_PASSWORD", raising=False)

        assert app_client.get("/api/books").status_code == 200
        assert app_client.get("/api/auth/status").json() == {"mode": "disabled", "authenticated": True}
        assert app_client.post("/api/auth/login", json={"password": "anything"}).json()["authenticated"] is True
        assert app_client.post("/api/auth/logout").json()["authenticated"] is True

    def test_disabled_mode_logs_proxy_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "disabled")
        with caplog.at_level(logging.WARNING, logger="backend.app.auth"):
            warn_if_admin_auth_disabled()
        assert "authenticating reverse proxy" in caplog.text

    def test_password_mode_does_not_warn(self, password_auth, caplog):
        with caplog.at_level(logging.WARNING, logger="backend.app.auth"):
            warn_if_admin_auth_disabled()
        assert caplog.text == ""
