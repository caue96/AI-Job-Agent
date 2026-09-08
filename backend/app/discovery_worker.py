"""Small database-backed scheduler suitable for cron or the optional Compose worker."""

from __future__ import annotations

import argparse
import logging
import time

from app.config import get_settings
from app.db import SessionLocal
from app.discovery import run_due_searches
from app.repositories import SqlAlchemyUnitOfWork

logger = logging.getLogger("app.discovery.worker")


def tick() -> list[str]:
    with SessionLocal() as db:
        uow = SqlAlchemyUnitOfWork(db)
        run_ids = run_due_searches(uow, get_settings())
        uow.commit()
        return run_ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Run due job-discovery searches")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int)
    args = parser.parse_args()
    settings = get_settings()
    interval = args.poll_seconds or settings.discovery_scheduler_poll_seconds
    while True:
        try:
            tick()
        except Exception:  # scheduler boundary must survive one failed tick
            logger.exception("discovery.scheduler.tick_failed")
        if args.once:
            return
        time.sleep(min(max(interval, 15), 60))


if __name__ == "__main__":
    main()
