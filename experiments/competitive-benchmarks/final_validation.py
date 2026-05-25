#!/usr/bin/env python3
"""Final validation at 1000 simulations."""

import sys
from pathlib import Path

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


def validate_strategy(strategy_path: Path, n_sims: int = 1000):
    """Final validation with high simulation count."""
    strategy = load_strategy(strategy_path)
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

    print(f"\n{'='*60}")
    print(f"FINAL VALIDATION: {name}")
    print(f"Running {n_sims} simulations...")
    print(f"{'='*60}\n")

    result = runner.run_match(strategy, baseline, store_results=False)

    our_edge = float(result.total_edge_a / n_sims)
    norm_edge = float(result.total_edge_b / n_sims)
    margin = our_edge - norm_edge
    win_rate = 100 * result.wins_a / n_sims
    loss_rate = 100 * result.wins_b / n_sims
    tie_rate = 100 * (n_sims - result.wins_a - result.wins_b) / n_sims

    print(f"RESULTS:")
    print(f"  Strategy Edge:    {our_edge:>8.2f}")
    print(f"  Normalizer Edge:  {norm_edge:>8.2f}")
    print(f"  ─────────────────────────")
    print(f"  MARGIN:           {margin:>+8.2f}")
    print(f"")
    print(f"  Wins:   {result.wins_a:>4}/{n_sims} ({win_rate:.1f}%)")
    print(f"  Losses: {result.wins_b:>4}/{n_sims} ({loss_rate:.1f}%)")
    print(f"  Ties:   {n_sims - result.wins_a - result.wins_b:>4}/{n_sims} ({tie_rate:.1f}%)")
    print(f"\n{'='*60}")

    if margin > 0:
        print(f"✓ {name} BEATS normalizer by {margin:.2f} edge per simulation")
    else:
        print(f"✗ {name} LOSES to normalizer by {abs(margin):.2f} edge per simulation")
    print(f"{'='*60}\n")

    return name, our_edge, norm_edge, margin, result.wins_a, n_sims


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    validate_strategy(PROJECT_ROOT / "contracts/src/WinningV4Strategy.sol", n_sims=1000)
