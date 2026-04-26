import logging
import os

_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger("app")
if not logger.handlers:
    logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
    ch = logging.StreamHandler()
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    ch.setFormatter(fmt)
    logger.addHandler(ch)

__all__ = ["logger"]
