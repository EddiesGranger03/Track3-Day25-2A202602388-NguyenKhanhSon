"""Concurrency and retry-budget regressions found during the reliability review."""

from __future__ import annotations

import pytest

from gameday_lab.breaker import BreakerState
from gameday_lab.client import ResilientClient
from gameday_lab.sim.contracts import Attempt, CallContext, GiveUp, ProviderError, ProviderInfo, Send


def make_client(order: tuple[str, ...] = ("alpha", "beta"), tokens: float = 2.0,
                min_calls: int = 5) -> ResilientClient:
    providers = {name: ProviderInfo(name, name, "us", True, 1.0) for name in order}
    settings = {
        "attempt_timeout_s": 8.0,
        "max_attempts_per_provider": 2,
        "min_time_left_s": 1.0,
        "retry_budget_ratio": 0.0,
        "retry_budget_min_per_s": 0.0,
        "retry_budget_max_tokens": tokens,
        "quota_cooldown_s": 300.0,
        "breaker": {"min_calls": min_calls, "half_open_max_probes": 1, "half_open_successes": 1},
    }
    return ResilientClient(providers, order, settings, seed=7)


def new_call(cid: int = 1, deadline: float = 30.0) -> CallContext:
    return CallContext(cid, cid, "tool", 0.0, deadline)


def start(client: ResilientClient, call: CallContext, now: float = 0.0) -> Send:
    action = client.start(call, now)
    assert isinstance(action, Send)
    return action


def fail(client: ResilientClient, call: CallContext, send: Send, now: float,
         code: str = "rate_limit_exceeded", retry_after: float | None = 0.25) -> Send | GiveUp:
    status = 500 if code == "api_error" else 429
    action = client.on_error(Attempt(call, send.provider, 1, now, send.tag),
                             ProviderError(send.provider, status, code, retry_after=retry_after), now)
    assert isinstance(action, (Send, GiveUp))
    return action


@pytest.mark.parametrize(
    ("first_code", "first_retry_after", "second_code", "second_retry_after", "expected_until"),
    [
        ("rate_limit_exceeded", 10.0, "rate_limit_exceeded", 1.0, 11.0),
        ("insufficient_quota", None, "rate_limit_exceeded", 1.0, 301.0),
        ("rate_limit_exceeded", 600.0, "insufficient_quota", None, 601.0),
    ],
)
def test_concurrent_errors_cannot_shorten_shared_cooldown(
    first_code: str, first_retry_after: float | None, second_code: str,
    second_retry_after: float | None, expected_until: float,
) -> None:
    client = make_client()
    first_call, second_call = new_call(1), new_call(2)
    first, second = start(client, first_call), start(client, second_call)
    fail(client, first_call, first, 1.0, first_code, first_retry_after)
    fail(client, second_call, second, 1.1, second_code, second_retry_after)

    assert client.cooldown_until["alpha"] == expected_until
    assert start(client, new_call(3), 2.5).provider == "beta"


def test_transient_retry_honors_another_calls_cooldown_without_spending_budget() -> None:
    client = make_client()
    first_call, second_call = new_call(1), new_call(2)
    first, second = start(client, first_call), start(client, second_call)
    fail(client, first_call, first, 0.1, retry_after=10.0)
    before = client.budget.tokens

    action = fail(client, second_call, second, 0.2, "api_error", None)

    assert isinstance(action, Send) and action.provider == "beta"
    assert action.delay_s == 0.0
    assert client.budget.tokens == before


def test_transient_retry_can_send_after_shared_cooldown_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client()
    call = new_call()
    first = start(client, call)
    client.cooldown_until["alpha"] = 0.5
    monkeypatch.setattr(client.backoff, "delay", lambda *args, **kwargs: 1.0)

    action = fail(client, call, first, 0.2, "api_error", None)

    assert isinstance(action, Send) and action.provider == "alpha"
    assert 0.2 + action.delay_s >= client.cooldown_until["alpha"]
    assert client.budget.tokens == 1.0


@pytest.mark.parametrize("tokens", [0.0, 1.0, 2.0])
def test_exhausted_ladder_rate_limit_retries_are_bounded_by_budget(tokens: float) -> None:
    client = make_client(("alpha",), tokens=tokens)
    call = new_call()
    action: Send | GiveUp = start(client, call)
    now = 0.0
    attempts = 0

    while isinstance(action, Send) and attempts < 10:
        now += action.delay_s + 0.01
        attempts += 1
        action = fail(client, call, action, now)

    assert isinstance(action, GiveUp)
    assert attempts == 1 + int(tokens)
    assert client.budget.tokens == 0.0


def test_waiting_for_an_untried_provider_does_not_charge_retry_budget() -> None:
    client = make_client(tokens=0.0)
    call = new_call()
    first = start(client, call)
    client.cooldown_until["beta"] = 0.6

    action = fail(client, call, first, 0.1)

    # Alpha becomes eligible first, but cannot be retried with an empty budget.
    # Beta has never been tried for this call and may receive its first attempt.
    assert isinstance(action, Send) and action.provider == "beta"
    assert action.delay_s == pytest.approx(0.5)
    assert client.budget.tokens == 0.0


def test_wait_candidates_continue_when_first_half_open_provider_has_no_probe_slot() -> None:
    client = make_client(tokens=0.0, min_calls=1)
    breaker = client.breakers["alpha"]
    permit = breaker.allow(-20.0)
    assert permit is not None
    breaker.on_failure(permit, -20.0)
    held_probe = breaker.allow(0.0)
    assert held_probe is not None and held_probe.probe
    client.cooldown_until.update(alpha=1.0, beta=2.0)

    action = start(client, new_call())

    assert action.provider == "beta" and action.delay_s == 2.0
    assert breaker.probes_in_flight == 1
    assert client.budget.tokens == 0.0


def test_a_failure_that_opens_the_breaker_does_not_charge_a_declined_retry() -> None:
    client = make_client(min_calls=1)
    call = new_call()
    first = start(client, call)
    before = client.budget.tokens

    action = fail(client, call, first, 0.1, "api_error", None)

    assert client.breakers["alpha"].state is BreakerState.OPEN
    assert isinstance(action, Send) and action.provider == "beta"
    assert client.budget.tokens == before


def test_attempts_that_cannot_fit_deadline_do_not_charge_retry_budget() -> None:
    client = make_client()
    call = new_call()
    first = start(client, call)
    before = client.budget.tokens

    action = fail(client, call, first, 29.9, "api_error", None)

    assert isinstance(action, GiveUp) and action.reason == "deadline"
    assert client.budget.tokens == before


def test_budget_refusal_releases_a_reserved_half_open_probe() -> None:
    client = make_client(("alpha",), tokens=0.0, min_calls=1)
    call = new_call(1)
    first = start(client, call)
    fail(client, call, first, 0.1, "api_error", None)
    probe_call = new_call(2, deadline=50.0)
    probe = start(client, probe_call, 20.0)
    assert probe.tag.probe

    action = fail(client, probe_call, probe, 20.1, retry_after=1.0)

    breaker = client.breakers["alpha"]
    assert isinstance(action, GiveUp)
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.probes_in_flight == 0
    assert breaker.allow(20.2) is not None
