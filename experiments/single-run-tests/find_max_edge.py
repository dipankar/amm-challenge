#!/usr/bin/env python3
"""Find optimal fee for MAXIMUM absolute edge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from amm_competition.competition.match import MatchRunner
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE, resolve_n_workers
from amm_competition.evm.adapter import EVMStrategyAdapter
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
    """Test a static fee level and return edge."""
    source = TEMPLATE.format(fee=fee_bps)

    validator = SolidityValidator()
    validation = validator.validate(source)
    if not validation.valid:
        print(f"Validation failed for {fee_bps} bps: {validation.errors}")
        return None

    compiler = SolidityCompiler()
    compilation = compiler.compile(source)
    if not compilation.success:
        print(f"Compilation failed for {fee_bps} bps: {compilation.errors}")
        return None

    strategy = EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)

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

    # Run solo (strategy A only matters)
    result = runner.run_match(strategy, strategy, store_results=False)
    edge = float(result.total_edge_a / n_sims)

    return edge


def main():
    n_sims = 200
    print(f"Finding optimal fee for MAXIMUM EDGE ({n_sims} sims each)")
    print("=" * 50)

    # Test range of fees
    fees = [30, 40, 50, 60, 70, 75, 78, 80, 82, 85, 90, 95, 100]

    results = []
    for fee in fees:
        edge = test_fee(fee, n_sims)
        if edge is not None:
            results.append((fee, edge))
            print(f"{fee:3d} bps: edge = {edge:7.2f}")

    print("\n" + "=" * 50)
    print("SORTED BY EDGE (highest first):")
    print("=" * 50)
    for fee, edge in sorted(results, key=lambda x: -x[1]):
        print(f"{fee:3d} bps: {edge:7.2f}")

    best_fee, best_edge = max(results, key=lambda x: x[1])
    print(f"\nBEST: {best_fee} bps with edge {best_edge:.2f}")


if __name__ == "__main__":
    main()
