import logging

def get_logger(name: str = "gee"):
    logger = logging.getLogger(name)

    # Do NOT add handlers here. Let uvicorn/root decide the handlers.
    # Just make sure level is at least INFO.
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)

    return logger

