#!/usr/bin/env python3
"""Test aggressive undercutting to capture more volume."""

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
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;

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

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        if (trade.timestamp > lastTs) {{
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 30) {{
                uint256 decay = steps * DECAY_PER_STEP;
                if (bidFee > BASE_FEE) bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
                if (askFee > BASE_FEE) askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
            }}
        }}
        slots[SLOT_LAST_TS] = trade.timestamp;

        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;

        if (isArb) {{
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;
            if (trade.isBuy) bidFee = clampFee(bidFee + 30 * BPS);
            else askFee = clampFee(askFee + 30 * BPS);
        }}

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


def test_variant(base, arb, arb_thresh, decay, n_sims=400):
    source = TEMPLATE.format(base=base, arb=arb, arb_thresh=arb_thresh, decay=decay)

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
    print(f"Testing aggressive undercutting ({n_sims} sims each)")
    print("=" * 70)
    print(f"{'Config':40} | {'Our Edge':>10} | {'Norm':>10} | {'Gap':>8}")
    print("-" * 70)

    # Undercut normalizer significantly
    variants = [
        # (base, arb, arb_thresh, decay)
        # Lower base to capture more volume
        (25, 80, 50, 10),
        (25, 100, 45, 12),
        (25, 120, 40, 15),
        (20, 80, 50, 8),
        (20, 100, 45, 10),
        (20, 120, 40, 12),
        (20, 150, 35, 15),
        (15, 80, 50, 6),
        (15, 100, 45, 8),
        (15, 120, 40, 10),
        (15, 150, 35, 12),
        (10, 100, 50, 6),
        (10, 120, 45, 8),
        (10, 150, 40, 10),
        (5, 100, 50, 4),
        (5, 150, 40, 8),
    ]

    results = []
    for base, arb, arb_thresh, decay in variants:
        our_edge, norm_edge = test_variant(base, arb, arb_thresh, decay, n_sims)
        if our_edge is not None:
            gap = norm_edge - our_edge
            results.append((base, arb, arb_thresh, decay, our_edge, norm_edge, gap))
            config_str = f"base={base}, arb={arb}, th=1/{arb_thresh}, dec={decay}"
            print(f"{config_str:40} | {our_edge:>10.2f} | {norm_edge:>10.2f} | {gap:>+8.2f}")

    print("\n" + "=" * 70)
    print("TOP 5 BY OUR ABSOLUTE EDGE:")
    print("=" * 70)
    for base, arb, arb_thresh, decay, our, norm, gap in sorted(results, key=lambda x: -x[4])[:5]:
        print(f"edge={our:>7.2f} | base={base}, arb={arb}, thresh=1/{arb_thresh}, decay={decay} | gap={gap:+.2f}")


if __name__ == "__main__":
    main()
