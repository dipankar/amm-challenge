# AMM Fee Strategy Challenge - Overview

**Target: Beat 522 Edge**
**Normalizer Baseline: 250-350 Edge**

---

## What Is This Challenge?

You design a **dynamic fee strategy** for a constant-product AMM (Automated Market Maker). Your strategy competes against a fixed-fee "normalizer" AMM for retail order flow.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      THE COMPETITION                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│    ┌───────────────────┐         ┌───────────────────┐              │
│    │   YOUR STRATEGY   │         │    NORMALIZER     │              │
│    │    (Dynamic Fees) │         │  (Fixed 30 bps)   │              │
│    │                   │         │                   │              │
│    │  Reserves: 100 X  │         │  Reserves: 100 X  │              │
│    │          10,000 Y │         │          10,000 Y │              │
│    └─────────┬─────────┘         └─────────┬─────────┘              │
│              │                             │                        │
│              └─────────────┬───────────────┘                        │
│                            │                                        │
│                   ┌────────▼────────┐                               │
│                   │  ORDER ROUTER   │                               │
│                   │ (Splits orders  │                               │
│                   │  optimally)     │                               │
│                   └────────┬────────┘                               │
│                            │                                        │
│              ┌─────────────┼─────────────┐                          │
│              │             │             │                          │
│       ┌──────▼──────┐ ┌────▼────┐ ┌──────▼──────┐                   │
│       │ ARBITRAGEUR │ │ RETAIL  │ │   PRICE     │                   │
│       │ (Informed)  │ │ TRADERS │ │   PROCESS   │                   │
│       │             │ │(Random) │ │    (GBM)    │                   │
│       └─────────────┘ └─────────┘ └─────────────┘                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## The Three Actors

### 1. Your AMM (The Submission)
- Constant-product market maker: `x * y = k`
- You control **bid fee** (when buying X) and **ask fee** (when selling X)
- Fees can change after every trade
- Start with 100 X and 10,000 Y (price = 100)

### 2. Normalizer AMM (The Benchmark)
- Identical mechanics, identical starting reserves
- Fixed **30 basis points** (0.30%) fee on both sides
- Never adapts - completely static
- Sets the competitive baseline

### 3. Market Participants

| Participant | Information | Behavior | Impact on You |
|-------------|-------------|----------|---------------|
| **Arbitrageur** | Knows fair price | Trades to extract profit when your price diverges | **Negative edge** |
| **Retail** | Uninformed | Random buy/sell, optimally routed | **Positive edge** |

---

## The Simulation Loop

Each simulation runs **10,000 steps**. Each step has 3 phases:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     ONE SIMULATION STEP                                   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════╗    │
│  ║  PHASE 1: PRICE MOVES                                            ║    │
│  ╠══════════════════════════════════════════════════════════════════╣    │
│  ║                                                                  ║    │
│  ║  Fair price evolves via Geometric Brownian Motion:               ║    │
│  ║                                                                  ║    │
│  ║    S(t+1) = S(t) × exp(-σ²/2 + σZ)    where Z ~ N(0,1)          ║    │
│  ║                                                                  ║    │
│  ║  • Drift μ = 0 (no directional bias - fair game)                ║    │
│  ║  • Volatility σ ~ U[0.088%, 0.101%] per step                    ║    │
│  ║  • Starting price = 100                                         ║    │
│  ║                                                                  ║    │
│  ║  NOTE: You CANNOT see the fair price!                           ║    │
│  ╚══════════════════════════════════════════════════════════════════╝    │
│                                                                          │
│                               │                                          │
│                               ▼                                          │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════╗    │
│  ║  PHASE 2: ARBITRAGEURS TRADE                                     ║    │
│  ╠══════════════════════════════════════════════════════════════════╣    │
│  ║                                                                  ║    │
│  ║  If AMM spot price ≠ fair price, arb extracts profit:           ║    │
│  ║                                                                  ║    │
│  ║  • Spot < Fair → Arb BUYS X from you (you sell cheap)           ║    │
│  ║  • Spot > Fair → Arb SELLS X to you (you buy expensive)         ║    │
│  ║                                                                  ║    │
│  ║  They use optimal trade sizes to maximize profit.               ║    │
│  ║  Higher fees = need bigger mispricing to profit.                ║    │
│  ║                                                                  ║    │
│  ║  THIS IS NEGATIVE EDGE - you lose to informed flow              ║    │
│  ╚══════════════════════════════════════════════════════════════════╝    │
│                                                                          │
│                               │                                          │
│                               ▼                                          │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════╗    │
│  ║  PHASE 3: RETAIL ORDERS ARRIVE                                   ║    │
│  ╠══════════════════════════════════════════════════════════════════╣    │
│  ║                                                                  ║    │
│  ║  Random uninformed traders arrive:                               ║    │
│  ║  • Arrival rate λ ~ U[0.6, 1.0] orders per step (Poisson)       ║    │
│  ║  • Order size ~ LogNormal, mean ~ U[19, 21] in Y terms          ║    │
│  ║  • Direction: 50% buy, 50% sell                                 ║    │
│  ║                                                                  ║    │
│  ║  Orders SPLIT optimally between your AMM and normalizer:        ║    │
│  ║  • Lower fees → more volume routed to you                       ║    │
│  ║  • Nonlinear: small fee drop can shift huge volume              ║    │
│  ║                                                                  ║    │
│  ║  THIS IS POSITIVE EDGE - you profit from the spread             ║    │
│  ╚══════════════════════════════════════════════════════════════════╝    │
│                                                                          │
│                               │                                          │
│                               ▼                                          │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════════╗    │
│  ║  YOUR STRATEGY CALLED: afterSwap(TradeInfo)                      ║    │
│  ╠══════════════════════════════════════════════════════════════════╣    │
│  ║                                                                  ║    │
│  ║  After each trade that hits YOUR AMM, you see:                  ║    │
│  ║  • isBuy: did you buy X (trader sold) or sell X?                ║    │
│  ║  • amountX, amountY: trade amounts                              ║    │
│  ║  • timestamp: current step number                               ║    │
│  ║  • reserveX, reserveY: post-trade reserves                      ║    │
│  ║                                                                  ║    │
│  ║  You return: (newBidFee, newAskFee)                             ║    │
│  ╚══════════════════════════════════════════════════════════════════╝    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## What Is Edge?

