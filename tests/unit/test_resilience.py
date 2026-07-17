import asyncio

import pytest

from app.core.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    ResiliencePolicy,
    RetryPolicy,
    TimeoutPolicy,
    run_with_resilience,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class AttemptOperation:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return str(outcome)


@pytest.mark.anyio
async def test_retry_policy_success_on_first_attempt() -> None:
    operation = AttemptOperation(["ok"])
    sleeps: list[float] = []

    result, attempts = await run_with_resilience(
        operation,
        component="test",
        policy=_policy(),
        circuit_breaker=None,
        is_retryable=lambda exc: True,
        sleep=_sleep_recorder(sleeps),
        random_source=lambda: 0,
    )

    assert result == "ok"
    assert attempts == 1
    assert operation.calls == 1
    assert sleeps == []


@pytest.mark.anyio
async def test_retry_policy_transient_failure_then_success() -> None:
    operation = AttemptOperation([ConnectionError(), "ok"])
    sleeps: list[float] = []

    result, attempts = await run_with_resilience(
        operation,
        component="test",
        policy=_policy(base_delay=0.5, jitter=0.1),
        circuit_breaker=None,
        is_retryable=lambda exc: isinstance(exc, ConnectionError),
        sleep=_sleep_recorder(sleeps),
        random_source=lambda: 0.5,
    )

    assert result == "ok"
    assert attempts == 2
    assert sleeps == [0.55]


@pytest.mark.anyio
async def test_retry_policy_exhausts_attempts() -> None:
    operation = AttemptOperation([ConnectionError(), ConnectionError()])

    with pytest.raises(ConnectionError):
        await run_with_resilience(
            operation,
            component="test",
            policy=_policy(max_attempts=2),
            circuit_breaker=None,
            is_retryable=lambda exc: isinstance(exc, ConnectionError),
            sleep=_sleep_recorder([]),
            random_source=lambda: 0,
        )

    assert operation.calls == 2


@pytest.mark.anyio
async def test_non_retryable_failure_is_not_retried() -> None:
    operation = AttemptOperation([ValueError()])

    with pytest.raises(ValueError):
        await run_with_resilience(
            operation,
            component="test",
            policy=_policy(max_attempts=3),
            circuit_breaker=None,
            is_retryable=lambda exc: False,
            sleep=_sleep_recorder([]),
            random_source=lambda: 0,
        )

    assert operation.calls == 1


def test_exponential_delay_progression_cap_and_bounded_jitter() -> None:
    policy = RetryPolicy(
        max_attempts=4,
        base_delay_seconds=0.5,
        max_delay_seconds=1.0,
        jitter_seconds=0.25,
    )

    assert policy.delay_for_attempt(1, random_source=lambda: 1.0) == 0.75
    assert policy.delay_for_attempt(2, random_source=lambda: 1.0) == 1.25
    assert policy.delay_for_attempt(3, random_source=lambda: 1.0) == 1.25


@pytest.mark.anyio
async def test_circuit_breaker_starts_closed_and_opens_at_threshold() -> None:
    breaker = _breaker(failure_threshold=2)

    assert breaker.snapshot().state == CircuitState.CLOSED
    await breaker.record_failure()
    assert breaker.snapshot().state == CircuitState.CLOSED
    await breaker.record_failure()
    assert breaker.snapshot().state == CircuitState.OPEN


@pytest.mark.anyio
async def test_circuit_breaker_rejects_while_open_with_retry_after() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, clock=clock)
    await breaker.record_failure()

    with pytest.raises(CircuitOpenError) as exc_info:
        await breaker.before_call()

    assert exc_info.value.retry_after_seconds == 10.0


@pytest.mark.anyio
async def test_circuit_breaker_half_open_recovery_and_close() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery=10, clock=clock)
    await breaker.record_failure()
    clock.advance(10)

    await breaker.before_call()
    assert breaker.snapshot().state == CircuitState.HALF_OPEN
    await breaker.record_success()

    snapshot = breaker.snapshot()
    assert snapshot.state == CircuitState.CLOSED
    assert snapshot.consecutive_failure_count == 0


@pytest.mark.anyio
async def test_circuit_breaker_reopens_after_failed_probe() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery=10, clock=clock)
    await breaker.record_failure()
    clock.advance(10)

    await breaker.before_call()
    await breaker.record_failure()

    assert breaker.snapshot().state == CircuitState.OPEN


@pytest.mark.anyio
async def test_closed_success_resets_consecutive_failures() -> None:
    breaker = _breaker(failure_threshold=2)

    await breaker.record_failure()
    await breaker.record_success()

    assert breaker.snapshot().consecutive_failure_count == 0


@pytest.mark.anyio
async def test_concurrent_half_open_calls_respect_probe_limit() -> None:
    clock = FakeClock()
    breaker = _breaker(
        failure_threshold=1,
        recovery=10,
        half_open_max_calls=1,
        clock=clock,
    )
    await breaker.record_failure()
    clock.advance(10)

    await breaker.before_call()
    with pytest.raises(CircuitOpenError):
        await breaker.before_call()


def _policy(
    *,
    max_attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 1.0,
    jitter: float = 0.0,
) -> ResiliencePolicy:
    return ResiliencePolicy(
        timeout=TimeoutPolicy(timeout_seconds=1),
        retry=RetryPolicy(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay,
            max_delay_seconds=max_delay,
            jitter_seconds=jitter,
        ),
        circuit_breaker=CircuitBreakerConfig(
            enabled=False,
            failure_threshold=1,
            recovery_timeout_seconds=1,
            half_open_max_calls=1,
        ),
    )


def _breaker(
    *,
    failure_threshold: int = 1,
    recovery: float = 10.0,
    half_open_max_calls: int = 1,
    clock: FakeClock | None = None,
) -> CircuitBreaker:
    return CircuitBreaker(
        component="test",
        config=CircuitBreakerConfig(
            enabled=True,
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=recovery,
            half_open_max_calls=half_open_max_calls,
        ),
        monotonic_clock=clock or FakeClock(),
    )


def _sleep_recorder(sleeps: list[float]):
    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    return sleep
