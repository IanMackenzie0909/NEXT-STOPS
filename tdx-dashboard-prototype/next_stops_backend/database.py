"""Database connection helpers for NEXT STOPS.

The app uses PostgreSQL when DATABASE_URL is configured, and falls back to
SQLite for local development.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - PostgreSQL is optional for local SQLite mode.
    psycopg = None
    dict_row = None


BACKEND_ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATION_DB = Path(os.getenv("NEXT_STOPS_DB_PATH", BACKEND_ROOT / "data" / "next_stops.sqlite3"))
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("NEXT_STOPS_DATABASE_URL")
    or ""
)
USE_POSTGRES = bool(DATABASE_URL)


def convert_sql_for_postgres(sql: str) -> str:
    return (
        sql
        .replace("?", "%s")
        .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    )


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class PostgresConnection:
    def __init__(self):
        if psycopg is None:
            raise RuntimeError("PostgreSQL mode requires psycopg. Install dependencies with: pip install -r requirements.txt")
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
        return False

    def execute(self, sql: str, params: tuple | list | None = None):
        cursor = self.conn.execute(convert_sql_for_postgres(sql), params or ())
        return PostgresCursor(cursor)

    def executemany(self, sql: str, seq_of_params):
        cursor = self.conn.cursor()
        cursor.executemany(convert_sql_for_postgres(sql), seq_of_params)
        return PostgresCursor(cursor)


def connect_recommendation_db():
    if USE_POSTGRES:
        return PostgresConnection()
    return sqlite3.connect(RECOMMENDATION_DB)


def init_recommendation_db() -> None:
    if not USE_POSTGRES:
        RECOMMENDATION_DB.parent.mkdir(parents=True, exist_ok=True)
    with connect_recommendation_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_requests (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                session_id TEXT,
                criteria_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                source_status_json TEXT NOT NULL,
                result_count INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                place_id TEXT NOT NULL,
                place_name TEXT NOT NULL,
                score REAL NOT NULL,
                uncertainty REAL NOT NULL,
                reason TEXT,
                result_json TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES recommendation_requests(id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_recommendation_results_request ON recommendation_results(request_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                place_id TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT,
                address TEXT,
                lat REAL,
                lng REAL,
                note TEXT,
                place_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(session_id, place_id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_saved_places_session ON saved_places(session_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT,
                place_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_session ON recommendation_feedback(session_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preference_signals (
                session_id TEXT PRIMARY KEY,
                signals_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                account TEXT UNIQUE,
                email TEXT,
                display_name TEXT NOT NULL,
                avatar_url TEXT,
                password_hash TEXT,
                google_sub TEXT UNIQUE,
                preferences_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account ON users(account) WHERE account IS NOT NULL")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub) WHERE google_sub IS NOT NULL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")
