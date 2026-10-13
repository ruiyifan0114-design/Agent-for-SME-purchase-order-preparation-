import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_transient(operation: Callable[[], T], *, retryable: Callable[[Exception], bool],
                    attempts: int = 3, base_delay: float = 0.1,
                    sleep: Callable[[float], None] = time.sleep) -> T:
    """Retry explicitly safe transient operations; never wrap ambiguous writes."""
    if attempts < 1 or attempts > 5:
        raise ValueError("attempts must be between 1 and 5")
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if attempt == attempts - 1 or not retryable(exc):
                raise
            sleep(base_delay * (2 ** attempt))
    raise RuntimeError("unreachable")
