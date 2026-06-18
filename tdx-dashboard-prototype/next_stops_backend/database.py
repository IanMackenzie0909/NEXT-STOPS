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
