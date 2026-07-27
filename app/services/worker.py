from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from app.pipeline.run_pipeline import run_pipeline
from app.services.job_queue import queued_jobs, read_status, write_status
from app.services.job_recovery import (
    RecoveryError,
    acquire_job_lock,
    refresh_job_lock,
    release_job_lock,
)
from app.services.readiness import WorkerServiceHeartbeat

POLL_SECONDS = float(os.getenv("BOOK_WORKER_POLL_SECONDS", "2"))
HEARTBEAT_SECONDS = max(
    1.0,
    float(os.getenv("BOOK_WORKER_HEARTBEAT_SECONDS", "5")),
)


def acquire_lock(job_dir: Path) -> bool:
    return acquire_job_lock(job_dir) is not None


def release_lock(job_dir: Path) -> None:
    release_job_lock(job_dir)


def _heartbeat_loop(job_dir: Path, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            if not refresh_job_lock(job_dir):
                print(f"Worker lock disappeared for {job_dir.name}", flush=True)
                return
        except RecoveryError as exc:
            print(f"Worker heartbeat stopped for {job_dir.name}: {exc}", flush=True)
            return


def process_jobs(
    jobs: list[Path],
    service_heartbeat: WorkerServiceHeartbeat | None = None,
) -> int:
    processed = 0
    for job in jobs:
        if not acquire_lock(job):
            continue

        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None

        try:
            status = read_status(job)
            if status.get("status") != "queued":
                continue

            write_status(
                job,
                status="running",
                step="worker",
                message="Worker started job",
            )
            if service_heartbeat is not None:
                service_heartbeat.set_state("running")

            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                args=(job, heartbeat_stop),
                name=f"book-worker-heartbeat-{job.name}",
                daemon=True,
            )
            heartbeat_thread.start()
            run_pipeline(job)
            processed += 1
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=HEARTBEAT_SECONDS + 1.0)
            release_lock(job)
            if service_heartbeat is not None:
                service_heartbeat.set_state("idle")

    return processed


def process_next_jobs(
    service_heartbeat: WorkerServiceHeartbeat | None = None,
) -> int:
    return process_jobs(queued_jobs(), service_heartbeat)


def run_forever() -> None:
    service_heartbeat = WorkerServiceHeartbeat()
    service_heartbeat.start()
    startup_complete = False

    try:
        while True:
            try:
                jobs = queued_jobs()
            except OSError as exc:
                service_heartbeat.set_state("starting")
                print(
                    f"Worker queue scan unavailable: {type(exc).__name__}",
                    flush=True,
                )
                time.sleep(POLL_SECONDS)
                continue

            service_heartbeat.set_state("idle")
            if not startup_complete:
                print("Book System worker started", flush=True)
                startup_complete = True

            processed = process_jobs(jobs, service_heartbeat)
            if processed == 0:
                time.sleep(POLL_SECONDS)
    finally:
        service_heartbeat.stop()


if __name__ == "__main__":
    run_forever()
