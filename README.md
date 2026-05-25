# AMM Fee Strategy Challenge

**https://ammchallenge.com**

Design dynamic fee strategies for a constant-product AMM. Your goal: maximize **edge**.

## Results

### Current Best: SigmaAdaptive (526.54 Edge)

| Strategy | Edge (500 sims) | Approach |
|----------|-----------------|----------|
| **SigmaAdaptive** | **526.54** | State estimation + adaptive fees |
| MaxEdgeFinal | 410.58 | High base + extreme arb protection |
| WinningV5 | 295.57 | Low base + spike/decay |

SigmaAdaptive implements techniques from the winning AMM Challenge approaches: fair price estimation (pHat) with adaptive sigma-gated updates, cubic toxicity response, trade-aligned arb detection, and asymmetric directional fees. See [ANALYSIS.md](ANALYSIS.md) for the research methodology post-mortem.

### Leaderboard Context

The competition leaderboard top is ~522.39 with the 30 bps baseline scoring ~522.13. Local scores differ from server due to different RNG seeds, so cross-reference deltas rather than absolute values.

## Quick Start

```bash
git clone https://github.com/benedictbrady/amm-challenge.git
cd amm-challenge

# Install dependencies (requires uv)
uv sync
uv sync --extra dev

# Build Rust engine in release mode
uv run maturin develop --release -m amm_sim_rs/Cargo.toml

# Run 100 simulations
uv run amm-match run contracts/src/SigmaAdaptiveStrategy.sol --simulations 100

# Quick test
uv run amm-match run contracts/src/StarterStrategy.sol --simulations 10

# Validate without running
uv run amm-match validate contracts/src/SigmaAdaptiveStrategy.sol
```

## Repository Structure

```
amm-challenge/
├── amm_competition/          # Python simulation engine
├── amm_sim_rs/               # Rust simulation engine (performance)
├── contracts/
│   ├── src/                  # Solidity strategies (33 total)
│   │   ├── AMMStrategyBase.sol   # Abstract base contract
│   │   ├── IAMMStrategy.sol      # Strategy interface
│   │   ├── StarterStrategy.sol   # Template to copy
│   │   ├── VanillaStrategy.sol   # 30 bps normalizer
│   │   ├── SigmaAdaptiveStrategy.sol  # State-estimating adaptive (best)
│   │   └── ...                    # Experimental strategies
│   └── README.md             # Contract categorization
├── experiments/              # Research experiments by theme
│   ├── static-baselines/     # Fixed-fee calibration
│   ├── arbitrage-defense/    # Arb detection experiments
│   ├── grid-search/          # Parameter sweeps
│   ├── greedy-architectures/ # Aggressive variants
│   ├── competitive-benchmarks/ # Head-to-head comparisons
│   ├── pareto-optimization/  # Multi-objective optimization
│   ├── single-run-tests/     # Quick validations
│   ├── results/              # Output data (gitignored)
│   └── README.md             # Experiment index
├── research/                 # Structured analysis documents
├── tests/                    # pytest suite for the engine
├── ANALYSIS.md               # Research methodology post-mortem
├── parallel_harness.py       # Multiprocessing parameter sweep tool
├── visualize.py              # Simulation visualization CLI
├── grid_search.py            # Parameter search framework
└── pyproject.toml            # Project config (uses uv)
```

## The Simulation

Each simulation runs 10,000 steps. At each step:

1. **Price moves** — A fair price `p` evolves via geometric Brownian motion
2. **Arbitrageurs trade** — They push each AMM's spot price toward `p`, extracting profit
3. **Retail orders arrive** — Random buy/sell orders get routed optimally across AMMs

Your strategy competes against a **normalizer AMM** running fixed 30 bps fees. Both AMMs start with identical reserves (100 X, 10,000 Y at price 100).

### Price Process

The fair price follows GBM: `S(t+1) = S(t) · exp(−σ²/2 + σZ)` where `Z ~ N(0,1)`

- Drift `μ = 0` (no directional bias)
- Per-step volatility `σ ~ U[0.088%, 0.101%]` (varies across simulations)

### Retail Flow

Uninformed traders arrive via Poisson process:

- Arrival rate `λ ~ U[0.6, 1.0]` orders per step
- Order size `~ LogNormal(μ, σ=1.2)` with mean `~ U[19, 21]` in Y terms
- Direction: 50% buy, 50% sell

Retail flow splits optimally between AMMs based on fees — lower fees attract more volume.

## The Math

### Constant Product AMM

Reserves `(x, y)` satisfy `x * y = k`. The spot price is `y/x`. When the AMM sells Δx tokens:

```
Δy = y − k/(x − Δx)    (what trader pays)
```

