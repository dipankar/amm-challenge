#!/usr/bin/env python3
"""Test the GreedyEdgeStrategy with parameter grid search.

Architecture: Two-tier fees - competitive retail + extreme arb extraction.
Goal: Capture retail at low fees, extract maximum from large/arb trades.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parallel_harness import ParallelHarness, StrategySpec

# Two-tier greedy template
GREEDY_EDGE_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant RETAIL_FEE = {retail} * BPS;
    uint256 constant ARB_FEE = {arb} * BPS;
    uint256 constant SMALL_TRADE = WAD / {small};   // <1/small = retail
    uint256 constant LARGE_TRADE = WAD / {large};   // >1/large = arb

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

        if (tradeRatio < SMALL_TRADE) {{
            fee = RETAIL_FEE;
        }} else if (tradeRatio > LARGE_TRADE) {{
            fee = ARB_FEE;
        }} else {{
            uint256 range = LARGE_TRADE - SMALL_TRADE;
            uint256 position = tradeRatio - SMALL_TRADE;
            uint256 feeRange = ARB_FEE - RETAIL_FEE;
            fee = RETAIL_FEE + wmul(wdiv(position, range), feeRange);
        }}

        fee = clampFee(fee);
        return (fee, fee);
    }}

    function getName() external pure override returns (string memory) {{
        return "GreedyEdge";
    }}
}}
'''


def main():
    print("=" * 70)
    print("GREEDY EDGE STRATEGY - Two-Tier Architecture")
    print("Architecture: Competitive retail + extreme arb extraction")
    print("=" * 70)

    harness = ParallelHarness(
        n_workers=4,
        rust_workers_per=2,
        n_sims=500,
    )

    specs = []

    # Grid search parameters
    # retail: 25-32 bps (compete with normalizer at 30)
    # arb: 200-600 bps (extract maximum from arbs)
    # small: 100-200 (threshold for retail, WAD/small)
    # large: 30-60 (threshold for arb, WAD/large)

    for retail in [25, 27, 28, 29, 30, 32]:
        for arb in [200, 300, 400, 500, 600]:
            for small in [100, 125, 150, 175, 200]:
                for large in [30, 40, 50, 60]:
                    specs.append(StrategySpec(
                        name=f"GE_r{retail}_a{arb}_s{small}_l{large}",
                        template=GREEDY_EDGE_TEMPLATE,
                        params={
                            "retail": retail,
                            "arb": arb,
                            "small": small,
                            "large": large,
                        }
                    ))

    print(f"\nTotal variants to test: {len(specs)}")

    results = harness.run_sweep(specs)

    # Analysis
    valid = [r for r in results if r.error is None]
    if valid:
        # Sort by edge
        by_edge = sorted(valid, key=lambda r: r.edge, reverse=True)

        print("\n" + "=" * 70)
        print("TOP 20 BY EDGE:")
        print("=" * 70)
        for r in by_edge[:20]:
            print(f"edge={r.edge:7.2f} | wins={r.wins:3d}/{r.total} ({r.win_rate*100:5.1f}%) | {r.spec.params}")

        # Best with 100% wins
        perfect = [r for r in valid if r.win_rate == 1.0]
        if perfect:
            print("\n" + "=" * 70)
            print("BEST WITH 100% WIN RATE:")
            print("=" * 70)
            best = max(perfect, key=lambda r: r.edge)
            print(f"edge={best.edge:.2f} | wins={best.wins}/{best.total} | {best.spec.params}")

        # Best overall
        print("\n" + "=" * 70)
        print("BEST OVERALL:")
        print("=" * 70)
        best = by_edge[0]
        print(f"edge={best.edge:.2f} | wins={best.wins}/{best.total} ({best.win_rate*100:.1f}%) | {best.spec.params}")


if __name__ == "__main__":
    main()
