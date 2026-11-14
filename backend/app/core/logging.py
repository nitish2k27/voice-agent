"""One logging setup for every process (API, agent, Celery, scripts)."""
from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # quieter third-party loggers
    for noisy in ("httpx", "httpcore", "psycopg.pool", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
