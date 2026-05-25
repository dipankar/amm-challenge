#!/usr/bin/env python3
"""Test aggressive/greedy architecture variants to maximize edge.

Goal: Find strategies that extract maximum edge per trade, even at cost of lower win rate.
Target: Beat 526.39 edge (current leader)

Key insight from prior testing:
- Fixed 80 bps gives max edge (385) with 0% wins
- Normalizer gets 532 edge when we charge high fees (and captures all retail)
- To beat 526, we need architectures that are GREEDY and extract max value per trade
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parallel_harness import ParallelHarness, StrategySpec

# =============================================================================
# ARCHITECTURE 1: EXTREME ASYMMETRIC
# Different fees for buy vs sell - very high on one side, competitive on other
# Uses MAX_FEE from base contract instead of redefining
# =============================================================================
ASYMMETRIC_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant SLOT_PRESSURE = 0;
    uint256 constant SLOT_LAST_TS = 1;

    uint256 constant BASE = {base} * BPS;
    uint256 constant HIGH = {high} * BPS;  // High fee for one direction
    uint256 constant PRESSURE_THRESH = {pressure} * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        return (BASE, BASE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 pressure = slots[SLOT_PRESSURE];

        // Track directional pressure
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        if (trade.isBuy) {{
            pressure = pressure < WAD ? pressure + tradeRatio : WAD;
        }} else {{
            pressure = pressure > tradeRatio ? pressure - tradeRatio : 0;
        }}
        slots[SLOT_PRESSURE] = pressure;

        uint256 bidFee = BASE;
        uint256 askFee = BASE;

        // If pressure indicates lots of buys, charge HIGH on buys
        if (pressure > WAD / 2 + PRESSURE_THRESH) {{
            bidFee = clampFee(HIGH);
        }} else if (pressure < WAD / 2 - PRESSURE_THRESH) {{
            askFee = clampFee(HIGH);
        }}

        // Extra: If trade is large (arb), charge even more
        if (tradeRatio > WAD / 30) {{
            if (trade.isBuy) bidFee = clampFee(bidFee + 50 * BPS);
            else askFee = clampFee(askFee + 50 * BPS);
        }}

        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "Asymmetric";
    }}
}}
'''

# =============================================================================
# ARCHITECTURE 2: SQUEEZE - Charge extreme fees when inventory is imbalanced
# The idea: When reserves are heavily skewed, someone NEEDS to trade to rebalance
# =============================================================================
SQUEEZE_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant BASE = {base} * BPS;
    uint256 constant SQUEEZE_FEE = {squeeze} * BPS;
    uint256 constant IMBALANCE_THRESH = {imbalance};  // 80 = 80% ratio threshold

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        return (BASE, BASE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        // Calculate ratio of X to Y reserves (normalized)
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);

        uint256 bidFee = BASE;
        uint256 askFee = BASE;

        // If heavy imbalance toward X (ratio > threshold), sells are desperate
        if (ratio > WAD * IMBALANCE_THRESH / 100) {{
            askFee = clampFee(SQUEEZE_FEE);
        }}
        // If heavy imbalance toward Y (ratio < 100-threshold), buys are desperate
        else if (ratio < WAD * (200 - IMBALANCE_THRESH) / 100) {{
            bidFee = clampFee(SQUEEZE_FEE);
        }}

        // Large trade = arb, charge extra
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        if (tradeRatio > WAD / 25) {{
            if (trade.isBuy) bidFee = clampFee(bidFee + 30 * BPS);
            else askFee = clampFee(askFee + 30 * BPS);
        }}

        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "Squeeze";
    }}
}}
'''

# =============================================================================
# ARCHITECTURE 3: ULTRA GREEDY - Charge near-max fees always, only undercut for big retail
# Strategy: Extract maximum from every trade unless it's clearly small retail
# =============================================================================
ULTRA_GREEDY_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant HIGH_FEE = {high} * BPS;     // High fee (most trades)
    uint256 constant RETAIL_FEE = {retail} * BPS; // Low fee only for small trades
    uint256 constant SMALL_THRESH = {thresh};     // Trade size threshold (WAD/X)

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        return (HIGH_FEE, HIGH_FEE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Only give low fees to clearly small retail trades
        if (tradeRatio < WAD / SMALL_THRESH) {{
            return (clampFee(RETAIL_FEE), clampFee(RETAIL_FEE));
        }}

        // Everything else gets high fees
        return (clampFee(HIGH_FEE), clampFee(HIGH_FEE));
    }}

    function getName() external pure override returns (string memory) {{
        return "UltraGreedy";
    }}
}}
'''

# =============================================================================
# ARCHITECTURE 4: REACTIVE SPIKE - Normal fees, but spike to max on any arb signal
# =============================================================================
REACTIVE_SPIKE_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant SLOT_EWMA = 0;
    uint256 constant SLOT_SPIKE = 1;

    uint256 constant BASE = {base} * BPS;
    uint256 constant SPIKE = {spike} * BPS;
    uint256 constant ALPHA = WAD / 10;
    uint256 constant ARB_MULT = {arb_mult};  // Trade > ARB_MULT * EWMA = arb

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        slots[SLOT_EWMA] = WAD / 200;  // Start with small expected trade
        return (BASE, BASE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 ewma = slots[SLOT_EWMA];
        uint256 spikeActive = slots[SLOT_SPIKE];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        uint256 bidFee = BASE;
        uint256 askFee = BASE;

        // If this trade is much larger than average -> spike fees
        if (tradeRatio > ewma * ARB_MULT || tradeRatio > WAD / 30) {{
            bidFee = clampFee(SPIKE);
            askFee = clampFee(SPIKE);
            slots[SLOT_SPIKE] = 3;  // Keep spike active for 3 trades
        }} else if (spikeActive > 0) {{
            // Gradually reduce spike
            bidFee = clampFee(BASE + (SPIKE - BASE) * spikeActive / 3);
            askFee = clampFee(BASE + (SPIKE - BASE) * spikeActive / 3);
            slots[SLOT_SPIKE] = spikeActive - 1;
        }}

        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "ReactiveSpike";
    }}
}}
'''

# =============================================================================
# ARCHITECTURE 5: COMPETITIVE UNDERCUT - Match normalizer exactly, +1 bps on arb
# Try to win trades by being exactly at 30 bps like normalizer, extract from arb
# =============================================================================
COMPETITIVE_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant MATCH_FEE = 30 * BPS;  // Match normalizer at 30 bps
    uint256 constant ARB_PREMIUM = {arb_premium} * BPS;  // Extra fee for arbs
    uint256 constant ARB_THRESH = {arb_thresh};  // WAD / X threshold

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        return (MATCH_FEE, MATCH_FEE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Large trade = arb, charge premium
        if (tradeRatio > WAD / ARB_THRESH) {{
            uint256 fee = clampFee(MATCH_FEE + ARB_PREMIUM);
            return (fee, fee);
        }}

        // Otherwise match normalizer exactly
        return (MATCH_FEE, MATCH_FEE);
    }}

    function getName() external pure override returns (string memory) {{
        return "Competitive";
    }}
}}
'''


def main():
    print("=" * 70)
    print("GREEDY ARCHITECTURE SEARCH")
    print("Goal: Maximize edge (current leader: 526.39)")
    print("Strategy: Extract max value per trade, accept lower win rate")
    print("=" * 70)

    harness = ParallelHarness(
        n_workers=4,
        rust_workers_per=2,
        n_sims=500,
    )

    specs = []

    # Architecture 1: Asymmetric - test different high fees and pressure thresholds
    print("\nBuilding Asymmetric specs...")
    for base in [30, 50, 80]:
        for high in [200, 500, 800, 1000]:  # Very high fees
            for pressure in [10, 20, 30]:
                specs.append(StrategySpec(
                    name=f"ASYM_b{base}_h{high}_p{pressure}",
                    template=ASYMMETRIC_TEMPLATE,
                    params={"base": base, "high": high, "pressure": pressure}
                ))

    # Architecture 2: Squeeze - test imbalance thresholds
    print("Building Squeeze specs...")
    for base in [30, 50, 80]:
        for squeeze in [300, 500, 800, 1000]:
            for imbalance in [60, 70, 80, 90]:
                specs.append(StrategySpec(
                    name=f"SQZ_b{base}_s{squeeze}_i{imbalance}",
                    template=SQUEEZE_TEMPLATE,
                    params={"base": base, "squeeze": squeeze, "imbalance": imbalance}
                ))

    # Architecture 3: Ultra Greedy - test high/retail fee combos
    print("Building UltraGreedy specs...")
    for high in [200, 400, 600, 800, 1000]:
        for retail in [20, 25, 28, 30]:
            for thresh in [50, 75, 100, 150]:
                specs.append(StrategySpec(
                    name=f"GRDY_h{high}_r{retail}_t{thresh}",
                    template=ULTRA_GREEDY_TEMPLATE,
                    params={"high": high, "retail": retail, "thresh": thresh}
                ))

    # Architecture 4: Reactive Spike
    print("Building ReactiveSpike specs...")
    for base in [30, 50]:
        for spike in [300, 600, 900]:
            for arb_mult in [2, 3, 5]:
                specs.append(StrategySpec(
                    name=f"SPIKE_b{base}_s{spike}_m{arb_mult}",
                    template=REACTIVE_SPIKE_TEMPLATE,
                    params={"base": base, "spike": spike, "arb_mult": arb_mult}
                ))

    # Architecture 5: Competitive undercut
    print("Building Competitive specs...")
    for arb_premium in [50, 100, 200, 300, 500]:
        for arb_thresh in [20, 30, 50]:
            specs.append(StrategySpec(
                name=f"COMP_p{arb_premium}_t{arb_thresh}",
                template=COMPETITIVE_TEMPLATE,
                params={"arb_premium": arb_premium, "arb_thresh": arb_thresh}
            ))

    print(f"\nTotal variants to test: {len(specs)}")

    results = harness.run_sweep(specs)

    # Additional analysis
    valid = [r for r in results if r.error is None]
    if valid:
        by_arch = {}
        for r in valid:
            arch = r.spec.name.split('_')[0]
            if arch not in by_arch:
                by_arch[arch] = []
            by_arch[arch].append(r)

        print("\n" + "=" * 70)
        print("BEST BY ARCHITECTURE")
        print("=" * 70)
        for arch, arch_results in sorted(by_arch.items()):
            best = max(arch_results, key=lambda r: r.edge)
            print(f"{arch:8s}: edge={best.edge:7.2f} | wins={best.wins:3d}/{best.total} | {best.spec.params}")


if __name__ == "__main__":
    main()
