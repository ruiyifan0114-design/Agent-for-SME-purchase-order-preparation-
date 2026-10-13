import json
import logging
import time
from collections import Counter
from threading import Lock
from uuid import uuid4

from fastapi import Request

log = logging.getLogger("supplydesk.request")
_counts = Counter()
_lock = Lock()


def increment(name: str, value: int = 1, **labels):
    key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
    with _lock:
        _counts[key] += value


def metrics_snapshot():
    with _lock:
        return [{"metric": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(_counts.items())]


async def request_context(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", "").strip()[:64] or str(uuid4())
    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000)
    response.headers["X-Correlation-ID"] = correlation_id
    increment("http_requests_total", method=request.method, status=response.status_code)
    increment("http_request_duration_ms_total", value=duration_ms, method=request.method)
    log.info(json.dumps({"event": "http_request", "method": request.method,
                         "path": request.url.path, "status": response.status_code,
                         "duration_ms": duration_ms, "correlation_id": correlation_id}))
    return response
