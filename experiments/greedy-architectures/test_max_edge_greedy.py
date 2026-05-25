#!/usr/bin/env python3
"""Maximize edge through extreme arb extraction - ignore win rate.

Key insight: Edge = retail_profit - arb_loss
To maximize edge, we need to either:
1. Extract max from arbs (very high arb fees)
2. Or capture more retail at decent fees

This test pushes extreme arb fees to find the edge maximum.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parallel_harness import ParallelHarness, StrategySpec

# Three-tier with extreme arb fees
EXTREME_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant RETAIL_FEE = {retail} * BPS;
    uint256 constant MEDIUM_FEE = {medium} * BPS;
    uint256 constant ARB_FEE = {arb} * BPS;

    uint256 constant SMALL_THRESH = WAD / {small};   // trades < this = retail
    uint256 constant LARGE_THRESH = WAD / {large};   // trades > this = arb

    function afterInitialize(uint256, uint256)
        external override returns (uint256, uint256)
    {{
        return (RETAIL_FEE, RETAIL_FEE);
    }}

    function afterSwap(TradeInfo calldata trade)
        external override returns (uint256, uint256)
    {{
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        uint256 fee;

        if (tradeRatio < SMALL_THRESH) {{
            fee = RETAIL_FEE;
        }} else if (tradeRatio > LARGE_THRESH) {{
            fee = ARB_FEE;
        }} else {{
            fee = MEDIUM_FEE;
        }}

        fee = clampFee(fee);
        return (fee, fee);
    }}

    function getName() external pure override returns (string memory) {{
        return "ExtremeGreedy";
    }}
}}
'''


def main():
    print("=" * 70)
    print("EXTREME EDGE EXTRACTION - Ignore Win Rate")
    print("Focus: Maximum edge through extreme arb fees")
    print("=" * 70)

    harness = ParallelHarness(
        n_workers=4,
        rust_workers_per=2,
        n_sims=500,
    )

    specs = []

    # Push extreme arb fees - from 500 to 1000 bps (max)
    for retail in [25, 28, 30]:
        for medium in [50, 100, 150]:
            for arb in [500, 600, 700, 800, 900, 1000]:
                for small in [150, 200, 250]:
                    for large in [25, 30, 40, 50]:
                        specs.append(StrategySpec(
                            name=f"EX_r{retail}_m{medium}_a{arb}_s{small}_l{large}",
                            template=EXTREME_TEMPLATE,
                            params={
                                "retail": retail,
                                "medium": medium,
                                "arb": arb,
                                "small": small,
                                "large": large,
                            }
                        ))

    print(f"\nTotal variants to test: {len(specs)}")

    results = harness.run_sweep(specs)

    # Analysis - sort by edge only
    valid = [r for r in results if r.error is None]
    if valid:
        by_edge = sorted(valid, key=lambda r: r.edge, reverse=True)

        print("\n" + "=" * 70)
        print("TOP 30 BY EDGE (ignoring win rate):")
        print("=" * 70)
        for r in by_edge[:30]:
            print(f"edge={r.edge:7.2f} | wins={r.wins:3d}/{r.total} ({r.win_rate*100:5.1f}%) | {r.spec.params}")

        print("\n" + "=" * 70)
        print("ABSOLUTE BEST EDGE:")
        print("=" * 70)
        best = by_edge[0]
        print(f"edge={best.edge:.2f}")
        print(f"wins={best.wins}/{best.total} ({best.win_rate*100:.1f}%)")
        print(f"params={best.spec.params}")


if __name__ == "__main__":
    main()
