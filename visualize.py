#!/usr/bin/env python3
"""
Visualization tool for AMM simulation.
Helps understand price dynamics, fee behavior, and edge accumulation.
"""

import argparse
import sys
from pathlib import Path
from decimal import Decimal

import matplotlib.pyplot as plt
import numpy as np

from amm_competition.competition.match import MatchRunner, HyperparameterVariance, SimulationConfig
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import load_vanilla_strategy
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator


def load_strategy(strategy_path: Path) -> EVMStrategyAdapter:
    """Load and compile a strategy from a .sol file."""
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


def run_single_simulation(strategy: EVMStrategyAdapter, seed: int = 42):
    """Run a single simulation and return detailed results."""
    baseline = load_vanilla_strategy()

    # Use midpoint of variance ranges for consistent visualization
    config = SimulationConfig(
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
        seed=seed,
    )

    # No variance for single sim
    variance = HyperparameterVariance(
        retail_mean_size_min=config.retail_mean_size,
        retail_mean_size_max=config.retail_mean_size,
        vary_retail_mean_size=False,
        retail_arrival_rate_min=config.retail_arrival_rate,
        retail_arrival_rate_max=config.retail_arrival_rate,
        vary_retail_arrival_rate=False,
        gbm_sigma_min=config.gbm_sigma,
        gbm_sigma_max=config.gbm_sigma,
        vary_gbm_sigma=False,
    )

    runner = MatchRunner(
        n_simulations=1,
        config=config,
        n_workers=1,
        variance=variance,
    )

    result = runner.run_match(strategy, baseline, store_results=True)
    return result.simulation_results[0] if result.simulation_results else None


