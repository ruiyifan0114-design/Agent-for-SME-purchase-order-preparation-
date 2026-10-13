"""Resilient, read-only model provider boundary.

Retries are limited to model inference requests. Domain writes are never invoked here.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.config import settings
from backend.tools.runtime import BusinessError


@dataclass
class ProviderResult:
    body: dict
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class CircuitBreaker:
    def __init__(self):
        self.failures = 0
        self.opened_at = 0.0
        self.lock = Lock()

    def before(self):
        cfg = settings()
        with self.lock:
            if self.failures >= cfg.agent_circuit_failure_threshold:
                if time.monotonic() - self.opened_at < cfg.agent_circuit_cooldown_seconds:
                    raise BusinessError("The model circuit is open; no action was taken", "AGENT_CIRCUIT_OPEN", 503)
                self.failures = 0

    def success(self):
        with self.lock:
            self.failures = 0
            self.opened_at = 0.0

    def failure(self):
        with self.lock:
            self.failures += 1
            self.opened_at = time.monotonic()


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = Lock()


def _breaker(name: str) -> CircuitBreaker:
    with _breakers_lock:
        return _breakers.setdefault(name, CircuitBreaker())


def reset_circuits():
    """Test/operations hook; does not affect procurement state."""
    with _breakers_lock:
        _breakers.clear()


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, key: str):
        self.key = key

    def complete(self, payload: dict, timeout: float) -> ProviderResult:
        model = str(payload["model"])
        breaker = _breaker(f"{self.name}:{model}")
        last_error: Exception | None = None
        for attempt in range(max(1, settings().agent_model_attempts)):
            breaker.before()
            request = Request(
                "https://api.deepseek.com/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                usage = body.get("usage") or {}
                breaker.success()
                return ProviderResult(body, self.name, model,
                                      int(usage.get("prompt_tokens") or 0),
                                      int(usage.get("completion_tokens") or 0))
            except HTTPError as exc:
                last_error = exc
                transient = exc.code == 429 or 500 <= exc.code < 600
                if not transient:
                    breaker.failure()
                    raise BusinessError(f"Model request failed (HTTP {exc.code}); no action was taken",
                                        "AGENT_UNAVAILABLE", 502) from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            breaker.failure()
            if attempt + 1 < max(1, settings().agent_model_attempts):
                time.sleep(min(0.25 * (2 ** attempt), 1.0))
        raise BusinessError("The model is temporarily unavailable; no action was taken",
                            "AGENT_UNAVAILABLE", 502) from last_error


def complete_with_fallback(payload: dict, key: str, timeout: float) -> ProviderResult:
    provider = DeepSeekProvider(key)
    try:
        return provider.complete(payload, timeout)
    except BusinessError:
        fallback = settings().deepseek_fallback_model.strip()
        if not fallback or fallback == payload.get("model"):
            raise
        next_payload = {**payload, "model": fallback}
        return provider.complete(next_payload, timeout)
