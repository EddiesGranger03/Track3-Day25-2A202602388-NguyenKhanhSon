"""Regression coverage for SLO decision boundaries and reporting precision."""

import pytest

from gameday_lab.slo.alerting import (
    DEFAULT_RULES,
    AlertEvent,
    BurnRateAlerter,
    error_budget_report,
)


@pytest.mark.parametrize("rule,bad_per_min", tuple(zip(DEFAULT_RULES, (72, 30, 5))))
def test_exact_default_burn_threshold_fires(rule, bad_per_min):
    total = [1000] * rule.long_min
    bad = [bad_per_min] * rule.long_min

    assert BurnRateAlerter(rules=(rule,)).evaluate(total, bad) == [
        AlertEvent(rule.name, rule.severity, 0, rule.long_min)
    ]


@pytest.mark.parametrize("rule,bad_per_min", tuple(zip(DEFAULT_RULES, (72, 30, 5))))
@pytest.mark.parametrize("scale", (1, 10**12))
def test_burn_below_default_threshold_does_not_fire(rule, bad_per_min, scale):
    # Even a one-request deficit must stay below the threshold at high volume.
    total = [1000 * scale] * rule.long_min
    bad = [bad_per_min * scale - 1] * rule.long_min

    assert BurnRateAlerter(rules=(rule,)).evaluate(total, bad) == []


def test_zero_traffic_does_not_alert():
    assert BurnRateAlerter().evaluate([0] * 60, [0] * 60) == []


def test_small_positive_budget_is_not_rounded_to_zero_before_division():
    report = error_budget_report([1], [1])

    assert report["allowed_bad"] == 0.0  # Presentation still rounds to one decimal.
    assert report["budget_consumed"] == 200.0
    assert report["budget_remaining"] == -199.0
    assert report["freeze_releases"] is True


@pytest.mark.parametrize("requests,bad", ((10001, 50), (1000001, 5000), (10**18 + 1, 5 * 10**15)))
def test_positive_unrounded_remaining_budget_does_not_freeze(requests, bad):
    assert error_budget_report([requests], [bad])["freeze_releases"] is False


@pytest.mark.parametrize("requests,bad", ((10000, 50), (10**18, 5 * 10**15)))
def test_exactly_exhausted_budget_freezes(requests, bad):
    report = error_budget_report([requests], [bad])

    assert report["budget_consumed"] == 1.0
    assert report["budget_remaining"] == 0.0
    assert report["freeze_releases"] is True


@pytest.mark.parametrize("total,bad", (([], []), ([0, 0], [0, 0])))
def test_zero_traffic_keeps_budget_available(total, bad):
    assert error_budget_report(total, bad) == {
        "requests": 0,
        "allowed_bad": 0.0,
        "bad": 0,
        "availability": 1.0,
        "budget_consumed": 0.0,
        "budget_remaining": 1.0,
        "freeze_releases": False,
    }
