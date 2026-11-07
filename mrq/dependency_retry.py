"""Bounded retries for pre-job startup operations, never arbitrary job bodies."""
import time

from pymongo.errors import ServerSelectionTimeoutError


def retry_mongo_selection(operation, logger, timeout=120):
    deadline = time.monotonic() + timeout
    delay = 1
    while True:
        try:
            return operation()
        except ServerSelectionTimeoutError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            logger.warning("MongoDB unavailable during worker startup; retrying")
            time.sleep(min(delay, remaining))
            if time.monotonic() >= deadline:
                raise
            delay = min(delay * 2, 10)
