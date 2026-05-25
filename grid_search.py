#!/usr/bin/env python3
"""
Grid Search for Optimal Strategy Parameters

Core strategy: Spike on large trades (likely arb), decay back to competitive base.

Parameters to search:
- BASE_FEE: Competitive rate to capture retail (must be < 30 bps normalizer)
- POST_ARB_FEE: Fee after detecting arb
- ARB_THRESHOLD: Trade ratio above which we spike
- DECAY_PER_STEP: How fast we return to base
- ASYMMETRIC_EXTRA: Extra fee on the hit side
"""

import sys
import json
import itertools
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import multiprocessing as mp

sys.path.insert(0, str(Path(__file__).parent))

from amm_competition.competition.match import MatchRunner
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE, resolve_n_workers
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator
from amm_competition.evm.baseline import load_vanilla_strategy
import amm_sim_rs


# Strategy template with placeholders for parameters
STRATEGY_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;

    uint256 constant BASE_FEE = {base_fee} * BPS;
    uint256 constant POST_ARB_FEE = {post_arb_fee} * BPS;
    uint256 constant ARB_THRESHOLD = WAD / {arb_divisor};  // {arb_pct}%
    uint256 constant DECAY_PER_STEP = {decay} * BPS;
    uint256 constant ASYMMETRIC_EXTRA = {asymmetric} * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {{
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        return (BASE_FEE, BASE_FEE);
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {{
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 lastTs = slots[SLOT_LAST_TS];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Time decay
        if (trade.timestamp > lastTs) {{
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 50) {{
                uint256 decay = steps * DECAY_PER_STEP;
                if (bidFee > BASE_FEE) {{
                    bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
                }}
                if (askFee > BASE_FEE) {{
                    askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
                }}
            }}
        }}
        slots[SLOT_LAST_TS] = trade.timestamp;

        // Arb detection
        if (tradeRatio > ARB_THRESHOLD) {{
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;
            if (trade.isBuy) {{
                bidFee = clampFee(bidFee + ASYMMETRIC_EXTRA);
            }} else {{
                askFee = clampFee(askFee + ASYMMETRIC_EXTRA);
            }}
        }}

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;
        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "GS_{base_fee}_{post_arb_fee}_{arb_divisor}_{decay}_{asymmetric}";
    }}
}}
'''


@dataclass
class StrategyParams:
    """Strategy parameters for grid search."""
    base_fee: int       # bps
    post_arb_fee: int   # bps
    arb_divisor: int    # WAD / arb_divisor = threshold (e.g., 40 = 2.5%)
    decay: int          # bps per step
    asymmetric: int     # bps extra on hit side

    @property
    def arb_pct(self) -> float:
        return 100.0 / self.arb_divisor

    def to_dict(self) -> dict:
        return {
            'base_fee': self.base_fee,
            'post_arb_fee': self.post_arb_fee,
            'arb_divisor': self.arb_divisor,
            'arb_pct': self.arb_pct,
            'decay': self.decay,
            'asymmetric': self.asymmetric,
        }


@dataclass
class SearchResult:
    """Result of testing one parameter combination."""
    params: StrategyParams
    edge: float
    normalizer_edge: float
    margin: float  # edge - normalizer_edge
    wins: int
    losses: int
    draws: int

    def to_dict(self) -> dict:
        return {
            'params': self.params.to_dict(),
            'edge': self.edge,
            'normalizer_edge': self.normalizer_edge,
            'margin': self.margin,
            'wins': self.wins,
            'losses': self.losses,
            'draws': self.draws,
        }


def generate_source(params: StrategyParams) -> str:
    """Generate Solidity source code for given parameters."""
    return STRATEGY_TEMPLATE.format(
        base_fee=params.base_fee,
        post_arb_fee=params.post_arb_fee,
        arb_divisor=params.arb_divisor,
        arb_pct=params.arb_pct,
        decay=params.decay,
        asymmetric=params.asymmetric,
    )


def compile_strategy(source: str) -> Optional[EVMStrategyAdapter]:
    """Compile and validate a strategy."""
    validator = SolidityValidator()
    validation = validator.validate(source)
    if not validation.valid:
        return None

    compiler = SolidityCompiler()
    compilation = compiler.compile(source)
    if not compilation.success:
        return None

    return EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)


# Cache the normalizer
_NORMALIZER = None

def get_normalizer() -> EVMStrategyAdapter:
    """Get the 30 bps normalizer strategy (cached)."""
    global _NORMALIZER
    if _NORMALIZER is None:
        _NORMALIZER = load_vanilla_strategy()
    return _NORMALIZER


def test_params(params: StrategyParams, n_sims: int = 100) -> Optional[SearchResult]:
    """Test a single parameter combination against the normalizer."""
    source = generate_source(params)
    strategy = compile_strategy(source)
    if strategy is None:
        return None

    normalizer = get_normalizer()

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

    # Run strategy (A) vs normalizer (B)
    result = runner.run_match(strategy, normalizer, store_results=False)
    edge = float(result.total_edge_a / n_sims)
    normalizer_edge = float(result.total_edge_b / n_sims)
    margin = edge - normalizer_edge

    return SearchResult(
        params=params,
        edge=edge,
        normalizer_edge=normalizer_edge,
        margin=margin,
        wins=result.wins_a,
        losses=result.wins_b,
        draws=result.draws,
    )


def run_grid_search(
    base_fees: list[int],
    post_arb_fees: list[int],
    arb_divisors: list[int],
    decays: list[int],
    asymmetrics: list[int],
    n_sims: int = 100,
) -> list[SearchResult]:
    """Run grid search over all parameter combinations."""

    # Generate all combinations
    combinations = list(itertools.product(
        base_fees, post_arb_fees, arb_divisors, decays, asymmetrics
    ))

    total = len(combinations)
    print(f"Grid search: {total} combinations")
    print(f"  base_fees: {base_fees}")
    print(f"  post_arb_fees: {post_arb_fees}")
    print(f"  arb_divisors: {arb_divisors} (thresholds: {[f'{100/d:.1f}%' for d in arb_divisors]})")
    print(f"  decays: {decays}")
    print(f"  asymmetrics: {asymmetrics}")
    print(f"  n_sims: {n_sims}")
    print("=" * 80)

    results = []
    for i, (base, post_arb, arb_div, decay, asym) in enumerate(combinations):
        params = StrategyParams(
            base_fee=base,
            post_arb_fee=post_arb,
            arb_divisor=arb_div,
            decay=decay,
            asymmetric=asym,
        )

        result = test_params(params, n_sims)
        if result:
            results.append(result)
            win_rate = result.wins / n_sims * 100
            print(f"[{i+1:3d}/{total}] base={base:2d} post={post_arb:3d} arb={100/arb_div:.1f}% "
                  f"decay={decay} asym={asym:2d} => edge={result.edge:7.2f} margin={result.margin:+7.2f} "
                  f"wins={win_rate:.0f}%")
        else:
            print(f"[{i+1:3d}/{total}] FAILED: base={base} post={post_arb}")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Grid search for optimal strategy parameters')
    parser.add_argument('--sims', type=int, default=100, help='Simulations per test (default: 100)')
    parser.add_argument('--quick', action='store_true', help='Quick test with reduced grid')
    parser.add_argument('--fine', action='store_true', help='Fine grid around known good values')
    parser.add_argument('--output', type=str, default=None, help='Output JSON file')
    args = parser.parse_args()

    if args.quick:
        # Quick test - reduced grid
        base_fees = [24, 26, 28]
        post_arb_fees = [45, 55, 65]
        arb_divisors = [40, 50]  # 2.5%, 2%
        decays = [5, 7]
        asymmetrics = [10, 15]
        n_sims = 50
    elif args.fine:
        # Fine grid around known good values
        base_fees = [23, 24, 25, 26, 27]
        post_arb_fees = [50, 55, 60, 65]
        arb_divisors = [35, 40, 45, 50]  # 2.86%, 2.5%, 2.22%, 2%
        decays = [5, 6, 7, 8]
        asymmetrics = [10, 12, 15]
        n_sims = args.sims
    else:
        # Standard grid
        base_fees = [22, 24, 26, 28]
        post_arb_fees = [45, 55, 65, 75]
        arb_divisors = [30, 40, 50]  # 3.3%, 2.5%, 2%
        decays = [4, 5, 6, 7]
        asymmetrics = [8, 10, 12, 15]
        n_sims = args.sims

    print(f"\n{'='*80}")
    print(f"GRID SEARCH vs NORMALIZER (30 bps) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")

    results = run_grid_search(
        base_fees=base_fees,
        post_arb_fees=post_arb_fees,
        arb_divisors=arb_divisors,
        decays=decays,
        asymmetrics=asymmetrics,
        n_sims=n_sims,
    )

    # Sort by margin (how much we beat normalizer by)
    results.sort(key=lambda r: -r.margin)

    print("\n" + "=" * 80)
    print("TOP 10 RESULTS (sorted by margin over normalizer)")
    print("=" * 80)
    for i, r in enumerate(results[:10]):
        p = r.params
        print(f"{i+1:2d}. margin={r.margin:+7.2f} edge={r.edge:7.2f} | base={p.base_fee:2d} "
              f"post={p.post_arb_fee:3d} arb={p.arb_pct:.1f}% decay={p.decay} asym={p.asymmetric}")

    # Best result
    if results:
        best = results[0]
        print("\n" + "=" * 80)
        print("BEST CONFIGURATION")
        print("=" * 80)
        print(f"Edge: {best.edge:.2f}")
        print(f"Normalizer Edge: {best.normalizer_edge:.2f}")
        print(f"Margin (edge - normalizer): {best.margin:+.2f}")
        print(f"Win Rate: {best.wins}/{best.wins + best.losses + best.draws} ({best.wins/(best.wins+best.losses+best.draws)*100:.1f}%)")
        print(f"\nParameters:")
        print(f"  BASE_FEE = {best.params.base_fee} * BPS")
        print(f"  POST_ARB_FEE = {best.params.post_arb_fee} * BPS")
        print(f"  ARB_THRESHOLD = WAD / {best.params.arb_divisor}  // {best.params.arb_pct:.2f}%")
        print(f"  DECAY_PER_STEP = {best.params.decay} * BPS")
        print(f"  ASYMMETRIC_EXTRA = {best.params.asymmetric} * BPS")

    # Save results
    output_file = args.output or f"grid_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'n_sims': n_sims,
            'results': [r.to_dict() for r in results],
        }, f, indent=2)
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
