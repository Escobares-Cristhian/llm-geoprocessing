import logging
import sys

def get_logger(name: str = "gee_geoprocess"):
    logger = logging.getLogger(name)

    # Avoid duplicate handlers in case of reloads
    if logger.handlers:
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

    # Do not propagate to uvicorn/root (avoid double filtering / double logging)
    logger.propagate = False

    return logger

