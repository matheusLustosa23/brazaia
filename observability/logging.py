import logging
import sys

import orjson


class OrjsonFormatter(logging.Formatter):
    """Emite uma linha JSON por log (ts, level, logger, msg, + extras anexados)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if extra := getattr(record, "extra_fields", None):
            payload.update(extra)
        return orjson.dumps(payload).decode()


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(OrjsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
