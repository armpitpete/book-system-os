from __future__ import annotations

import os
import time
from pathlib import Path

from app.pipeline.run_pipeline import run_pipeline
from app.services.job_queue import queued_jobs, read_status, write_status

POLL_SECONDS = float(os.getenv("BOOK_WORKER_POLL_SECONDS", "2"))


def acquire_lock(job_dir: Path) -> bool:
    lock = job_dir / ".lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock(job_dir: Path) -> None:
    lock = job_dir / ".lock"
    if lock.exists():
        lock.unlink()


def process_next_jobs() -> int:
    processed = 0
    for job in queued_jobs():
        if not acquire_lock(job):
            continue
        try:
            status = read_status(job)
            if status.get("status") != "queued":
                continue
            write_status(job, status="running", step="worker", message="Worker started job")
            run_pipeline(job)
            processed += 1
        finally:
            release_lock(job)
    return processed


def run_forever() -> None:
    print("Book System worker started")
    while True:
        processed = process_next_jobs()
        if processed == 0:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
