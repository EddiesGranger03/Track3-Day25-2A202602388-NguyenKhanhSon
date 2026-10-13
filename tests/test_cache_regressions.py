"""Cache tape checks on seeds that previously exceeded the stale-answer limit."""

import pytest

from gameday_lab.factory import build_client
from gameday_lab.sim.config import load_config
from gameday_lab.sim.engine import evaluate_checks, run_scenario


@pytest.mark.parametrize("seed", [3, 4, 58, 85])
def test_cache_tape_remains_safe_across_seeds(seed: int) -> None:
    cfg = load_config("configs/gameday.yaml", "configs/scenarios_cache.yaml")
    scenario = "C1_faq_outage"
    metrics = run_scenario(cfg, scenario, build_client("cached", cfg), seed).metrics()
    checks = evaluate_checks(metrics, cfg.scenarios[scenario].checks)
    assert all(checks.values()), {
        "seed": seed,
        "failed": [name for name, passed in checks.items() if not passed],
        "outdated_answers": metrics["outdated_answers"],
    }
