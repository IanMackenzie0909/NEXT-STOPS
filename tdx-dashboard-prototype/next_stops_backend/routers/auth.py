"""Authentication routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header


def create_router(deps) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.get("/config")
    def auth_config():
        return deps.auth_config()

    @router.post("/register")
    def register(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.register_platform_user(payload or {}))

    @router.post("/login")
    def login(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.login_platform_user(payload or {}))

    @router.post("/google")
    def google(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.login_google_user(payload or {}))

    @router.get("/me")
    def me(authorization: str | None = Header(default=None)):
        return {"user": deps.require_current_user(authorization)}

    @router.patch("/preferences")
    def preferences(payload: dict[str, Any] | None = Body(default=None), authorization: str | None = Header(default=None)):
        user = deps.require_current_user(authorization)
        updated = deps.run_or_raise(lambda: deps.update_user_preferences(user, payload or {}))
        return {"user": updated}

    @router.patch("/profile")
    def profile(payload: dict[str, Any] | None = Body(default=None), authorization: str | None = Header(default=None)):
        user = deps.require_current_user(authorization)
        updated = deps.run_or_raise(lambda: deps.update_user_profile(user, payload or {}))
        return {"user": updated}

    @router.post("/logout")
    def logout(payload: dict[str, Any] | None = Body(default=None), authorization: str | None = Header(default=None)):
        data = payload or {}
        return deps.run_or_raise(lambda: deps.logout_auth_session(authorization or str(data.get("token") or "")))

    @router.delete("/account")
    def delete_account(authorization: str | None = Header(default=None)):
        user = deps.require_current_user(authorization)
        return deps.run_or_raise(lambda: deps.delete_user_account(user))

    return router

