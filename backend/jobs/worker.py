"""Single-process durable job worker.

Run `python -m backend.jobs.worker --once` from a scheduler or a separately managed
worker process. PostgreSQL row locking prevents two workers from claiming one job.
"""
import argparse
import time
from datetime import datetime, timezone

from sqlalchemy import select

from backend.db.session import SessionLocal
from backend.jobs.service import JobService
from backend.models.entities import JobRecord
from backend.tools.procurement import ProcurementTools


def run_one(session_factory=SessionLocal) -> bool:
    with session_factory() as db:
        query = (select(JobRecord).where(
            JobRecord.status == "PENDING", JobRecord.available_at <= datetime.now(timezone.utc),
        ).order_by(JobRecord.available_at, JobRecord.created_at, JobRecord.id).limit(1))
        if db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query)
        if job is None:
            return False
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        job.attempts += 1
        db.commit()
        tools = ProcurementTools(db, actor=f"job-worker:{job.created_by}", role="service",
                                 workspace_id=job.workspace_id, correlation_id=job.correlation_id)
        JobService(db, tools).run(job.id, claimed=True)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process persisted procurement jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    while True:
        processed = run_one()
        if args.once:
            return
        if not processed:
            time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    main()
