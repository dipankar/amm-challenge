#!/usr/bin/env python3
"""Analyze what edge the normalizer actually gets."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amm_competition.competition.match import MatchRunner
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE, resolve_n_workers
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import load_vanilla_strategy
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator
import amm_sim_rs


def test_normalizer_edge(n_sims=500):
    """See what edge the normalizer gets when running alone (no competition)."""
    baseline = load_vanilla_strategy()

    config = amm_sim_rs.SimulationConfig(
        n_steps=BASELINE_SETTINGS.n_steps,
        initial_price=BASELINE_SETTINGS.initial_price,
        initial_x=BASELINE_SETTINGS.initial_x,
        initial_y=BASELINE_SETTINGS.initial_y,
        gbm_mu=BASELINE_SETTINGS.gbm_mu,
        gbm_sigma=(BASELINE_VARIANCE.gbm_sigma_min + BASELINE_VARIANCE.gbm_sigma_max) / 2,
        gbm_dt=BASELINE_SETTINGS.gbm_dt,
        retail_arrival_rate=(BASELINE_VARIANCE.retail_arrival_rate_min + BASELINE_VARIANCE.retail_arrival_rate_max) / 2,
        retail_mean_size=(BASELINE_VARIANCE.retail_mean_size_min + BASELINE_VARIANCE.retail_mean_size_max) / 2,
        retail_size_sigma=BASELINE_SETTINGS.retail_size_sigma,
        retail_buy_prob=BASELINE_SETTINGS.retail_buy_prob,
        seed=None,
    )

    runner = MatchRunner(
        n_simulations=n_sims,
        config=config,
        n_workers=resolve_n_workers(),
        variance=BASELINE_VARIANCE,
    )

    # Run normalizer vs normalizer (each gets 50% of flow)
    result = runner.run_match(baseline, baseline, store_results=False)
    norm_edge = float(result.total_edge_a / n_sims)
    print(f"Normalizer vs Normalizer (50/50 split): {norm_edge:.2f} edge each")

    return norm_edge


def test_strategy_vs_normalizer(strategy_path: Path, n_sims=500):
    """Test a strategy against normalizer and see both edges."""
    source = strategy_path.read_text()
    validator = SolidityValidator()
    validation = validator.validate(source)
    if not validation.valid:
        raise ValueError(f"Validation failed: {validation.errors}")

    compiler = SolidityCompiler()
    compilation = compiler.compile(source)
    if not compilation.success:
        raise ValueError(f"Compilation failed: {compilation.errors}")

    strategy = EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)
    baseline = load_vanilla_strategy()
    name = strategy.get_name()

    config = amm_sim_rs.SimulationConfig(
        n_steps=BASELINE_SETTINGS.n_steps,
        initial_price=BASELINE_SETTINGS.initial_price,
        initial_x=BASELINE_SETTINGS.initial_x,
        initial_y=BASELINE_SETTINGS.initial_y,
        gbm_mu=BASELINE_SETTINGS.gbm_mu,
        gbm_sigma=(BASELINE_VARIANCE.gbm_sigma_min + BASELINE_VARIANCE.gbm_sigma_max) / 2,
        gbm_dt=BASELINE_SETTINGS.gbm_dt,
        retail_arrival_rate=(BASELINE_VARIANCE.retail_arrival_rate_min + BASELINE_VARIANCE.retail_arrival_rate_max) / 2,
        retail_mean_size=(BASELINE_VARIANCE.retail_mean_size_min + BASELINE_VARIANCE.retail_mean_size_max) / 2,
        retail_size_sigma=BASELINE_SETTINGS.retail_size_sigma,
        retail_buy_prob=BASELINE_SETTINGS.retail_buy_prob,
        seed=None,
    )

    runner = MatchRunner(
        n_simulations=n_sims,
        config=config,
        n_workers=resolve_n_workers(),
        variance=BASELINE_VARIANCE,
    )

    result = runner.run_match(strategy, baseline, store_results=False)
    our_edge = float(result.total_edge_a / n_sims)
    norm_edge = float(result.total_edge_b / n_sims)

    print(f"\n{name} vs Normalizer:")
    print(f"  Our Edge:       {our_edge:>8.2f}")
    print(f"  Normalizer:     {norm_edge:>8.2f}")
    print(f"  Gap to close:   {norm_edge - our_edge:>8.2f}")

    return our_edge, norm_edge


if __name__ == "__main__":
    n_sims = 500
    print(f"Analyzing normalizer edge ({n_sims} sims)")
    print("=" * 60)

    # First see what normalizer gets in isolation
    norm_solo = test_normalizer_edge(n_sims)

    # Then compare our best strategies
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    strategies = [
        PROJECT_ROOT / "contracts/src/MaxEdgeFinalStrategy.sol",
        PROJECT_ROOT / "contracts/src/WinningV4Strategy.sol",
    ]

    for s in strategies:
        if s.exists():
            test_strategy_vs_normalizer(s, n_sims)
