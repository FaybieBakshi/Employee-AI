"""
retry_handler.py — Retry logic + Circuit Breaker for error recovery (Gold Tier).

Provides:
  @with_retry          — decorator for exponential backoff retry
  CircuitBreaker       — prevents hammering a failing external service
  safe_call()          — wrapper that combines retry + circuit breaker + fallback

Error categories from the hackathon doc:
  Transient  — network timeout, rate limit → retry with backoff
  Auth       — expired token → alert human, pause
  Logic      — bad input → move to error queue
  Data       — corrupted file → quarantine
  System     — crash, disk full → watchdog + restart
"""

import functools
import logging
import time
from enum import Enum
from typing import Callable, Any, Optional

logger = logging.getLogger("recovery")


# ──────────────────────────────────────────────────────────────────────
# Custom exceptions
# ──────────────────────────────────────────────────────────────────────

class TransientError(Exception):
    """Retriable error (network, rate limit, timeout)."""


class AuthError(Exception):
    """Authentication / permission error — do not retry, alert human."""


class DataError(Exception):
    """Data / parsing error — quarantine the item."""


# ──────────────────────────────────────────────────────────────────────
# Retry decorator
# ──────────────────────────────────────────────────────────────────────

def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (TransientError, ConnectionError, TimeoutError),
):
    """
    Decorator: retry a function with exponential backoff.

    Usage:
        @with_retry(max_attempts=3, base_delay=2)
        def call_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_err = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as err:
                    last_err = err
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {err}")
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    logger.warning(f"{func.__name__} attempt {attempt}/{max_attempts} failed: {err}. Retrying in {delay:.1f}s")
                    time.sleep(delay)
            raise last_err
        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────────────
# Circuit Breaker
# ──────────────────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED = "closed"      # Normal — requests go through
    OPEN = "open"          # Tripped — requests blocked
    HALF_OPEN = "half_open"  # Testing — one request allowed


class CircuitBreaker:
    """
    Circuit Breaker pattern: prevents repeated calls to a failing service.

    States:
      CLOSED   → normal operation
      OPEN     → failure threshold exceeded, blocking all calls for reset_timeout
      HALF_OPEN → after timeout, allow one probe call to test recovery

    Usage:
        cb = CircuitBreaker("gmail", failure_threshold=3, reset_timeout=60)

        try:
            result = cb.call(gmail_api_function, arg1, arg2)
        except CircuitOpenError:
            # Service unavailable — use fallback
            ...
    """

    class CircuitOpenError(Exception):
        """Raised when the circuit is OPEN and calls are blocked."""

    def __init__(self, name: str, failure_threshold: int = 3, reset_timeout: float = 60.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN (probing)")
        return self._state

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Call func through the circuit breaker."""
        s = self.state
        if s == CircuitState.OPEN:
            raise self.CircuitOpenError(
                f"Circuit {self.name!r} is OPEN — service unavailable. "
                f"Retry in {max(0, self.reset_timeout - (time.time() - self._opened_at)):.0f}s"
            )
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as err:
            self._on_failure(err)
            raise

    def _on_success(self) -> None:
        self._failures = 0
        if self._state != CircuitState.CLOSED:
            logger.info(f"Circuit {self.name}: recovered → CLOSED")
        self._state = CircuitState.CLOSED

    def _on_failure(self, err: Exception) -> None:
        self._failures += 1
        logger.warning(f"Circuit {self.name}: failure {self._failures}/{self.failure_threshold} — {err}")
        if self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
            logger.error(f"Circuit {self.name}: TRIPPED → OPEN (will retry in {self.reset_timeout}s)")

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        self._failures = 0
        self._state = CircuitState.CLOSED
        logger.info(f"Circuit {self.name}: manually reset to CLOSED")


# ──────────────────────────────────────────────────────────────────────
# Safe call wrapper
# ──────────────────────────────────────────────────────────────────────

def safe_call(
    func: Callable,
    *args,
    fallback: Any = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    max_attempts: int = 3,
    **kwargs,
) -> Any:
    """
    Call func with retry + optional circuit breaker + fallback.

    If all retries fail, returns fallback value instead of raising.
    Logs all failures for audit purposes.

    Usage:
        result = safe_call(
            gmail_api.send,
            to="x@example.com",
            subject="Hi",
            fallback={"queued": True},
            circuit_breaker=gmail_circuit,
        )
    """
    @with_retry(max_attempts=max_attempts)
    def _inner():
        if circuit_breaker:
            return circuit_breaker.call(func, *args, **kwargs)
        return func(*args, **kwargs)

    try:
        return _inner()
    except CircuitBreaker.CircuitOpenError as err:
        logger.warning(f"safe_call: circuit open for {func.__name__}: {err}")
        return fallback
    except Exception as err:
        logger.error(f"safe_call: {func.__name__} failed permanently: {err}")
        return fallback


# ──────────────────────────────────────────────────────────────────────
# Pre-built circuit breakers (shared singletons)
# ──────────────────────────────────────────────────────────────────────

CIRCUITS: dict[str, CircuitBreaker] = {
    "gmail": CircuitBreaker("gmail", failure_threshold=3, reset_timeout=120),
    "odoo": CircuitBreaker("odoo", failure_threshold=3, reset_timeout=60),
    "facebook": CircuitBreaker("facebook", failure_threshold=3, reset_timeout=300),
    "twitter": CircuitBreaker("twitter", failure_threshold=3, reset_timeout=300),
    "smtp": CircuitBreaker("smtp", failure_threshold=2, reset_timeout=120),
    "playwright": CircuitBreaker("playwright", failure_threshold=3, reset_timeout=30),
}


def get_circuit(name: str) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    if name not in CIRCUITS:
        CIRCUITS[name] = CircuitBreaker(name)
    return CIRCUITS[name]