def plot_simulation(sim_result, strategy_name: str, output_path: str = None):
    """Create visualization plots for a simulation."""
    steps = sim_result.steps
    n_steps = len(steps)

    # Extract data
    timestamps = [s.timestamp for s in steps]
    fair_prices = [s.fair_price for s in steps]

    submission_spots = [s.spot_prices.get('submission', 0) for s in steps]
    normalizer_spots = [s.spot_prices.get('normalizer', 0) for s in steps]

    submission_pnls = [s.pnls.get('submission', 0) for s in steps]
    normalizer_pnls = [s.pnls.get('normalizer', 0) for s in steps]

    submission_bid_fees = [s.fees.get('submission', (0, 0))[0] * 10000 for s in steps]  # Convert to bps
    submission_ask_fees = [s.fees.get('submission', (0, 0))[1] * 10000 for s in steps]
    normalizer_fees = [s.fees.get('normalizer', (0, 0))[0] * 10000 for s in steps]

    # Create figure with subplots
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    fig.suptitle(f'AMM Simulation Analysis: {strategy_name}', fontsize=14, fontweight='bold')

    # Subsample for cleaner plots (every 100th point for 10k steps)
    step = max(1, n_steps // 1000)
    idx = range(0, n_steps, step)

    # Plot 1: Price Evolution
    ax1 = axes[0]
    ax1.plot([timestamps[i] for i in idx], [fair_prices[i] for i in idx],
             'b-', label='Fair Price', linewidth=1, alpha=0.8)
    ax1.plot([timestamps[i] for i in idx], [submission_spots[i] for i in idx],
             'g--', label=f'{strategy_name} Spot', linewidth=0.8, alpha=0.7)
    ax1.plot([timestamps[i] for i in idx], [normalizer_spots[i] for i in idx],
             'r--', label='Normalizer Spot', linewidth=0.8, alpha=0.7)
    ax1.set_ylabel('Price (Y per X)')
    ax1.legend(loc='upper right')
    ax1.set_title('Price Evolution')
    ax1.grid(True, alpha=0.3)

    # Plot 2: Fee Dynamics
    ax2 = axes[1]
    ax2.plot([timestamps[i] for i in idx], [submission_bid_fees[i] for i in idx],
             'g-', label=f'{strategy_name} Bid Fee', linewidth=1)
    ax2.plot([timestamps[i] for i in idx], [submission_ask_fees[i] for i in idx],
             'b-', label=f'{strategy_name} Ask Fee', linewidth=1)
    ax2.axhline(y=30, color='r', linestyle='--', label='Normalizer (30 bps)', linewidth=1)
    ax2.set_ylabel('Fee (bps)')
    ax2.legend(loc='upper right')
    ax2.set_title('Fee Dynamics')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0, 120)

    # Plot 3: Cumulative PnL
    ax3 = axes[2]
    ax3.plot([timestamps[i] for i in idx], [submission_pnls[i] for i in idx],
             'g-', label=f'{strategy_name}', linewidth=1.5)
    ax3.plot([timestamps[i] for i in idx], [normalizer_pnls[i] for i in idx],
             'r-', label='Normalizer', linewidth=1.5)
    ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax3.set_ylabel('Cumulative PnL')
    ax3.legend(loc='upper left')
    ax3.set_title('Cumulative PnL Over Time')
    ax3.grid(True, alpha=0.3)

    # Plot 4: Price Deviation (Spot - Fair)
    ax4 = axes[3]
    submission_deviation = [(submission_spots[i] - fair_prices[i]) / fair_prices[i] * 100 for i in idx]
    normalizer_deviation = [(normalizer_spots[i] - fair_prices[i]) / fair_prices[i] * 100 for i in idx]
    ax4.plot([timestamps[i] for i in idx], submission_deviation,
             'g-', label=f'{strategy_name}', linewidth=0.8, alpha=0.7)
    ax4.plot([timestamps[i] for i in idx], normalizer_deviation,
             'r-', label='Normalizer', linewidth=0.8, alpha=0.7)
    ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax4.set_xlabel('Step')
    ax4.set_ylabel('Deviation from Fair (%)')
    ax4.legend(loc='upper right')
    ax4.set_title('Spot Price Deviation from Fair Price')
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Saved plot to {output_path}")
    else:
        plt.show()

    # Print summary statistics
    print("\n" + "="*60)
    print("SIMULATION SUMMARY")
    print("="*60)
    print(f"Strategy: {strategy_name}")
    print(f"Steps: {n_steps}")
    print(f"\nFinal Edge:")
    print(f"  {strategy_name}: {float(sim_result.edges.get('submission', 0)):.2f}")
    print(f"  Normalizer: {float(sim_result.edges.get('normalizer', 0)):.2f}")
    print(f"\nVolume (Y):")
    print(f"  {strategy_name} Arb: {sim_result.arb_volume_y.get('submission', 0):.2f}")
    print(f"  {strategy_name} Retail: {sim_result.retail_volume_y.get('submission', 0):.2f}")
    print(f"  Normalizer Arb: {sim_result.arb_volume_y.get('normalizer', 0):.2f}")
    print(f"  Normalizer Retail: {sim_result.retail_volume_y.get('normalizer', 0):.2f}")
    print(f"\nAverage Fees (bps):")
    sub_avg = sim_result.average_fees.get('submission', (0, 0))
    norm_avg = sim_result.average_fees.get('normalizer', (0, 0))
    print(f"  {strategy_name}: Bid={sub_avg[0]*10000:.1f}, Ask={sub_avg[1]*10000:.1f}")
    print(f"  Normalizer: Bid={norm_avg[0]*10000:.1f}, Ask={norm_avg[1]*10000:.1f}")
    print("="*60)

    return fig


def main():
    parser = argparse.ArgumentParser(description="Visualize AMM simulation")
    parser.add_argument("strategy", help="Path to strategy .sol file")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for simulation")
    parser.add_argument("--output", "-o", help="Output file path (e.g., plot.png)")
    args = parser.parse_args()

    strategy_path = Path(args.strategy)
    if not strategy_path.exists():
        print(f"Error: Strategy file not found: {strategy_path}")
        return 1

    print(f"Loading strategy from {strategy_path}...")
    strategy = load_strategy(strategy_path)
    strategy_name = strategy.get_name()
    print(f"Strategy: {strategy_name}")

    print(f"\nRunning simulation (seed={args.seed})...")
    sim_result = run_single_simulation(strategy, seed=args.seed)

    if sim_result is None:
        print("Error: Simulation returned no results")
        return 1

    print("Generating visualization...")
    plot_simulation(sim_result, strategy_name, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
