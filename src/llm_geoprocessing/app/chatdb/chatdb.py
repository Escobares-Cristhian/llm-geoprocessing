from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import psycopg2
    from psycopg2.extras import Json
except Exception:
    psycopg2 = None
    Json = None


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _chatdb_enabled() -> bool:
    postgis_enabled = os.getenv("POSTGIS_ENABLED", "false")
    chatdb_enabled = os.getenv("CHATDB_ENABLED", postgis_enabled)
    return _is_truthy(chatdb_enabled)


def _uuid(value: Optional[str | uuid.UUID]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _shown_to_user(role: str, content: str) -> bool:
    if role == "system":
        return False
    if content.startswith("Generated JSON instructions:"):
        return False
    return True


class ChatDB:
    def __init__(self) -> None:
        self.enabled: bool = _chatdb_enabled() and psycopg2 is not None
        self._conn = None
        self._schema_ready = False

    def _connect(self):
        if not self.enabled or psycopg2 is None:
            return None
        try:
            conn = psycopg2.connect(
                host=os.getenv("POSTGIS_HOST", "localhost"),
                port=os.getenv("POSTGIS_PORT", "5432"),
                dbname=os.getenv("POSTGIS_DB", "geollm"),
                user=os.getenv("POSTGIS_USER", "geollm"),
                password=os.getenv("POSTGIS_PASSWORD", "geollm"),
            )
            conn.autocommit = True
            return conn
        except Exception:
            return None

    def _get_conn(self):
        if not self.enabled:
            return None
        if self._conn is not None:
            try:
                if getattr(self._conn, "closed", 1) == 0:
                    return self._conn
            except Exception:
                self._conn = None
        self._conn = self._connect()
        return self._conn

    def _json(self, value: Any):
        if value is None:
            return None
        if Json is None:
            return value
        return Json(value)

    def ensure_schema(self) -> None:
        if not self.enabled:
            return
        conn = self._get_conn()
        if conn is None:
            return
        if self._schema_ready:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS chatdb;")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chatdb.sessions (
                        id uuid PRIMARY KEY,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        title text NULL,
                        metadata jsonb
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chatdb.messages (
                        id uuid PRIMARY KEY,
                        session_id uuid REFERENCES chatdb.sessions(id),
                        role text,
                        content text,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        metadata jsonb,
                        shown_to_user boolean NOT NULL DEFAULT true
                    );
                    """
                )
                cur.execute(
                    "ALTER TABLE chatdb.messages ADD COLUMN IF NOT EXISTS shown_to_user boolean;"
                )
                cur.execute(
                    """
                    UPDATE chatdb.messages
                    SET shown_to_user = false
                    WHERE (role = 'system' OR content LIKE 'Generated JSON instructions:%')
                      AND shown_to_user IS DISTINCT FROM false;
                    """
                )
                cur.execute(
                    "UPDATE chatdb.messages SET shown_to_user = true WHERE shown_to_user IS NULL;"
                )
                cur.execute(
                    "ALTER TABLE chatdb.messages ALTER COLUMN shown_to_user SET DEFAULT true;"
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chatdb.runs (
                        id uuid PRIMARY KEY,
                        session_id uuid REFERENCES chatdb.sessions(id),
                        started_at timestamptz NOT NULL DEFAULT now(),
                        ended_at timestamptz NULL,
                        status text,
                        params jsonb
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chatdb.artifacts (
                        id uuid PRIMARY KEY,
                        run_id uuid REFERENCES chatdb.runs(id),
                        kind text,
                        uri text,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        metadata jsonb
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chatdb.logs (
                        id uuid PRIMARY KEY,
                        ts timestamptz NOT NULL DEFAULT now(),
                        level text,
                        logger text,
                        message text,
                        session_id uuid NULL,
                        run_id uuid NULL,
                        exception_text text NULL,
                        extra jsonb
                    );
                    """
                )
            self._schema_ready = True
        except Exception:
            self._conn = None
            self._schema_ready = False

    def create_session(self, title: Optional[str] = None, metadata: Optional[dict] = None) -> uuid.UUID:
        session_id = uuid.uuid4()
        if not self.enabled:
            return session_id
        self.ensure_schema()
        conn = self._get_conn()
        if conn is None:
            return session_id
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatdb.sessions (id, created_at, title, metadata)
                    VALUES (%s, now(), %s, %s)
                    """,
                    (_uuid(session_id), title, self._json(metadata)),
                )
        except Exception:
            self._conn = None
        return session_id

    def insert_message(
        self,
        session_id: str | uuid.UUID,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        shown_to_user: Optional[bool] = None,
    ) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        conn = self._get_conn()
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatdb.messages
                        (id, session_id, role, content, created_at, metadata, shown_to_user)
                    VALUES (%s, %s, %s, %s, now(), %s, %s)
                    """,
                    (
                        _uuid(uuid.uuid4()),
                        _uuid(session_id),
                        role,
                        content,
                        self._json(metadata),
                        bool(_shown_to_user(role, content) if shown_to_user is None else shown_to_user),
                    ),
                )
        except Exception:
            self._conn = None

    def start_run(self, session_id: Optional[str | uuid.UUID] = None, params: Optional[dict] = None) -> uuid.UUID:
        run_id = uuid.uuid4()
        if not self.enabled:
            return run_id
        self.ensure_schema()
        conn = self._get_conn()
        if conn is None:
            return run_id
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatdb.runs (id, session_id, started_at, status, params)
                    VALUES (%s, %s, now(), %s, %s)
                    """,
                    (_uuid(run_id), _uuid(session_id), "running", self._json(params)),
                )
        except Exception:
            self._conn = None
        return run_id

    def finish_run(self, run_id: str | uuid.UUID, status: str, extra: Optional[dict] = None) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        conn = self._get_conn()
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                if extra is None:
                    cur.execute(
                        "UPDATE chatdb.runs SET ended_at = now(), status = %s WHERE id = %s",
                        (status, _uuid(run_id)),
                    )
                else:
                    extra_json = json.dumps(extra)
                    cur.execute(
                        """
                        UPDATE chatdb.runs
                        SET ended_at = now(),
                            status = %s,
                            params = COALESCE(params, '{}'::jsonb) || %s::jsonb
                        WHERE id = %s
                        """,
                        (status, extra_json, _uuid(run_id)),
                    )
        except Exception:
            self._conn = None

    def insert_artifact(
        self,
        run_id: str | uuid.UUID,
        kind: str,
        uri: str,
        metadata: Optional[dict] = None,
    ) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        conn = self._get_conn()
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatdb.artifacts (id, run_id, kind, uri, created_at, metadata)
                    VALUES (%s, %s, %s, %s, now(), %s)
                    """,
                    (_uuid(uuid.uuid4()), _uuid(run_id), kind, uri, self._json(metadata)),
                )
        except Exception:
            self._conn = None

    def insert_log(self, record: dict) -> None:
        if not self.enabled:
            return
        self.ensure_schema()
        conn = self._get_conn()
        if conn is None:
            return
        try:
            ts = record.get("ts") or datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatdb.logs
                        (id, ts, level, logger, message, session_id, run_id, exception_text, extra)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        _uuid(uuid.uuid4()),
                        ts,
                        record.get("level"),
                        record.get("logger"),
                        record.get("message"),
                        _uuid(record.get("session_id")),
                        _uuid(record.get("run_id")),
                        record.get("exception_text"),
                        self._json(record.get("extra")),
                    ),
                )
        except Exception:
            self._conn = None


_chatdb_singleton: Optional[ChatDB] = None


def get_chatdb() -> ChatDB:
    global _chatdb_singleton
    if _chatdb_singleton is None:
        _chatdb_singleton = ChatDB()
    return _chatdb_singleton
