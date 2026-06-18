"""Admin routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends


def create_router(deps) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/summary")
    def summary(_: None = Depends(deps.require_admin)):
        return deps.run_or_raise(deps.admin_summary)

    @router.get("/overview")
    def overview(limit: int = 80, _: None = Depends(deps.require_admin)):
        return deps.run_or_raise(lambda: deps.admin_overview(limit))

    @router.get("/users")
    def users(limit: int = 80, _: None = Depends(deps.require_admin)):
        return deps.run_or_raise(lambda: deps.admin_users(limit))

    @router.delete("/users/{user_id}")
    def delete_user(user_id: str, _: None = Depends(deps.require_admin)):
        return deps.run_or_raise(lambda: deps.admin_delete_user(user_id))

    @router.get("/recommendations")
    def recommendations(limit: int = 80, _: None = Depends(deps.require_admin)):
        return deps.run_or_raise(lambda: deps.admin_recommendations(limit))

    @router.get("/feedback")
    def feedback(limit: int = 120, _: None = Depends(deps.require_admin)):
        return deps.run_or_raise(lambda: deps.admin_feedback(limit))

    @router.get("/places")
    def places(_: None = Depends(deps.require_admin)):
        return deps.run_or_raise(deps.admin_places_summary)

    @router.post("/places/rebuild")
    def rebuild_places(with_optional: bool = False, _: None = Depends(deps.require_admin)):
        return deps.places_build(with_optional=with_optional)

    return router