**Edge** is the scoring metric. It measures profitability using the fair price at trade time.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          EDGE FORMULA                                     │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   For each trade your AMM executes:                                      │
│                                                                          │
│   ┌────────────────────────────────────────────────────────────────┐     │
│   │                                                                │     │
│   │  When you SELL X (isBuy = false):                             │     │
│   │    Trade Edge = amountY - amountX × fair_price                │     │
│   │                                                                │     │
│   │  When you BUY X (isBuy = true):                               │     │
│   │    Trade Edge = amountX × fair_price - amountY                │     │
│   │                                                                │     │
│   └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│   Total Edge = Σ(all trade edges)                                        │
│                                                                          │
│   ───────────────────────────────────────────────────────────────────    │
│                                                                          │
│   INTERPRETATION:                                                        │
│                                                                          │
│   • Retail trades → Positive edge (you charge spread)                   │
│   • Arb trades → Negative edge (they extract profit)                    │
│                                                                          │
│   Edge = Retail_Profits - Arb_Losses                                     │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Why Edge, Not PnL?

Edge is "honest" - it measures skill independent of price movements:
- **PnL** includes gains/losses from price changes (luck)
- **Edge** only counts what you captured from the spread (skill)

---

## Why the Normalizer?

Without competition, you could set 10% fees and look profitable (huge spread on few trades). The normalizer prevents this:

```
                     FEE vs RETAIL FLOW

    Your    │
    Share   │
    of      │    ●
    Retail  │       ●
            │          ●
            │             ●
            │                ●
            │                   ●───────────
            │                      (zero flow)
            └────────────────────────────────► Your Fee
                 25    30    50    80   100+
                       ▲
                       │
                  Normalizer
                  gets all
                  retail here
```

If your fees are higher than 30 bps, retail routes to the normalizer. You get nothing.

---

## What You Can and Cannot See

| You CAN See | You CANNOT See |
|-------------|----------------|
| Trade that just hit your AMM (size, direction) | Fair price |
| Your current reserves | Normalizer's state |
| Timestamp (step number) | Future retail flow |
| Historical trades (via storage) | Whether trade was arb or retail |

This information asymmetry is the core challenge. You must **infer** market conditions from limited observations.

---

## Competition Setup

| Parameter | Value |
|-----------|-------|
| Initial X reserves | 100 |
| Initial Y reserves | 10,000 |
| Starting price | 100 (Y per X) |
| k (constant product) | 1,000,000 |
| Steps per simulation | 10,000 |
| Simulations per run | 1,000 (default) |
| Max fee | 10% (1000 bps) |
| WAD precision | 1e18 |
| BPS unit | 1e14 (0.01%) |

### Variance Across Simulations

Each of 1000 simulations uses different parameters:
- **Volatility σ**: 0.088% - 0.101%
- **Retail arrival λ**: 0.6 - 1.0 per step
- **Retail order size mean**: 19-21 Y

This tests **robustness** - your strategy must work across market conditions.

---

## Strategy Interface

Your strategy must implement:

```solidity
contract Strategy is AMMStrategyBase {

    // Called once at simulation start
    function afterInitialize(uint256 initialX, uint256 initialY)
        external returns (uint256 bidFee, uint256 askFee);

    // Called after every trade
    function afterSwap(TradeInfo calldata trade)
        external returns (uint256 bidFee, uint256 askFee);

    function getName() external pure returns (string memory);
}
```

### TradeInfo Structure

```solidity
struct TradeInfo {
    bool isBuy;        // true = you bought X (trader sold X to you)
    uint256 amountX;   // X traded (WAD precision)
    uint256 amountY;   // Y traded
    uint256 timestamp; // Step number
    uint256 reserveX;  // Your post-trade X reserves
    uint256 reserveY;  // Your post-trade Y reserves
}
```

### Available Resources

- **32 storage slots** (`slots[0..31]`) for state persistence
- **Helper functions**: `wmul`, `wdiv`, `sqrt`, `clampFee`, `bpsToWad`
- **Constants**: `WAD`, `BPS`, `MAX_FEE`

---

## The Core Insight

> "We compete FOR retail, not against arb"
> - WinningV2 Strategy comment

You make money from **steady retail flow**, not from beating arbitrageurs. The key is:

1. **Undercut normalizer** to capture retail (base fee < 30 bps)
2. **Spike after arbs** to protect reserves temporarily
3. **Decay quickly** back to competitive to resume capturing retail

This balance between retail capture and arb protection is what separates good strategies from great ones.

---

## File References

| File | Purpose |
|------|---------|
| `contracts/src/AMMStrategyBase.sol` | Base class with helpers |
| `contracts/src/StarterStrategy.sol` | Simple 50 bps example |
| `README.md` | Official challenge description |
| `amm_sim_rs/src/simulation/engine.rs` | Rust simulation engine |
| `amm_competition/cli.py` | CLI for running simulations |
