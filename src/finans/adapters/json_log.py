import json
import logging
from datetime import UTC, datetime

_FIELDS = ("job", "run_id", "logical_date", "status", "instrument")


class JsonFormatter(logging.Formatter):
    """journald için tek satır JSON (K-81); iş alanları `extra` ile gelir."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in _FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                entry[name] = str(value) if not isinstance(value, int) else value
        return json.dumps(entry, ensure_ascii=False)
