import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from app.core.metrics import (
    record_circuit_rejection,
    record_circuit_state,
    record_resilience_retry,
)

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    def __init__(self, component: str, retry_after_seconds: float) -> None:
        super().__init__("Circuit breaker is open.")
        self.component = component
        self.retry_after_seconds = max(0.0, retry_after_seconds)


@dataclass(frozen=True)
class TimeoutPolicy:
    timeout_seconds: float

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float
    jitter_seconds: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be zero or greater.")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be greater than base delay.")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be zero or greater.")

    def delay_for_attempt(
        self,
        attempt: int,
        *,
        random_source: Callable[[], float],
    ) -> float:
        exponential_delay = self.base_delay_seconds * (2 ** max(0, attempt - 1))
        capped_delay = min(exponential_delay, self.max_delay_seconds)
        jitter = self.jitter_seconds * random_source()
        return float(
            min(capped_delay + jitter, self.max_delay_seconds + self.jitter_seconds)
        )


@dataclass(frozen=True)
class CircuitBreakerConfig:
    enabled: bool
    failure_threshold: int
    recovery_timeout_seconds: float
    half_open_max_calls: int

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1.")
        if self.recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be greater than zero.")
        if self.half_open_max_calls < 1:
            raise ValueError("half_open_max_calls must be at least 1.")


@dataclass(frozen=True)
class ResiliencePolicy:
    timeout: TimeoutPolicy
    retry: RetryPolicy
    circuit_breaker: CircuitBreakerConfig


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    state: CircuitState
    consecutive_failure_count: int
    seconds_until_next_probe: float


class CircuitBreaker:
    def __init__(
        self,
        *,
        component: str,
        config: CircuitBreakerConfig,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._component = component
        self._config = config
        self._clock = monotonic_clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = 0
        self._half_open_successes = 0
        self._lock = asyncio.Lock()
        if self._config.enabled:
            record_circuit_state(component=self._component, state=self._state.value)

    @property
    def component(self) -> str:
        return self._component

    async def before_call(self) -> None:
        if not self._config.enabled:
            return
        async with self._lock:
            self._transition_if_recoverable()
            if self._state == CircuitState.OPEN:
                record_circuit_rejection(component=self._component)
                raise CircuitOpenError(self._component, self.retry_after_seconds())
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_in_flight >= self._config.half_open_max_calls:
                    record_circuit_rejection(component=self._component)
                    raise CircuitOpenError(self._component, self.retry_after_seconds())
                self._half_open_in_flight += 1

    async def record_success(self) -> None:
        if not self._config.enabled:
            return
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._half_open_successes += 1
                if self._half_open_successes >= self._config.half_open_max_calls:
                    self._close()
                return
            self._consecutive_failures = 0

    async def record_failure(self) -> None:
        if not self._config.enabled:
            return
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._open()
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._config.failure_threshold:
                self._open()

    def snapshot(self) -> CircuitBreakerSnapshot:
        self._transition_if_recoverable()
        return CircuitBreakerSnapshot(
            state=self._state,
            consecutive_failure_count=self._consecutive_failures,
            seconds_until_next_probe=self.retry_after_seconds(),
        )

    def retry_after_seconds(self) -> float:
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return 0.0
        elapsed = self._clock() - self._opened_at
        return max(0.0, self._config.recovery_timeout_seconds - elapsed)

    def _transition_if_recoverable(self) -> None:
        if self._state != CircuitState.OPEN:
            return
        if self.retry_after_seconds() > 0:
            return
        self._state = CircuitState.HALF_OPEN
        record_circuit_state(component=self._component, state=self._state.value)
        self._half_open_in_flight = 0
        self._half_open_successes = 0
        logger.warning(
            "circuit_half_opened",
            extra={"provider": self._component, "outcome": "half_open"},
        )

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        record_circuit_state(component=self._component, state=self._state.value)
        self._opened_at = self._clock()
        self._half_open_in_flight = 0
        self._half_open_successes = 0
        logger.warning(
            "circuit_opened",
            extra={"provider": self._component, "outcome": "open"},
        )

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        record_circuit_state(component=self._component, state=self._state.value)
        self._opened_at = None
        self._consecutive_failures = 0
        self._half_open_in_flight = 0
        self._half_open_successes = 0
        logger.info(
            "circuit_closed",
            extra={"provider": self._component, "outcome": "closed"},
        )


async def run_with_resilience[T](
    operation: Callable[[], Awaitable[T]],
    *,
    component: str,
    policy: ResiliencePolicy,
    circuit_breaker: CircuitBreaker | None,
    is_retryable: Callable[[BaseException], bool],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    random_source: Callable[[], float] = random.random,
) -> tuple[T, int]:
    if circuit_breaker is not None:
        try:
            await circuit_breaker.before_call()
        except CircuitOpenError:
            logger.warning(
                "circuit_request_rejected",
                extra={"provider": component, "outcome": "open"},
            )
            raise

    attempt = 0
    last_error: BaseException | None = None
    count_circuit_failure = False
    try:
        for attempt in range(1, policy.retry.max_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    operation(),
                    timeout=policy.timeout.timeout_seconds,
                )
                if circuit_breaker is not None:
                    await circuit_breaker.record_success()
                return result, attempt
            except Exception as exc:
                last_error = exc
                retryable = is_retryable(exc)
                count_circuit_failure = retryable
                if not retryable or attempt >= policy.retry.max_attempts:
                    raise
                delay = policy.retry.delay_for_attempt(
                    attempt,
                    random_source=random_source,
                )
                reason = failure_reason(exc)
                record_resilience_retry(
                    component=component,
                    reason=reason,
                    delay_seconds=delay,
                )
                logger.warning(
                    "provider_retry_scheduled",
                    extra={"provider": component, "outcome": reason},
                )
                await sleep(delay)
    except Exception:
        if circuit_breaker is not None and count_circuit_failure:
            await circuit_breaker.record_failure()
        raise

    raise RuntimeError("Resilience retry loop exited unexpectedly.") from last_error


def failure_reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    status_code = http_status_code(exc)
    if status_code is not None:
        return f"http_{status_code}"
    return "transient"


def http_status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


def is_transient_exception(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    status_code = http_status_code(exc)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    if status_code in {400, 401, 403, 404, 422}:
        return False
    return isinstance(exc, (ConnectionError, OSError))
