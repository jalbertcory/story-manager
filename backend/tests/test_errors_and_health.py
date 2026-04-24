"""Tests for structured error responses and the health check endpoint."""

import pytest


class TestStructuredErrors:
    @pytest.mark.asyncio
    async def test_404_returns_structured_error(self, app_client):
        response = app_client.get("/api/books/99999")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"] == "not_found"
        assert "detail" in data
        assert data["status_code"] == 404

    @pytest.mark.asyncio
    async def test_400_returns_structured_error(self, app_client):
        response = app_client.post("/api/books/add_web_novel", json={"url": "not-a-url"})
        # Pydantic validation returns 422
        assert response.status_code in (400, 422)
        data = response.json()
        assert "detail" in data


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(self, app_client):
        response = app_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


class TestAdminApiAuth:
    @pytest.mark.asyncio
    async def test_admin_api_requires_login_when_password_auth_enabled(self, app_client, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "password")
        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "secret")

        unauthorized = app_client.get("/api/books")
        assert unauthorized.status_code == 401

        bad_login = app_client.post("/api/auth/login", json={"password": "wrong"})
        assert bad_login.status_code == 401

        login = app_client.post("/api/auth/login", json={"password": "secret"})
        assert login.status_code == 200
        assert login.json()["authenticated"] is True

        authorized = app_client.get("/api/books")
        assert authorized.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_api_allows_disabled_auth_mode(self, app_client, monkeypatch):
        monkeypatch.setenv("STORY_MANAGER_AUTH_MODE", "disabled")
        monkeypatch.setenv("STORY_MANAGER_ADMIN_PASSWORD", "secret")

        response = app_client.get("/api/books")
        assert response.status_code == 200
