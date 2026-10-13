import json
import logging
import hashlib
import time
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from sqlalchemy import inspect
from backend.models.entities import ToolExecutionLog
from backend.observability import increment

logger = logging.getLogger(__name__)


class BusinessError(Exception):
    def __init__(self, message, code="BUSINESS_RULE", status=409):
        self.message, self.code, self.status = message, code, status
        super().__init__(message)


def serial(value):
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__table__"):
        return {c.key: serial(getattr(value, c.key)) for c in inspect(value).mapper.column_attrs}
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def audited(fn):
    """Each atomic tool commits state and success together; failures roll back then log separately."""
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        started = time.perf_counter()
        inputs = serial({"args": args, "kwargs": kwargs})
        # Keep logs bounded; the full import data is retained in import_batch.
        if len(json.dumps(inputs)) > 20_000:
            inputs = {"note": "Large input retained in import batch"}
        try:
            result = fn(self, *args, **kwargs)
            self.db.flush()
            output = serial(result)
            # Audit listing must not recursively embed previous audit listings.
            logged_output = output
            if fn.__name__ == "list_resources":
                logged_output = {"count": len(output), "ids": [r["id"] for r in output]}
            elif fn.__name__ in {"import_dataset", "import_files"}:
                logged_output = {k: output[k] for k in ("id", "status", "source_hash")}
            duration_ms = round((time.perf_counter() - started) * 1000)
            self.db.add(ToolExecutionLog(workspace_id=self.workspace_id, tool_name=fn.__name__, actor=self.actor,
                                        user_id=self.user_id, correlation_id=self.correlation_id,
                                        duration_ms=duration_ms, status="SUCCESS", input=inputs, output=logged_output))
            increment("tool_executions_total", tool=fn.__name__, status="success")
            increment("tool_duration_ms_total", value=duration_ms, tool=fn.__name__)
            self.db.commit()
            return output
        except Exception as exc:
            self.db.rollback()
            duration_ms = round((time.perf_counter() - started) * 1000)
            self.db.add(ToolExecutionLog(workspace_id=self.workspace_id, tool_name=fn.__name__, actor=self.actor,
                user_id=self.user_id, correlation_id=self.correlation_id, duration_ms=duration_ms, status="FAILED",
                input=inputs, output=None, error=f"{type(exc).__name__}: {str(exc)[:4000]}"))
            increment("tool_executions_total", tool=fn.__name__, status="failed")
            increment("tool_duration_ms_total", value=duration_ms, tool=fn.__name__)
            self.db.commit()
            if not isinstance(exc, BusinessError):
                logger.exception("Tool %s failed", fn.__name__)
            raise
    return wrapper
