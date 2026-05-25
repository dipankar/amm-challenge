#!/usr/bin/env python3
"""
Find the optimal fee that maximizes wins against normalizer.
"""

import subprocess
import re
from pathlib import Path

TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant FEE = {fee} * BPS;

    function afterInitialize(uint256, uint256) external pure override returns (uint256, uint256) {{
        return (FEE, FEE);
    }}

    function afterSwap(TradeInfo calldata) external pure override returns (uint256, uint256) {{
        return (FEE, FEE);
    }}

    function getName() external pure override returns (string memory) {{
        return "Static{fee}bps";
    }}
}}
'''

# Import visualization to get detailed results
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from visualize import load_strategy, run_single_simulation

def test_fee(fee: int, n_seeds: int = 5):
    """Test a fee level across multiple seeds and return average edges."""
    strategy_path = Path(__file__).parent.parent.parent / "contracts/src/TestFees.sol"
    strategy_path.write_text(TEMPLATE.format(fee=fee))

    our_edges = []
    norm_edges = []

    for seed in range(n_seeds):
        try:
            strategy = load_strategy(strategy_path)
            result = run_single_simulation(strategy, seed=seed)
            if result:
                our_edges.append(float(result.edges.get('submission', 0)))
                norm_edges.append(float(result.edges.get('normalizer', 0)))
        except Exception as e:
            print(f"Error at fee={fee}, seed={seed}: {e}")

    if our_edges:
        avg_ours = sum(our_edges) / len(our_edges)
        avg_norm = sum(norm_edges) / len(norm_edges)
        margin = avg_ours - avg_norm
        wins = sum(1 for o, n in zip(our_edges, norm_edges) if o > n)
        return avg_ours, avg_norm, margin, wins, len(our_edges)
    return 0, 0, 0, 0, 0

def main():
    fees_to_test = [15, 18, 20, 22, 24, 25, 26, 27, 28, 29, 30, 32, 35, 40]
    results = []

    print("Finding optimal fee to beat normalizer...")
    print("-" * 70)
    print(f"{'Fee':>5} | {'Our Edge':>10} | {'Norm Edge':>10} | {'Margin':>10} | {'Wins':>5}")
    print("-" * 70)

    for fee in fees_to_test:
        our_edge, norm_edge, margin, wins, total = test_fee(fee, n_seeds=10)
        results.append((fee, our_edge, norm_edge, margin, wins, total))
        print(f"{fee:>5} | {our_edge:>10.2f} | {norm_edge:>10.2f} | {margin:>+10.2f} | {wins:>2}/{total}")

    print("-" * 70)

    # Find best by margin
    best = max(results, key=lambda x: x[3])
    print(f"\nBest fee by margin: {best[0]} bps")
    print(f"  Our edge: {best[1]:.2f}")
    print(f"  Norm edge: {best[2]:.2f}")
    print(f"  Margin: {best[3]:+.2f}")
    print(f"  Wins: {best[4]}/{best[5]}")

    # Find best by win rate
    best_wins = max(results, key=lambda x: x[4]/max(x[5], 1))
    print(f"\nBest fee by win rate: {best_wins[0]} bps")
    print(f"  Win rate: {best_wins[4]}/{best_wins[5]}")

if __name__ == "__main__":
    main()
