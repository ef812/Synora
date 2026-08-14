import logging
import json
from datetime import datetime, timezone

logger = logging.getLogger("synora")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def log_event(event_type: str, **fields):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **fields,
    }
    logger.info(json.dumps(entry))