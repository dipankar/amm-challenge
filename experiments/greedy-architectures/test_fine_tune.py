#!/usr/bin/env python3
"""Fine-tune around the best UltraGreedy parameters found.

Best from initial search: high=200, retail=30, thresh=100 -> edge=391.37, 100% wins
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parallel_harness import ParallelHarness, StrategySpec

# Best architecture: UltraGreedy
ULTRA_GREEDY_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant HIGH_FEE = {high} * BPS;
    uint256 constant RETAIL_FEE = {retail} * BPS;
    uint256 constant SMALL_THRESH = {thresh};

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        return (HIGH_FEE, HIGH_FEE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        if (tradeRatio < WAD / SMALL_THRESH) {{
            return (clampFee(RETAIL_FEE), clampFee(RETAIL_FEE));
        }}

        return (clampFee(HIGH_FEE), clampFee(HIGH_FEE));
    }}

    function getName() external pure override returns (string memory) {{
        return "UltraGreedy";
    }}
}}
'''

def main():
    print("=" * 70)
    print("FINE-TUNING UltraGreedy Strategy")
    print("Base: high=200, retail=30, thresh=100 -> edge=391.37")
    print("=" * 70)

    harness = ParallelHarness(
        n_workers=4,
        rust_workers_per=2,
        n_sims=1000,  # More sims for accuracy
    )

    specs = []

    # Fine-tune around best parameters
    # retail: 27-32 bps (around normalizer's 30)
    # high: 150-300 bps
    # thresh: 60-140

    for retail in [27, 28, 29, 30, 31, 32]:
        for high in [150, 175, 200, 225, 250, 300]:
            for thresh in [60, 80, 100, 120, 140]:
                specs.append(StrategySpec(
                    name=f"h{high}_r{retail}_t{thresh}",
                    template=ULTRA_GREEDY_TEMPLATE,
                    params={"high": high, "retail": retail, "thresh": thresh}
                ))

    print(f"\nTotal variants to test: {len(specs)}")

    results = harness.run_sweep(specs)

    # Find best with 100% wins
    perfect = [r for r in results if r.error is None and r.win_rate == 1.0]
    if perfect:
        print("\n" + "=" * 70)
        print("BEST WITH 100% WIN RATE:")
        print("=" * 70)
        best_perfect = max(perfect, key=lambda r: r.edge)
        print(f"Edge: {best_perfect.edge:.2f}")
        print(f"Params: {best_perfect.spec.params}")

    # Find best overall (ignoring win rate)
    valid = [r for r in results if r.error is None]
    if valid:
        print("\n" + "=" * 70)
        print("BEST OVERALL (ignoring win rate):")
        print("=" * 70)
        best_overall = max(valid, key=lambda r: r.edge)
        print(f"Edge: {best_overall.edge:.2f}")
        print(f"Wins: {best_overall.wins}/{best_overall.total} ({best_overall.win_rate*100:.1f}%)")
        print(f"Params: {best_overall.spec.params}")


if __name__ == "__main__":
    main()
