#!/usr/bin/env python3
"""Parallel testing harness for AMM strategy optimization.

Enables testing multiple strategy variants simultaneously to maximize edge.
Uses multiprocessing to run N Python workers, each with their own Rust simulation engine.

Usage:
    from parallel_harness import ParallelHarness, StrategySpec

    harness = ParallelHarness(n_workers=4, n_sims=500)

    # Grid search
    results = harness.run_grid(TEMPLATE, {
        "base": [48, 50, 52],
        "arb": [120, 125, 130],
    })

    # Or explicit specs
    specs = [StrategySpec("v1", TEMPLATE, {"base": 50}), ...]
    results = harness.run_sweep(specs)
"""

import itertools
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any, Callable, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import amm_sim_rs
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE
from amm_competition.competition.match import HyperparameterVariance, MatchRunner
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import load_vanilla_strategy
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator


@dataclass
class StrategySpec:
    """Specification for a strategy variant to test."""
    name: str
    template: str
    params: dict[str, Any]


@dataclass
class TestResult:
    """Result from testing a single strategy variant."""
    spec: StrategySpec
    edge: float
    wins: int
    total: int
    time_s: float
    error: Optional[str] = None

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.0


# Global state for worker processes (initialized once per worker)
_COMPILER: Optional[SolidityCompiler] = None
_VALIDATOR: Optional[SolidityValidator] = None
_BASELINE_BYTECODE: Optional[bytes] = None
_BASELINE_ABI: Optional[list] = None
_N_RUST_WORKERS: int = 2
_N_SIMS: int = 500


def _worker_init(baseline_bytecode: bytes, baseline_abi: list, n_rust_workers: int, n_sims: int):
    """Initialize worker process with compiler and baseline strategy."""
    global _COMPILER, _VALIDATOR, _BASELINE_BYTECODE, _BASELINE_ABI, _N_RUST_WORKERS, _N_SIMS

    _COMPILER = SolidityCompiler()
    _VALIDATOR = SolidityValidator()
    _BASELINE_BYTECODE = baseline_bytecode
    _BASELINE_ABI = baseline_abi
    _N_RUST_WORKERS = n_rust_workers
    _N_SIMS = n_sims


def _test_variant(spec: StrategySpec) -> TestResult:
    """Test a single strategy variant (runs in worker process)."""
    start_time = time.time()

    try:
        # Generate source from template
        source = spec.template.format(**spec.params)

        # Validate
        validation = _VALIDATOR.validate(source)
        if not validation.valid:
            return TestResult(
                spec=spec,
                edge=0.0,
                wins=0,
                total=0,
                time_s=time.time() - start_time,
                error=f"Validation failed: {validation.errors}",
            )

        # Compile
        compilation = _COMPILER.compile(source)
        if not compilation.success:
            return TestResult(
                spec=spec,
                edge=0.0,
                wins=0,
                total=0,
                time_s=time.time() - start_time,
                error=f"Compilation failed: {compilation.errors}",
            )

        # Create adapters
        strategy = EVMStrategyAdapter(bytecode=compilation.bytecode, abi=compilation.abi)
        baseline = EVMStrategyAdapter(bytecode=_BASELINE_BYTECODE, abi=_BASELINE_ABI)

        # Build config with midpoint variance values
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

        # Run match
        runner = MatchRunner(
            n_simulations=_N_SIMS,
            config=config,
            n_workers=_N_RUST_WORKERS,
            variance=BASELINE_VARIANCE,
        )

        result = runner.run_match(strategy, baseline, store_results=False)

        return TestResult(
            spec=spec,
            edge=float(result.total_edge_a / _N_SIMS),
            wins=result.wins_a,
            total=result.wins_a + result.wins_b + result.draws,
            time_s=time.time() - start_time,
        )

    except Exception as e:
        return TestResult(
            spec=spec,
            edge=0.0,
            wins=0,
            total=0,
            time_s=time.time() - start_time,
            error=str(e),
        )


