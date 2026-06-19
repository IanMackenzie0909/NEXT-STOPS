"""Authentication, session, and user-profile services for NEXT STOPS."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from typing import Any

import requests
from fastapi import HTTPException

from .config import GOOGLE_TOKENINFO_URL, PASSWORD_PATTERN
from .database import connect_recommendation_db, init_recommendation_db
from .service_area import SERVICE_AREA_LABEL, is_within_service_area
from .utils import now_iso


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    get_value = row.get if isinstance(row, dict) else row.__getitem__
    try:
        preferences = json.loads(get_value("preferences_json") or "{}")
    except Exception:
        preferences = {}
    return {
        "id": get_value("id"),
        "provider": get_value("provider"),
        "account": get_value("account"),
        "email": get_value("email"),
        "name": get_value("display_name") or get_value("account") or get_value("email"),
        "avatar_url": get_value("avatar_url"),
        "session_id": f"user:{get_value('id')}",
        "preferences": preferences,
    }


def clean_password(value: object) -> str:
    return str(value or "").rstrip()


def validate_password(account: str, password: str, confirm: str | None = None) -> None:
    if confirm is not None and password != clean_password(confirm):
        raise ValueError("兩次輸入的密碼不一致")
    if account and account == password:
        raise ValueError("帳號與密碼不可相同")
    if re.search(r"\s", password):
        raise ValueError("密碼開頭與中間不得包含空白字元")
    if not PASSWORD_PATTERN.match(password):
        raise ValueError("密碼需為 8-16 字元，包含大小寫英文字母、數字，且至少一個 @、$、_ 或 -")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180000)
    return f"pbkdf2_sha256$180000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def create_auth_session(user_id: str) -> str:
    init_recommendation_db()
    token = secrets.token_urlsafe(40)
    now = now_iso()
    with connect_recommendation_db() as db:
        db.execute(
            "INSERT INTO auth_sessions (token, user_id, created_at, last_seen) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now),
        )
    return token


def auth_response(user_row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    user = public_user(user_row)
    return {"token": create_auth_session(user["id"]), "user": user}


def bearer_token(authorization: str | None) -> str:
    text = str(authorization or "").strip()
    return text[7:].strip() if text.lower().startswith("bearer ") else text


def current_user_from_token(token: str) -> dict[str, Any] | None:
    token = bearer_token(token)
    if not token:
        return None
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            """
            SELECT users.*
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if row:
            db.execute("UPDATE auth_sessions SET last_seen = ? WHERE token = ?", (now_iso(), token))
    return public_user(row) if row else None


def require_current_user(authorization: str | None) -> dict[str, Any]:
    user = current_user_from_token(authorization or "")
    if not user:
        raise HTTPException(status_code=401, detail="請先登入")
    return user


def verify_google_id_token(id_token: str) -> dict[str, Any]:
    client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("VITE_GOOGLE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID 尚未設定")
    response = requests.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token}, timeout=10)
    response.raise_for_status()
    info = response.json()
    if info.get("aud") != client_id:
        raise ValueError("Google token audience 不符合目前應用程式")
    if info.get("email_verified") not in {True, "true", "True", "1", 1}:
        raise ValueError("Google 帳戶尚未完成 email 驗證")
    return info


