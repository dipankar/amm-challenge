#!/usr/bin/env python3
"""Compare strategies by their margin against normalizer."""

import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amm_competition.competition.match import MatchRunner, HyperparameterVariance, SimulationConfig
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE, resolve_n_workers
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import load_vanilla_strategy
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator
import amm_sim_rs


def load_strategy(strategy_path: Path) -> EVMStrategyAdapter:
    source_code = strategy_path.read_text()
    validator = SolidityValidator()
    validation = validator.validate(source_code)
    if not validation.valid:
        raise ValueError(f"Validation failed: {validation.errors}")

    compiler = SolidityCompiler()
    compilation = compiler.compile(source_code)
    if not compilation.success:
        raise ValueError(f"Compilation failed: {compilation.errors}")

    return EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)


def test_strategy(strategy_path: Path, n_sims: int = 100):
    """Test a strategy and return detailed comparison with normalizer."""
    strategy = load_strategy(strategy_path)
    baseline = load_vanilla_strategy()
    name = strategy.get_name()

    # Build config with variance
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
    margin = our_edge - norm_edge

    print(f"\n{name}:")
    print(f"  Our Edge:  {our_edge:>8.2f}")
    print(f"  Norm Edge: {norm_edge:>8.2f}")
    print(f"  Margin:    {margin:>+8.2f}")
    print(f"  Wins:      {result.wins_a}/{n_sims} ({100*result.wins_a/n_sims:.0f}%)")
    print(f"  Losses:    {result.wins_b}/{n_sims} ({100*result.wins_b/n_sims:.0f}%)")

    return name, our_edge, norm_edge, margin, result.wins_a, n_sims


def main():
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    strategies = [
        PROJECT_ROOT / "contracts/src/Low25bps.sol",
        PROJECT_ROOT / "contracts/src/WinningV2Strategy.sol",
        PROJECT_ROOT / "contracts/src/WinningV3Strategy.sol",
    ]

    n_sims = 200
    print(f"Testing strategies ({n_sims} simulations each)...")
    print("=" * 60)

    results = []
    for s in strategies:
        result = test_strategy(s, n_sims=n_sims)
        results.append(result)

    print("\n" + "=" * 60)
    print("SUMMARY (sorted by margin)")
    print("=" * 60)
    for name, our, norm, margin, wins, total in sorted(results, key=lambda x: -x[3]):
        print(f"{name:20s}: margin={margin:+7.2f}, wins={wins}/{total} ({100*wins/total:.0f}%)")


if __name__ == "__main__":
    main()