Fees are taken on input: if fee is `f`, only `(1−f)` of the input affects reserves.

### Arbitrage

When spot price diverges from fair price `p`, arbitrageurs trade to close the gap. For fee `f` (fee-on-input), let `γ = 1 − f`:

- **Spot < fair** (AMM underprices X): Buy X from AMM. Optimal size: `Δx = x − √(k/(γ·p))`
- **Spot > fair** (AMM overprices X): Sell X to AMM. Optimal size: `Δx_in = (√(k·γ/p) − x) / γ`

Higher fees mean arbitrageurs need larger mispricings to profit, so your AMM stays "stale" longer — bad for edge.

### Order Routing

Retail orders split optimally across AMMs to equalize marginal prices post-trade. For two AMMs with fee rates `f₁, f₂`, let `γᵢ = 1 − fᵢ` and `Aᵢ = √(xᵢ γᵢ yᵢ)`. The optimal Y split is:

```
Δy₁ = (r(y₂ + γ₂Y) − y₁) / (γ₁ + rγ₂)    where r = A₁/A₂
```

Lower fees → larger `γ` → more flow. But the relationship is nonlinear — small fee differences can shift large fractions of volume.

### Edge

Edge measures profitability using the fair price at trade time:

```
Edge = Σ (amount_x × fair_price − amount_y)   for sells (AMM sells X)
     + Σ (amount_y − amount_x × fair_price)   for buys  (AMM buys X)
```

- **Retail trades**: Positive edge (you profit from the spread)
- **Arbitrage trades**: Negative edge (you lose to informed flow)

Good strategies maximize retail edge while minimizing arb losses.

## Why the Normalizer?

Without competition, setting 10% fees would appear profitable — you'd capture huge spreads on the few trades that still execute. The normalizer prevents this: if your fees are too high, retail routes to the 30 bps AMM and you get nothing.

The normalizer also means there's no "free lunch" — you can't beat 30 bps just by setting 29 bps. The optimal fee depends on market conditions.

## Writing a Strategy

**Start with `contracts/src/StarterStrategy.sol`** — a simple 50 bps fixed-fee strategy. Copy it, rename `getName()`, and modify the fee logic.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY)
        external override returns (uint256 bidFee, uint256 askFee);

    function afterSwap(TradeInfo calldata trade)
        external override returns (uint256 bidFee, uint256 askFee);

    function getName() external pure override returns (string memory);
}
```

You set a buy fee and a sell fee, and after every trade you can change what fees you're showing the market.

`afterInitialize` is called once at simulation start — return your opening `(bidFee, askFee)`. Then `afterSwap` is called after every trade that hits your AMM. You see what just happened and return updated fees for the next trade.

| Field | Description |
|-------|-------------|
| `isBuy` | `true` if AMM bought X (trader sold X to you) |
| `amountX` | X traded (WAD precision, 1e18 = 1 unit) |
| `amountY` | Y traded |
| `timestamp` | Step number |
| `reserveX`, `reserveY` | Post-trade reserves |

Return fees in WAD: `30 * BPS` = 30 basis points. Max fee is 10%.

You get 32 storage slots (`slots[0..31]`) and helpers like `wmul`, `wdiv`, `sqrt`.

## Key Strategy Techniques

Based on analysis of winning approaches and our own experiments:

### State Estimation (The Winning Insight)

The fair price is hidden, but estimable from observed trades. Key state variables to track:
- **pHat**: Estimated fair price, reconstructed from trade implied prices
- **sigmaHat**: Volatility estimate from absolute returns
- **toxEma**: Toxicity = |spot − pHat| / pHat — how mispriced you are
- **dirState**: Directional pressure (buy vs sell imbalance)

### Adaptive Sigma-Gated Updates

Use a volatility-dependent gate for price updates: tight in low vol for fast tracking, wide in high vol for noise rejection. This enables aggressive price tracking (alpha = 0.26) without overfitting to outliers.

### Nonlinear Fee Response

- **Cubic toxicity**: Fee ∝ tox³ at high toxicity for superlinear arb deterrence
- **Trade-aligned boost**: Extra fee when trade direction matches spot−pHat divergence
- **Asymmetric directional fees**: Attract side (toward fair price) gets larger discount

See `contracts/src/SigmaAdaptiveStrategy.sol` for a complete implementation. All coefficients are named constants for easy grid-search tuning.

## Research

- [ANALYSIS.md](ANALYSIS.md) — Research methodology post-mortem: why we converged to 295 instead of 526
- [research/](research/) — Structured analysis of challenge mechanics, detection mechanisms, and parameter space
- [experiments/](experiments/) — Experiment scripts organized by research theme
- [contracts/README.md](contracts/README.md) — Categorization of all 33 strategy contracts