def register_platform_user(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    account = str(payload.get("account") or "").strip()
    password = clean_password(payload.get("password"))
    confirm = clean_password(payload.get("confirm_password"))
    if not name:
        raise ValueError("名稱為必填")
    if not account:
        raise ValueError("帳號為必填")
    validate_password(account, password, confirm)

    init_recommendation_db()
    user_id = uuid.uuid4().hex
    now = now_iso()
    try:
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            db.execute(
                """
                INSERT INTO users (
                    id, provider, account, email, display_name, avatar_url, password_hash, google_sub,
                    preferences_json, created_at, updated_at
                ) VALUES (?, 'platform', ?, NULL, ?, NULL, ?, NULL, '{}', ?, ?)
                """,
                (user_id, account, name, hash_password(password), now, now),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception as exc:
        if not isinstance(exc, sqlite3.IntegrityError) and exc.__class__.__name__ != "UniqueViolation":
            raise
        raise ValueError("這個帳號已經被使用") from exc
    return {"ok": True, "user": public_user(row)}


def login_platform_user(payload: dict[str, Any]) -> dict[str, Any]:
    account = str(payload.get("account") or "").strip()
    password = clean_password(payload.get("password"))
    if not account or not password:
        raise ValueError("帳號與密碼為必填")
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM users WHERE account = ? AND provider = 'platform'", (account,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise ValueError("帳號或密碼錯誤")
    return auth_response(row)


def login_google_user(payload: dict[str, Any]) -> dict[str, Any]:
    id_token = str(payload.get("id_token") or payload.get("credential") or "").strip()
    if not id_token:
        raise ValueError("Google ID token is required")
    info = verify_google_id_token(id_token)
    google_sub = str(info.get("sub") or "")
    email = str(info.get("email") or "")
    name = str(info.get("name") or email or "Google User")
    avatar_url = str(info.get("picture") or "")
    if not google_sub:
        raise ValueError("Google token 缺少 sub")

    init_recommendation_db()
    now = now_iso()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
        if row is None:
            user_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO users (
                    id, provider, account, email, display_name, avatar_url, password_hash, google_sub,
                    preferences_json, created_at, updated_at
                ) VALUES (?, 'google', ?, ?, ?, ?, NULL, ?, '{}', ?, ?)
                """,
                (user_id, email or None, email or None, name, avatar_url or None, google_sub, now, now),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        else:
            db.execute(
                """
                UPDATE users SET email = ?, display_name = ?, avatar_url = ?, updated_at = ?
                WHERE id = ?
                """,
                (email or row["email"], row["display_name"] or name, row["avatar_url"] or avatar_url or None, now, row["id"]),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return auth_response(row)


def normalize_favorite_starts(raw_starts: Any) -> list[dict[str, Any]]:
    starts = []
    if not isinstance(raw_starts, list):
        raise ValueError("常用起始點格式錯誤")
    for item in raw_starts[:2]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:24]
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
        if not label:
            raise ValueError("請先為常用起點命名")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("常用起始點座標不正確")
        if not is_within_service_area(lat, lon):
            raise ValueError(f"常用起始點不在服務區域內；目前服務區域暫定為{SERVICE_AREA_LABEL}")
        starts.append({
            "id": str(item.get("id") or uuid.uuid4().hex),
            "label": label,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
        })
    return starts


def update_user_preferences(user: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    allowed_weights = {"mood", "distance", "weather", "aqi", "budget", "category", "quality", "environment"}
    current_preferences = dict(user.get("preferences") or {})
    clean_preferences = dict(current_preferences)
    if "weightAdjustments" in preferences or "weight_adjustments" in preferences:
        raw_weights = preferences.get("weightAdjustments") or preferences.get("weight_adjustments") or {}
        weights = {}
        for key, value in raw_weights.items():
            if key in allowed_weights:
                weights[key] = max(0.5, min(1.6, float(value)))
        clean_preferences["weightAdjustments"] = weights
    if "favoriteStarts" in preferences or "favorite_starts" in preferences:
        clean_preferences["favoriteStarts"] = normalize_favorite_starts(
            preferences.get("favoriteStarts") or preferences.get("favorite_starts") or []
        )
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE users SET preferences_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(clean_preferences, ensure_ascii=False), now_iso(), user["id"]),
        )
        row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(row)


def update_user_profile(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    avatar_url = str(payload.get("avatar_url") or "").strip()
    if not name:
        raise ValueError("名稱為必填")
    if len(name) > 40:
        raise ValueError("名稱最多 40 個字元")
    if len(avatar_url) > 800000:
        raise ValueError("頭像圖片過大，請選擇較小的圖片")
    if avatar_url and not (avatar_url.startswith("data:image/") or avatar_url.startswith("https://")):
        raise ValueError("頭像格式不支援")

    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE users SET display_name = ?, avatar_url = ?, updated_at = ? WHERE id = ?",
            (name, avatar_url or None, now_iso(), user["id"]),
        )
        row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(row)


def logout_auth_session(token: str) -> dict[str, Any]:
    token = bearer_token(token)
    if token:
        init_recommendation_db()
        with connect_recommendation_db() as db:
            db.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
    return {"ok": True}


def delete_user_account(user: dict[str, Any]) -> dict[str, Any]:
    session_id = user["session_id"]
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        request_ids = [
            row["id"]
            for row in db.execute("SELECT id FROM recommendation_requests WHERE session_id = ?", (session_id,)).fetchall()
        ]
        if request_ids:
            placeholders = ",".join("?" for _ in request_ids)
            db.execute(f"DELETE FROM recommendation_results WHERE request_id IN ({placeholders})", request_ids)
        db.execute("DELETE FROM recommendation_requests WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM saved_places WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM recommendation_feedback WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM user_preference_signals WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user["id"],))
        db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    return {"ok": True, "deleted_user_id": user["id"]}


def auth_config() -> dict[str, Any]:
    client_id = os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    return {"google_client_id": client_id, "google_enabled": bool(client_id)}
