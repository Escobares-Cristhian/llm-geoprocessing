import logging
import sys
import os

def get_logger(name: str = "geollm"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid duplicate handlers on reloads

    # Read desired level from env, default INFO
    level_name = os.getenv("GEOLLM_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)  # dev logs -> stderr
    handler.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger

