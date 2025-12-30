from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict

from llm_geoprocessing.app.chatdb.chatdb import ChatDB
from llm_geoprocessing.app.chatdb.context import get_run_id, get_session_id


class ChatDBHandler(logging.Handler):
    def __init__(self, chatdb: ChatDB) -> None:
        super().__init__()
        self.chatdb = chatdb

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not self.chatdb or not self.chatdb.enabled:
                return
            exc_text = None
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info)).strip()
            elif record.exc_text:
                exc_text = str(record.exc_text)
            extra: Dict[str, Any] = {"module": record.module, "lineno": record.lineno}
            payload = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "session_id": get_session_id(),
                "run_id": get_run_id(),
                "exception_text": exc_text,
                "extra": extra,
            }
            self.chatdb.insert_log(payload)
        except Exception:
            return
