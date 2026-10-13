from datetime import datetime, timezone

from sqlalchemy import select

from backend.models.entities import JobRecord
from backend.tools.runtime import BusinessError, serial


class JobService:
    """Database-backed queue. A worker may call run(); no broker is required for one instance."""

    def __init__(self, db, tools):
        self.db, self.tools = db, tools

    def create(self, job_type: str, idempotency_key: str, *, resource_id: str | None = None,
               dataset: dict | None = None, filename: str = "dataset.json"):
        existing = self.db.scalar(select(JobRecord).where(
            JobRecord.workspace_id == self.tools.workspace_id,
            JobRecord.idempotency_key == idempotency_key,
        ))
        if existing:
            return existing
        job = JobRecord(
            workspace_id=self.tools.workspace_id, job_type=job_type,
            idempotency_key=idempotency_key,
            payload={"resource_id": resource_id, "dataset": dataset, "filename": filename},
            max_attempts=1, correlation_id=self.tools.correlation_id, created_by=self.tools.actor,
        )
        self.db.add(job)
        self.db.commit()
        return job

    def get(self, job_id: str):
        job = self.db.get(JobRecord, job_id)
        if not job or job.workspace_id != self.tools.workspace_id:
            raise BusinessError("Job not found", "NOT_FOUND", 404)
        return job

    def run(self, job_id: str, *, claimed: bool = False):
        job = self.get(job_id)
        if job.status in {"SUCCEEDED", "FAILED"}:
            return job
        if job.status == "RUNNING" and not claimed:
            return job
        if not claimed:
            job.status, job.started_at, job.attempts = "RUNNING", datetime.now(timezone.utc), job.attempts + 1
            self.db.commit()
        try:
            resource_id = job.payload.get("resource_id")
            if job.job_type == "import_dataset":
                result = self.tools.import_dataset(
                    job.payload["dataset"], job.payload.get("filename", "dataset.json"), f"job:{job.id}"
                )
            elif job.job_type == "procurement_check":
                result = self.tools.run_full_check(resource_id)
            elif job.job_type == "generate_po_drafts":
                result = self.tools.generate_po_drafts(resource_id)
            else:
                raise BusinessError("Unsupported job type", "INVALID_JOB", 422)
            job = self.get(job_id)
            job.status, job.result = "SUCCEEDED", serial(result)
        except Exception as exc:
            self.db.rollback()
            job = self.get(job_id)
            job.status, job.error = "FAILED", f"{type(exc).__name__}: {str(exc)[:4000]}"
        job.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        return job
