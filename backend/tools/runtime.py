import json
import logging
import hashlib
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from sqlalchemy import inspect
from backend.models.entities import ToolExecutionLog

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
            self.db.add(ToolExecutionLog(tool_name=fn.__name__, actor=self.actor, status="SUCCESS",
                                        input=inputs, output=logged_output))
            self.db.commit()
            return output
        except Exception as exc:
            self.db.rollback()
            self.db.add(ToolExecutionLog(tool_name=fn.__name__, actor=self.actor, status="FAILED",
                input=inputs, output=None, error=f"{type(exc).__name__}: {str(exc)[:4000]}"))
            self.db.commit()
            if not isinstance(exc, BusinessError):
                logger.exception("Tool %s failed", fn.__name__)
            raise
    return wrapper
