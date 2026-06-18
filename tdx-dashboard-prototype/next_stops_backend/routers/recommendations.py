"""Recommendation and saved-place routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query


def create_router(deps) -> APIRouter:
    router = APIRouter(tags=["recommendations"])

    @router.post("/api/recommend")
    def recommend(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.build_recommendations(payload or {}))

    @router.post("/api/recommendations")
    def recommendations(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.build_recommendations(payload or {}))

    @router.get("/api/recommendations/{request_id}")
    def recommendation_record(request_id: str):
        record = deps.run_or_raise(lambda: deps.fetch_recommendation_record(request_id))
        if record is None:
            raise HTTPException(status_code=404, detail="Recommendation request not found")
        return record

    @router.get("/api/saved-places")
    def saved_places(session_id: str = Query(...)):
        return deps.run_or_raise(lambda: {"saved": deps.list_saved_places(session_id.strip())})

    @router.post("/api/saved-places")
    def save_place(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.upsert_saved_place(payload or {}))

    @router.patch("/api/saved-places/{place_id}")
    def update_saved_place(place_id: str, payload: dict[str, Any] | None = Body(default=None)):
        data = payload or {}
        session_id = str(data.get("session_id") or "").strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        updated = deps.run_or_raise(lambda: deps.update_saved_place_note(session_id, place_id, str(data.get("note") or "")))
        if updated is None:
            raise HTTPException(status_code=404, detail="Saved place not found")
        return updated

    @router.delete("/api/saved-places/{place_id}")
    def delete_saved_place(place_id: str, session_id: str = Query(...)):
        return deps.run_or_raise(lambda: deps.remove_saved_place(session_id.strip(), place_id))

    @router.post("/api/recommendation-feedback")
    def recommendation_feedback(payload: dict[str, Any] | None = Body(default=None)):
        return deps.run_or_raise(lambda: deps.record_feedback(payload or {}))

    return router

