import logging
import sys

def get_logger(name: str = "geollm"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid duplicate handlers on reloads

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stderr)  # dev logs -> stderr
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger

