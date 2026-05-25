#!/usr/bin/env python3
"""Find optimal fee when COMPETING against normalizer for order flow."""

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


TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant FEE = {fee} * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        return (FEE, FEE);
    }}

    function afterSwap(TradeInfo calldata) external override returns (uint256, uint256) {{
        return (FEE, FEE);
    }}

    function getName() external pure override returns (string memory) {{
        return "Static{fee}bps";
    }}
}}
'''


def test_fee(fee_bps: int, n_sims: int = 200):
    """Test a static fee level competing against normalizer."""
    source = TEMPLATE.format(fee=fee_bps)

    validator = SolidityValidator()
    validation = validator.validate(source)
    if not validation.valid:
        return None, None

    compiler = SolidityCompiler()
    compilation = compiler.compile(source)
    if not compilation.success:
        return None, None

    strategy = EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)
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

    # Compete against normalizer (30 bps)
    result = runner.run_match(strategy, baseline, store_results=False)
    our_edge = float(result.total_edge_a / n_sims)
    norm_edge = float(result.total_edge_b / n_sims)

    return our_edge, norm_edge


def main():
    n_sims = 200
    print(f"Finding MAX ABSOLUTE EDGE when competing vs normalizer ({n_sims} sims each)")
    print("=" * 70)
    print(f"{'Fee':>6} | {'Our Edge':>10} | {'Norm Edge':>10} | {'Winner':>8}")
    print("-" * 70)

    # Test range of fees - competing against 30 bps normalizer
    fees = [15, 18, 20, 22, 24, 25, 26, 27, 28, 29, 30, 32, 35, 40, 50, 60, 80, 100]

    results = []
    for fee in fees:
        our_edge, norm_edge = test_fee(fee, n_sims)
        if our_edge is not None:
            winner = "US" if our_edge > norm_edge else "NORM"
            results.append((fee, our_edge, norm_edge))
            print(f"{fee:>5}bp | {our_edge:>10.2f} | {norm_edge:>10.2f} | {winner:>8}")

    print("\n" + "=" * 70)
    print("SORTED BY OUR ABSOLUTE EDGE (highest first):")
    print("=" * 70)
    for fee, our, norm in sorted(results, key=lambda x: -x[1])[:10]:
        winner = "WIN" if our > norm else "LOSE"
        print(f"{fee:>5}bp: our={our:>7.2f}, norm={norm:>7.2f} [{winner}]")

    best_fee, best_our, best_norm = max(results, key=lambda x: x[1])
    print(f"\nBEST ABSOLUTE EDGE: {best_fee} bps with edge {best_our:.2f}")
    if best_our > best_norm:
        print(f"  -> Also beats normalizer by {best_our - best_norm:.2f}")
    else:
        print(f"  -> But LOSES to normalizer by {best_norm - best_our:.2f}")


if __name__ == "__main__":
    main()
