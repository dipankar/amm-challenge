#!/usr/bin/env python3
"""Test EWMA-based dynamic fee adjustment."""

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


# EWMA-based dynamic fee - fee scales with volatility
TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;
    uint256 constant SLOT_VOL_EWMA = 4;

    uint256 constant MIN_BASE = {min_base} * BPS;
    uint256 constant MAX_BASE = {max_base} * BPS;
    uint256 constant SPIKE_FEE = {spike} * BPS;
    uint256 constant ARB_THRESHOLD = WAD / {arb_thresh};
    uint256 constant DECAY_PER_STEP = {decay} * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        uint256 startFee = (MIN_BASE + MAX_BASE) / 2;
        slots[SLOT_BID_FEE] = startFee;
        slots[SLOT_ASK_FEE] = startFee;
        slots[SLOT_EWMA] = WAD / 100;
        slots[SLOT_VOL_EWMA] = WAD / 100;
        return (startFee, startFee);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 lastTs = slots[SLOT_LAST_TS];
        uint256 ewma = slots[SLOT_EWMA];
        uint256 volEwma = slots[SLOT_VOL_EWMA];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update trade size EWMA
        uint256 alpha = WAD / 8;
        ewma = wmul(ewma, WAD - alpha) + wmul(tradeRatio, alpha);
        slots[SLOT_EWMA] = ewma;

        // Update volatility EWMA (absolute deviation from mean)
        uint256 deviation = tradeRatio > ewma ? tradeRatio - ewma : ewma - tradeRatio;
        volEwma = wmul(volEwma, WAD - alpha) + wmul(deviation, alpha);
        slots[SLOT_VOL_EWMA] = volEwma;

        // Calculate base fee based on volatility
        // Higher volatility = higher base fee
        uint256 volMultiplier = wdiv(volEwma, WAD / 100);  // normalize
        if (volMultiplier > WAD * 5) volMultiplier = WAD * 5;  // cap at 5x
        uint256 baseFee = MIN_BASE + wmul(MAX_BASE - MIN_BASE, volMultiplier / 5);

        // Time decay toward dynamic base
        if (trade.timestamp > lastTs) {{
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 30) {{
                uint256 decay = steps * DECAY_PER_STEP;
                if (bidFee > baseFee) bidFee = bidFee > baseFee + decay ? bidFee - decay : baseFee;
                if (askFee > baseFee) askFee = askFee > baseFee + decay ? askFee - decay : baseFee;
                // Also pull up if below base
                if (bidFee < baseFee) bidFee = baseFee;
                if (askFee < baseFee) askFee = baseFee;
            }}
        }}
        slots[SLOT_LAST_TS] = trade.timestamp;

        // Arb detection
        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;

        if (isArb) {{
            bidFee = SPIKE_FEE;
            askFee = SPIKE_FEE;
            if (trade.isBuy) bidFee = clampFee(bidFee + 25 * BPS);
            else askFee = clampFee(askFee + 25 * BPS);
        }}

        // Inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 70 / 100) askFee = clampFee(askFee + 25 * BPS);
        else if (ratio > WAD * 130 / 100) bidFee = clampFee(bidFee + 25 * BPS);

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;
        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "Variant";
    }}
}}
'''


def test_variant(min_base, max_base, spike, arb_thresh, decay, n_sims=400):
    source = TEMPLATE.format(min_base=min_base, max_base=max_base, spike=spike, arb_thresh=arb_thresh, decay=decay)

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

    result = runner.run_match(strategy, baseline, store_results=False)
    our_edge = float(result.total_edge_a / n_sims)
    norm_edge = float(result.total_edge_b / n_sims)

    return our_edge, norm_edge


def main():
    n_sims = 400
    print(f"Testing EWMA dynamic strategies ({n_sims} sims each)")
    print("=" * 80)
    print(f"{'Config':55} | {'Our Edge':>10} | {'Norm':>10}")
    print("-" * 80)

    # Various configurations
    variants = [
        # (min_base, max_base, spike, arb_thresh, decay)
        (30, 60, 120, 35, 25),
        (30, 70, 130, 35, 27),
        (35, 70, 130, 35, 27),
        (40, 70, 130, 35, 27),
        (40, 80, 140, 30, 30),
        (45, 80, 140, 30, 30),
        (45, 90, 150, 30, 32),
        (50, 80, 130, 35, 27),
        (50, 90, 140, 30, 30),
        (50, 100, 150, 28, 32),
        (55, 90, 140, 30, 30),
        (55, 100, 150, 28, 32),
        (60, 100, 150, 28, 35),
    ]

    results = []
    for min_base, max_base, spike, arb_thresh, decay in variants:
        our_edge, norm_edge = test_variant(min_base, max_base, spike, arb_thresh, decay, n_sims)
        if our_edge is not None:
            results.append((min_base, max_base, spike, arb_thresh, decay, our_edge, norm_edge))
            config_str = f"base=[{min_base}-{max_base}], spike={spike}, th=1/{arb_thresh}, dec={decay}"
            print(f"{config_str:55} | {our_edge:>10.2f} | {norm_edge:>10.2f}")

    print("\n" + "=" * 80)
    print("TOP 5 BY OUR ABSOLUTE EDGE:")
    print("=" * 80)
    for min_base, max_base, spike, arb_thresh, decay, our, norm in sorted(results, key=lambda x: -x[5])[:5]:
        gap = norm - our
        print(f"edge={our:>7.2f} | base=[{min_base}-{max_base}], spike={spike}, thresh=1/{arb_thresh}, decay={decay} | gap={gap:+.2f}")


if __name__ == "__main__":
    main()
