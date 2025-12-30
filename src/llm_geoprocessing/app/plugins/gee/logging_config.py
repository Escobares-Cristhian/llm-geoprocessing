import logging
import sys
import os
import json
import uuid
import traceback
from datetime import datetime, timezone

try:
    import psycopg2
except Exception:
    psycopg2 = None


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _chatdb_enabled() -> bool:
    postgis_enabled = os.getenv("POSTGIS_ENABLED", "false")
    chatdb_enabled = os.getenv("CHATDB_ENABLED", postgis_enabled)
    return _is_truthy(chatdb_enabled)


class _ChatDB:
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

    def ensure_schema(self) -> None:
        if not self.enabled or self._schema_ready:
            return
        conn = self._get_conn()
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS chatdb;")
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


_chatdb_singleton = None


def _get_chatdb() -> _ChatDB:
    global _chatdb_singleton
    if _chatdb_singleton is None:
        _chatdb_singleton = _ChatDB()
    return _chatdb_singleton


class ChatDBHandler(logging.Handler):
    def __init__(self, chatdb: _ChatDB) -> None:
        super().__init__()
        self.chatdb = chatdb

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not self.chatdb or not self.chatdb.enabled:
                return
            self.chatdb.ensure_schema()
            conn = self.chatdb._get_conn()
            if conn is None:
                return
            exc_text = None
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info)).strip()
            elif record.exc_text:
                exc_text = str(record.exc_text)
            extra = {"module": record.module, "lineno": record.lineno}
            extra_json = json.dumps(extra)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chatdb.logs
                        (id, ts, level, logger, message, session_id, run_id, exception_text, extra)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(uuid.uuid4()),
                        datetime.fromtimestamp(record.created, tz=timezone.utc),
                        record.levelname,
                        record.name,
                        record.getMessage(),
                        None,
                        None,
                        exc_text,
                        extra_json,
                    ),
                )
        except Exception:
            return


def _attach_chatdb_handler(logger: logging.Logger) -> None:
    chatdb = _get_chatdb()
    if not chatdb.enabled:
        return
    for h in logger.handlers:
        if isinstance(h, ChatDBHandler):
            return
    db_handler = ChatDBHandler(chatdb)
    db_handler.setLevel(logging.DEBUG)
    logger.addHandler(db_handler)

def get_logger(name: str = "gee_geoprocess"):
    logger = logging.getLogger(name)

    # Avoid duplicate handlers in case of reloads
    if logger.handlers:
        _attach_chatdb_handler(logger)
        return logger

    # Accept DEBUG and above on this logger
    logger.setLevel(logging.DEBUG)

    # Send everything to stderr (docker logs picks this up)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    _attach_chatdb_handler(logger)

    # Do not propagate to uvicorn/root (avoid double filtering / double logging)
    logger.propagate = False

    return logger
