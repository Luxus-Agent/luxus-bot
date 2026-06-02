"""
Central logging configuration.

Called once at app startup (app.main) so that:
  • all logs get a consistent, timestamped, level-tagged format
  • uvicorn's own loggers share that format (so access lines get timestamps too)
  • the verbosity is controlled by settings.LOG_LEVEL (DEBUG/INFO/WARNING/ERROR)

Usage in code — just grab a module logger and log:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("something happened: id=%s", some_id)
    logger.debug("verbose detail only shown when LOG_LEVEL=DEBUG")
    logger.exception("failed")   # inside an `except` block — logs full traceback
"""
import logging
import sys

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """Configure root + uvicorn loggers with a single timestamped handler."""
    log_level = getattr(logging, str(level).upper(), logging.INFO)
    formatter = logging.Formatter(_FORMAT, _DATEFMT)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Root logger — replace handlers so we don't stack duplicates on --reload.
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [handler]

    # Make uvicorn's loggers use the same format and level (no double-printing).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
        lg.setLevel(log_level)

    # Our application namespace.
    logging.getLogger("app").setLevel(log_level)

    logging.getLogger(__name__).info("Logging configured at level %s", level.upper())
