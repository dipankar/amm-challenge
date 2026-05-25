# Experiments

Each subdirectory contains scripts exploring a specific research question. All scripts write results to `experiments/results/`.

## Directory Index

### `static-baselines/`
**Question**: What is the optimal fixed fee against the 30 bps normalizer?
**Scripts**: `test_fees.py`, `test_high_fees.py`, `test_optimal_static.py`
**Key finding**: Static fees alone cannot beat adaptive strategies; the fee-vs-volume tradeoff has a narrow optimum.

### `arbitrage-defense/`
**Question**: Can we detect arb flow from trade signals and raise fees only during arb attacks?
**Scripts**: `test_advanced_protection.py`, `test_arb_extraction.py`, `test_ewma_dynamic.py`, `test_match_normalizer.py`, `test_undercut.py`
**Approach**: Multi-signal detection (trade size, direction streaks, EWMA smoothing) → dynamic fee adjustment.

### `grid-search/`
**Question**: What parameters maximize edge for the MaxEdge strategy family?
**Scripts**: `test_max_edge_extreme.py`, `test_max_edge_final.py`, `test_max_edge_fine.py`, `test_max_edge_push.py`, `test_max_edge_variants.py`, `test_fine_tune_best.py`
**Approach**: Systematic parameter sweeps across base fee, arb fee, and decay rate dimensions.

### `greedy-architectures/`
**Question**: Can aggressive/greedy fee architectures push edge higher by sacrificing win rate?
**Scripts**: `test_greedy_architectures.py`, `test_greedy_edge.py`, `test_max_edge_greedy.py`, `test_push_edge.py`, `test_fine_tune.py`
**Approach**: Extreme parameter ranges, unconventional fee structures, multi-tier fee models.

### `competitive-benchmarks/`
**Question**: How do our best strategies compare against the normalizer and each other?
**Scripts**: `compare_margin.py`, `analyze_normalizer.py`, `final_validation.py`
**Approach**: Head-to-head comparisons at high simulation counts for statistical confidence.

### `pareto-optimization/`
**Question**: What is the Pareto frontier of edge vs. win rate?
**Scripts**: `optimize_pareto.py`
**Approach**: Multi-objective optimization exploring the edge/win-rate tradeoff surface.

### `single-run-tests/`
**Question**: Quick validation of individual strategies.
**Scripts**: `test_margin.py`, `test_v3.py`, `find_optimal.py`, `find_max_edge.py`, `find_max_edge2.py`, `find_competitive_max.py`
**Approach**: Fast single-strategy tests, often early iterations that led to larger grid searches.

## Results

All output data (JSON grid search results, PNG simulation visualizations) lives in `experiments/results/`. These are gitignored — regenerate them by running the corresponding experiment script.

## Running an Experiment

```bash
cd experiments/<directory>
python <script>.py
```

Scripts depend on `amm_competition` being installed (`pip install -e .`) and the Rust engine being built (`cd amm_sim_rs && maturin develop --release`).
