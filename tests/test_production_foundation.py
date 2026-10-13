from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from backend.domain.schemas import RuleSetCreate
from backend.integrations.retry import retry_transient
from backend.models.entities import ProcurementRun
from backend.jobs.service import JobService
from backend.jobs.worker import run_one


def test_rule_snapshot_is_immutable_and_reproducible(t, data):
    t.role = "owner"
    first = t.create_rule_set(RuleSetCreate(
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc), currency="SGD",
        finance_threshold=Decimal("5000"),
    ))
    batch = t.import_dataset(data, idempotency_key="import-snapshot-1")
    from backend.demo import run_request
    request = run_request(batch["id"], datetime(2026, 9, 27).date())
    run = t.create_procurement_run(request, idempotency_key="run-snapshot-1")
    snapshot = deepcopy(run["approval_policy_snapshot"])
    t.create_rule_set(RuleSetCreate(
        effective_from=datetime(2027, 1, 1, tzinfo=timezone.utc), currency="SGD",
        finance_threshold=Decimal("100"),
    ))
    stored = t.db.get(ProcurementRun, run["id"])
    assert stored.rule_set_id == first["id"]
    assert stored.approval_policy_snapshot == snapshot
    assert t._policy(stored) == request


def test_import_and_run_idempotency(t, data):
    first = t.import_dataset(data, idempotency_key="same-import-key")
    second = t.import_dataset(deepcopy(data), idempotency_key="same-import-key")
    assert first["id"] == second["id"]
    from backend.demo import run_request
    request = run_request(first["id"], datetime(2026, 9, 27).date())
    run1 = t.create_procurement_run(request, idempotency_key="same-run-key")
    run2 = t.create_procurement_run(request, idempotency_key="same-run-key")
    assert run1["id"] == run2["id"]


def test_retry_is_bounded_and_only_for_retryable_errors():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("temporary")
        return "ok"

    assert retry_transient(flaky, retryable=lambda exc: isinstance(exc, TimeoutError),
                           attempts=3, base_delay=.5, sleep=sleeps.append) == "ok"
    assert sleeps == [.5, 1.0]

    with pytest.raises(ValueError):
        retry_transient(lambda: (_ for _ in ()).throw(ValueError("permanent")),
                        retryable=lambda exc: isinstance(exc, TimeoutError), sleep=sleeps.append)


def test_import_job_persists_state_and_is_idempotent(t, data):
    jobs = JobService(t.db, t)
    created = jobs.create("import_dataset", "job-import-key", dataset=data)
    duplicate = jobs.create("import_dataset", "job-import-key", dataset=data)
    assert created.id == duplicate.id
    completed = jobs.run(created.id)
    assert completed.status == "SUCCEEDED"
    assert completed.result["status"].startswith("VALIDATED")
    assert jobs.run(created.id).result == completed.result


def test_worker_claims_pending_job_once(t, data):
    jobs = JobService(t.db, t)
    created = jobs.create("import_dataset", "worker-import-key", dataset=data)
    factory = sessionmaker(t.db.bind, expire_on_commit=False)
    assert run_one(factory) is True
    t.db.expire_all()
    assert jobs.get(created.id).status == "SUCCEEDED"
    assert run_one(factory) is False
