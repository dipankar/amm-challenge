#!/usr/bin/env python3
"""Push for maximum edge - sacrifice win rate for profit.

Current reference: 423.71 edge at 0.8% wins
Goal: Find higher edge while staying intentionally low-win
"""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parallel_harness import ParallelHarness, StrategySpec

# Ultra greedy - push all fees higher, tighter thresholds
PUSH_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant RETAIL_FEE = {retail} * BPS;
    uint256 constant MEDIUM_FEE = {medium} * BPS;
    uint256 constant ARB_FEE = {arb} * BPS;

    uint256 constant SMALL_THRESH = WAD / {small};
    uint256 constant LARGE_THRESH = WAD / {large};

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
        return "PushEdge";
    }}
}}
'''


def main():
    print("=" * 70)
    print("PUSH FOR MAXIMUM EDGE - Sacrifice Win Rate")
    print("Reference: edge=423.71 @ 0.8% wins")
    print("Goal: Higher edge while remaining low-win")
    print("=" * 70)

    # Current proven reference point from 500-sim validation.
    current_best = {
        "retail": 60,
        "medium": 150,
        "arb": 400,
        "small": 150,
        "large": 40,
    }

    harness = ParallelHarness(
        n_workers=4,
        rust_workers_per=2,
        n_sims=500,
    )

    specs = []

    # Sample around the best-known low-win region instead of broad high-win grids.
    retail_vals = [50, 55, 58, 60, 62, 65, 68, 70]
    medium_vals = [120, 130, 140, 150, 160, 170, 180]
    arb_vals = [320, 350, 380, 400, 420, 450, 500]
    small_vals = [120, 130, 140, 150, 160, 170, 180, 200]
    large_vals = [30, 35, 40, 45, 50, 60]

    all_params = []
    for retail, medium, arb, small, large in itertools.product(
        retail_vals,
        medium_vals,
        arb_vals,
        small_vals,
        large_vals,
    ):
        if retail <= medium <= arb and small > large:
            all_params.append({
                "retail": retail,
                "medium": medium,
                "arb": arb,
                "small": small,
                "large": large,
            })

    rng = random.Random(42)
    max_variants = 1200
    sampled = all_params if len(all_params) <= max_variants else rng.sample(all_params, max_variants)

    # Always include current best for direct benchmark inside each sweep.
    if current_best not in sampled:
        sampled.append(current_best)

    for params in sampled:
        specs.append(StrategySpec(
            name=f"P_r{params['retail']}_m{params['medium']}_a{params['arb']}_s{params['small']}_l{params['large']}",
            template=PUSH_TEMPLATE,
            params=params,
        ))

    print(f"\nTotal variants to test: {len(specs)}")

    results = harness.run_sweep(specs)

    # Analysis - sort by edge only, ignore wins
    valid = [r for r in results if r.error is None]
    if valid:
        by_edge = sorted(valid, key=lambda r: r.edge, reverse=True)

        print("\n" + "=" * 70)
        print("TOP 30 BY EDGE (ignoring win rate):")
        print("=" * 70)
        for r in by_edge[:30]:
            print(f"edge={r.edge:7.2f} | wins={r.wins:3d}/{r.total} ({r.win_rate*100:5.1f}%) | {r.spec.params}")

        print("\n" + "=" * 70)
        print("TOP 20 WITH <= 1% WIN RATE:")
        print("=" * 70)
        low_win = [r for r in by_edge if r.win_rate <= 0.01]
        for r in low_win[:20]:
            print(f"edge={r.edge:7.2f} | wins={r.wins:3d}/{r.total} ({r.win_rate*100:5.1f}%) | {r.spec.params}")

        print("\n" + "=" * 70)
        print("CURRENT REFERENCE RESULT:")
        print("=" * 70)
        ref = [r for r in valid if r.spec.params == current_best]
        if ref:
            r = ref[0]
            print(f"edge={r.edge:7.2f} | wins={r.wins:3d}/{r.total} ({r.win_rate*100:5.1f}%) | {r.spec.params}")

        # Group by win rate buckets
        print("\n" + "=" * 70)
        print("BEST BY WIN RATE BUCKET:")
        print("=" * 70)

        buckets = [(0, 10), (10, 25), (25, 50), (50, 75), (75, 90), (90, 100)]
        for low, high in buckets:
            bucket = [r for r in valid if low <= r.win_rate * 100 < high]
            if bucket:
                best = max(bucket, key=lambda r: r.edge)
                print(f"{low:2d}-{high:2d}% wins: edge={best.edge:7.2f} | wins={best.wins:3d}/{best.total} | {best.spec.params}")


if __name__ == "__main__":
    main()