class ParallelHarness:
    """Parallel testing harness for strategy optimization."""

    def __init__(
        self,
        n_workers: int = 4,
        rust_workers_per: int = 2,
        n_sims: int = 500,
        verbose: bool = True,
    ):
        """Initialize the harness.

        Args:
            n_workers: Number of Python worker processes (default: 4)
            rust_workers_per: Rust threads per Python worker (default: 2)
            n_sims: Number of simulations per variant (default: 500)
            verbose: Print progress to stdout (default: True)
        """
        self.n_workers = min(n_workers, cpu_count())
        self.rust_workers_per = rust_workers_per
        self.n_sims = n_sims
        self.verbose = verbose

        # Load baseline strategy once (will be pickled to workers)
        baseline = load_vanilla_strategy()
        self._baseline_bytecode = bytes(baseline._bytecode)
        self._baseline_abi = baseline._abi

    def run_sweep(
        self,
        specs: list[StrategySpec],
        callback: Optional[Callable[[TestResult], None]] = None,
    ) -> list[TestResult]:
        """Run tests for a list of strategy specifications in parallel.

        Args:
            specs: List of StrategySpec to test
            callback: Optional callback for each result (for streaming)

        Returns:
            List of TestResult for all specs
        """
        if not specs:
            return []

        if self.verbose:
            print(f"\n{'='*70}")
            print(f"PARALLEL SWEEP: {len(specs)} variants")
            print(f"Workers: {self.n_workers} Python × {self.rust_workers_per} Rust = {self.n_workers * self.rust_workers_per} threads")
            print(f"Simulations per variant: {self.n_sims}")
            print(f"{'='*70}\n")

        start_time = time.time()
        results: list[TestResult] = []
        completed_ids: set[int] = set()

        with Pool(
            processes=self.n_workers,
            initializer=_worker_init,
            initargs=(self._baseline_bytecode, self._baseline_abi, self.rust_workers_per, self.n_sims),
        ) as pool:
            # Submit all tasks asynchronously
            async_results = [(i, pool.apply_async(_test_variant, (spec,))) for i, spec in enumerate(specs)]

            # Poll for completion with streaming output
            while len(completed_ids) < len(specs):
                for i, ar in async_results:
                    if i not in completed_ids and ar.ready():
                        try:
                            result = ar.get()
                            results.append(result)
                            completed_ids.add(i)

                            if callback:
                                callback(result)

                            if self.verbose:
                                self._print_result(result, len(completed_ids), len(specs))
                        except Exception as e:
                            # Handle worker errors
                            spec = specs[i]
                            result = TestResult(
                                spec=spec,
                                edge=0.0,
                                wins=0,
                                total=0,
                                time_s=0.0,
                                error=str(e),
                            )
                            results.append(result)
                            completed_ids.add(i)

                            if self.verbose:
                                print(f"[{len(completed_ids):3d}/{len(specs)}] {spec.name}: ERROR - {e}")

                time.sleep(0.05)  # Avoid busy-waiting

        total_time = time.time() - start_time

        if self.verbose:
            self._print_summary(results, total_time)

        return results

    def run_grid(
        self,
        template: str,
        param_grid: dict[str, list[Any]],
        callback: Optional[Callable[[TestResult], None]] = None,
    ) -> list[TestResult]:
        """Run a grid search over parameter combinations.

        Args:
            template: Solidity template with {param} placeholders
            param_grid: Dict of param_name -> list of values to try
            callback: Optional callback for each result

        Returns:
            List of TestResult for all combinations
        """
        specs = list(self._generate_grid(template, param_grid))

        if self.verbose:
            print(f"Generated {len(specs)} combinations from grid:")
            for param, values in param_grid.items():
                print(f"  {param}: {values}")

        return self.run_sweep(specs, callback)

    def _generate_grid(self, template: str, param_grid: dict[str, list[Any]]) -> list[StrategySpec]:
        """Generate all combinations from parameter grid."""
        keys = list(param_grid.keys())
        for values in itertools.product(*[param_grid[k] for k in keys]):
            params = dict(zip(keys, values))
            name = "_".join(f"{k}{v}" for k, v in params.items())
            yield StrategySpec(name=name, template=template, params=params)

    def _print_result(self, result: TestResult, completed: int, total: int):
        """Print a single result."""
        if result.error:
            print(f"[{completed:3d}/{total}] {result.spec.name}: ERROR - {result.error}")
        else:
            params_str = ", ".join(f"{k}={v}" for k, v in result.spec.params.items())
            print(
                f"[{completed:3d}/{total}] edge={result.edge:7.2f} | "
                f"wins={result.wins:3d}/{result.total} ({result.win_rate*100:5.1f}%) | "
                f"{result.time_s:5.1f}s | {params_str}"
            )

    def _print_summary(self, results: list[TestResult], total_time: float):
        """Print summary of results."""
        valid_results = [r for r in results if r.error is None]

        if not valid_results:
            print("\nNo valid results!")
            return

        sorted_results = sorted(valid_results, key=lambda r: -r.edge)

        print(f"\n{'='*70}")
        print(f"SUMMARY - Total time: {total_time:.1f}s ({total_time/len(results):.1f}s/variant avg)")
        print(f"{'='*70}")
        print(f"\nTOP 10 BY EDGE:")
        print("-" * 70)

        for i, r in enumerate(sorted_results[:10], 1):
            params_str = ", ".join(f"{k}={v}" for k, v in r.spec.params.items())
            print(
                f"{i:2d}. edge={r.edge:7.2f} | "
                f"wins={r.wins:3d}/{r.total} ({r.win_rate*100:5.1f}%) | "
                f"{params_str}"
            )

        best = sorted_results[0]
        print(f"\n{'='*70}")
        print(f"BEST: {best.spec.name}")
        print(f"  Edge: {best.edge:.2f}")
        print(f"  Win Rate: {best.wins}/{best.total} ({best.win_rate*100:.1f}%)")
        print(f"  Params: {best.spec.params}")
        print(f"{'='*70}\n")


# =============================================================================
# EXAMPLE TEMPLATES
# =============================================================================

MAXEDGE_TEMPLATE = '''// SPDX-License-Identifier: MIT
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
            if (trade.isBuy) bidFee = clampFee(bidFee + 20 * BPS);
            else askFee = clampFee(askFee + 20 * BPS);
        }} else if (tradeRatio < ewma / 3) {{
            bidFee = BASE_FEE - 3 * BPS;
            askFee = BASE_FEE - 3 * BPS;
        }}

        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 75 / 100) askFee = clampFee(askFee + 15 * BPS);
        else if (ratio > WAD * 125 / 100) bidFee = clampFee(bidFee + 15 * BPS);

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;
        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{
        return "MaxEdge";
    }}
}}
'''


# =============================================================================
# MAIN - Example usage
# =============================================================================

if __name__ == "__main__":
    # Example: Grid search around known good parameters
    harness = ParallelHarness(
        n_workers=4,
        rust_workers_per=2,
        n_sims=500,
    )

    # Quick grid search
    results = harness.run_grid(
        template=MAXEDGE_TEMPLATE,
        param_grid={
            "base": [48, 50, 52, 54, 56],
            "arb": [115, 120, 125, 130],
            "arb_thresh": [30, 32, 35],
            "decay": [22, 24, 26, 28],
        },
    )

    # Results are already printed by harness, but you can also process them:
    best = max([r for r in results if r.error is None], key=lambda r: r.edge)
    print(f"\nBest configuration to try: {best.spec.params}")
