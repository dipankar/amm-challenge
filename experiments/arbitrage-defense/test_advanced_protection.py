#!/usr/bin/env python3
"""Test more advanced arb protection and edge case handling."""

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


# More sophisticated template with multi-signal arb detection
TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;
    uint256 constant SLOT_LAST_DIR = 4;
    uint256 constant SLOT_CONSEC = 5;

    uint256 constant BASE_FEE = {base} * BPS;
    uint256 constant POST_ARB_FEE = {arb} * BPS;
    uint256 constant ARB_THRESHOLD = WAD / {arb_thresh};
    uint256 constant DECAY_PER_STEP = {decay} * BPS;
    uint256 constant ALPHA = WAD / 8;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_EWMA] = WAD / 100;
        return (BASE_FEE, BASE_FEE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 lastTs = slots[SLOT_LAST_TS];
        uint256 ewma = slots[SLOT_EWMA];
        uint256 lastDir = slots[SLOT_LAST_DIR];
        uint256 consec = slots[SLOT_CONSEC];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        // Track consecutive same-direction trades
        uint256 thisDir = trade.isBuy ? 1 : 2;
        if (thisDir == lastDir) {{
            consec = consec < 10 ? consec + 1 : 10;
        }} else {{
            consec = 1;
        }}
        slots[SLOT_LAST_DIR] = thisDir;
        slots[SLOT_CONSEC] = consec;

        // Decay
        if (trade.timestamp > lastTs) {{
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 30) {{
                uint256 decay = steps * DECAY_PER_STEP;
                if (bidFee > BASE_FEE) bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
                if (askFee > BASE_FEE) askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
            }}
        }}
        slots[SLOT_LAST_TS] = trade.timestamp;

        // Multi-signal arb detection
        bool isLargeTrade = tradeRatio > ARB_THRESHOLD;
        bool isAboveEwma = tradeRatio > ewma * 3;
        bool isConsecTrend = consec >= 3;

        if (isLargeTrade || isAboveEwma) {{
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;
            // Extra on hit side
            if (trade.isBuy) bidFee = clampFee(bidFee + {extra} * BPS);
            else askFee = clampFee(askFee + {extra} * BPS);

            // Even more if consecutive trend
            if (isConsecTrend) {{
                if (trade.isBuy) bidFee = clampFee(bidFee + consec * 5 * BPS);
                else askFee = clampFee(askFee + consec * 5 * BPS);
            }}
        }}

        // Strong inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 65 / 100) {{
            askFee = clampFee(askFee + 30 * BPS);
        }} else if (ratio < WAD * 80 / 100) {{
            askFee = clampFee(askFee + 15 * BPS);
        }} else if (ratio > WAD * 135 / 100) {{
            bidFee = clampFee(bidFee + 30 * BPS);
        }} else if (ratio > WAD * 120 / 100) {{
            bidFee = clampFee(bidFee + 15 * BPS);
        }}

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;
        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "Variant";
    }}
}}
'''


def test_variant(base, arb, arb_thresh, decay, extra, n_sims=400):
    source = TEMPLATE.format(base=base, arb=arb, arb_thresh=arb_thresh, decay=decay, extra=extra)

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
    print(f"Testing advanced protection strategies ({n_sims} sims each)")
    print("=" * 80)
    print(f"{'Config':50} | {'Our Edge':>10} | {'Norm':>10}")
    print("-" * 80)

    # Test with stronger protection
    variants = [
        # (base, arb, arb_thresh, decay, extra)
        (50, 120, 35, 25, 25),
        (50, 140, 30, 28, 30),
        (55, 120, 35, 27, 25),
        (55, 140, 30, 30, 30),
        (55, 160, 28, 32, 35),
        (60, 140, 30, 30, 30),
        (60, 160, 28, 32, 35),
        (60, 180, 25, 35, 40),
        (65, 160, 28, 35, 35),
        (65, 180, 25, 38, 40),
        (70, 180, 25, 40, 40),
        (70, 200, 22, 45, 45),
    ]

    results = []
    for base, arb, arb_thresh, decay, extra in variants:
        our_edge, norm_edge = test_variant(base, arb, arb_thresh, decay, extra, n_sims)
        if our_edge is not None:
            results.append((base, arb, arb_thresh, decay, extra, our_edge, norm_edge))
            config_str = f"base={base}, arb={arb}, th=1/{arb_thresh}, dec={decay}, ext={extra}"
            print(f"{config_str:50} | {our_edge:>10.2f} | {norm_edge:>10.2f}")

    print("\n" + "=" * 80)
    print("TOP 5 BY OUR ABSOLUTE EDGE:")
    print("=" * 80)
    for base, arb, arb_thresh, decay, extra, our, norm in sorted(results, key=lambda x: -x[5])[:5]:
        gap = norm - our
        print(f"edge={our:>7.2f} | base={base}, arb={arb}, thresh=1/{arb_thresh}, decay={decay}, extra={extra} | gap={gap:+.2f}")


if __name__ == "__main__":
    main()
