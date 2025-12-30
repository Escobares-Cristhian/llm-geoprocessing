import logging
import sys
import os

def _attach_chatdb_handler(logger: logging.Logger, level: int) -> None:
    try:
        from llm_geoprocessing.app.chatdb import get_chatdb
        from llm_geoprocessing.app.chatdb.log_handler import ChatDBHandler
    except Exception:
        return

    chatdb = get_chatdb()
    if not chatdb.enabled:
        return
    for h in logger.handlers:
        if isinstance(h, ChatDBHandler):
            return
    db_handler = ChatDBHandler(chatdb)
    db_handler.setLevel(level)
    logger.addHandler(db_handler)

def get_logger(name: str = "geollm"):
    logger = logging.getLogger(name)

    # Read desired level from env, default INFO
    level_name = os.getenv("GEOLLM_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger.setLevel(level)
    if logger.handlers:
        _attach_chatdb_handler(logger, level)
        return logger  # avoid duplicate handlers on reloads

    handler = logging.StreamHandler(sys.stderr)  # dev logs -> stderr
    handler.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    _attach_chatdb_handler(logger, level)
    return logger
