# AMM Challenge - Mathematical Deep Dive

This document covers the mathematical foundations of the AMM challenge.

---

## 1. Constant Product AMM

The AMM uses the constant product formula:

```
x · y = k
```

Where:
- `x` = reserves of token X
- `y` = reserves of token Y
- `k` = constant product (invariant)

### Spot Price

The instantaneous price is the derivative of the bonding curve:

```
spot_price = y / x  (units: Y per X)
```

### Trade Mechanics (Sell X)

When the AMM sells Δx tokens of X:

```
New reserves: (x - Δx, y')
Constant product: (x - Δx) · y' = k

Therefore: y' = k / (x - Δx)

Trader pays: Δy = y' - y = k/(x - Δx) - y
```

---

## 2. Fee-on-Input Model

Fees are taken on the **input** side of the trade (Uniswap v2 style):

```
γ = 1 - f    (where f = fee rate, e.g., 0.003 for 30 bps)
```

Only `γ × input` affects reserves. The fee is extracted separately.

### Example: Trader Buys X (Spends Y)

```
Input: Δy_gross (Y from trader)
Net input: Δy_net = γ · Δy_gross

Reserve change: y → y + Δy_net
                x → k / (y + Δy_net)

X out: Δx = x - k/(y + Δy_net)

Fee collected: (1 - γ) · Δy_gross = f · Δy_gross
```

### Example: Trader Sells X (Receives Y)

```
Input: Δx_gross (X from trader)
Net input: Δx_net = γ · Δx_gross

Reserve change: x → x + Δx_net
                y → k / (x + Δx_net)

Y out: Δy = y - k/(x + Δx_net)

Fee collected: (1 - γ) · Δx_gross = f · Δx_gross
```

---

## 3. Price Process (GBM)

Fair price evolves via **Geometric Brownian Motion**:

```
S(t+1) = S(t) · exp(-σ²/2 + σZ)

Where: Z ~ N(0,1)
```

### Parameters

| Parameter | Range | Meaning |
|-----------|-------|---------|
| μ | 0 | Drift (no directional bias) |
| σ | 0.088% - 0.101% | Per-step volatility |
| S₀ | 100 | Starting price |

The `-σ²/2` term ensures the process is a martingale (no drift in expectation).

### Implications

- Price walks randomly with no predictable direction
- Volatility creates arbitrage opportunities
- Higher σ = more frequent arbs = more negative edge potential

---

## 4. Arbitrageur Optimal Trade Formulas

Arbitrageurs have perfect information (know fair price `p`). They compute optimal trades to maximize profit.

### Case 1: Spot < Fair (AMM Underprices X)

Arbitrageur **buys X from AMM** (AMM sells X).

```
Objective: max Δx · p - Y_paid

Where Y_paid = quote for buying Δx of X

Closed-form solution (from arbitrageur.rs:24-25):
────────────────────────────────────────────────
Δx_out = x - √(k / (γ · p))

Where:
  γ = 1 - f_ask  (ask fee applies when AMM sells X)
  k = x · y
  p = fair price
```

**Derivation:**

After arbitrageur buys Δx, new reserves are:
- x' = x - Δx
- y' = y + Y_paid

To maximize profit, take derivative and set to zero:
```
Profit = Δx · p - Y_paid
       = Δx · p - (y' - y)

Using constant product: y' = k/x' = k/(x - Δx)

Profit = Δx · p - k/(x - Δx) + y

dProfit/dΔx = p - k/(x - Δx)² = 0

Solving: (x - Δx)² = k/p
         x - Δx = √(k/p)
         Δx = x - √(k/p)

With fees: Δx = x - √(k/(γ·p))
```

### Case 2: Spot > Fair (AMM Overprices X)

Arbitrageur **sells X to AMM** (AMM buys X).

```
Objective: max Y_received - Δx · p

Where Y_received = quote for selling Δx of X

Closed-form solution (from arbitrageur.rs:103):
─────────────────────────────────────────────────
Δx_in = (√(k·γ/p) - x) / γ

Where:
  γ = 1 - f_bid  (bid fee applies when AMM buys X)
```

**Derivation:**

After arbitrageur sells Δx_gross, net input is γ·Δx:
- x' = x + γ·Δx
- y' = k/x' = k/(x + γ·Δx)

Y out: Δy = y - y' = y - k/(x + γ·Δx)

Profit = Δy - Δx·p
       = y - k/(x + γ·Δx) - Δx·p

dProfit/dΔx = γ·k/(x + γ·Δx)² - p = 0

Solving: (x + γ·Δx)² = γ·k/p
         x + γ·Δx = √(γ·k/p)
         Δx = (√(γ·k/p) - x) / γ
```

### No-Arbitrage Bands

After arbitrage, the spot price lands in a "no-arb band":

```
When arb buys X:  new_spot ≥ γ · p
When arb sells X: new_spot ≤ p / γ
```

Higher fees = wider band = AMM can stay "stale" longer = bad for edge.

---

## 5. Order Routing Split Formula

Retail orders split optimally across AMMs to **equalize marginal prices** post-trade.

### For Buying X (Spending Y)

Given total Y to spend, split between AMM1 and AMM2:

```
From router.rs:35-74:
─────────────────────

Define: Aᵢ = √(xᵢ · γᵢ · yᵢ)    (liquidity metric)
        r = A₁ / A₂

Optimal split to AMM1:
────────────────────────
Δy₁* = (r · (y₂ + γ₂ · Y) - y₁) / (γ₁ + r · γ₂)

Where:
  Y = total Y to spend
  γᵢ = 1 - fᵢ  (ask fee for AMM i)
  yᵢ = Y reserves of AMM i
```

### For Selling X (Receiving Y)

Given total X to sell, split between AMM1 and AMM2:

```
Define: Bᵢ = √(yᵢ · γᵢ · xᵢ)    (liquidity metric)
        r = B₁ / B₂

Optimal split to AMM1:
────────────────────────
Δx₁* = (r · (x₂ + γ₂ · X) - x₁) / (γ₁ + r · γ₂)

Where:
  X = total X to sell
  γᵢ = 1 - fᵢ  (bid fee for AMM i)
```

### Key Insight: Fee Sensitivity

The liquidity metric `A = √(x·γ·y)` shows that:

```
Lower fee → higher γ → higher A → more flow
```

The relationship is **nonlinear** through the square root. Small fee differences can shift significant volume.

**Example with equal reserves (100 X, 10000 Y):**

```
Your fee: 25 bps  →  γ₁ = 0.9975  →  A₁ = √(100 × 0.9975 × 10000) = 998.75
Normalizer: 30 bps  →  γ₂ = 0.9970  →  A₂ = √(100 × 0.9970 × 10000) = 998.50

r = 998.75 / 998.50 = 1.00025

For a 100 Y order:
Δy₁ = (1.00025 × (10000 + 0.997 × 100) - 10000) / (0.9975 + 1.00025 × 0.997)
    ≈ 50.6 Y

You get 50.6% of the order (vs 49.4% for normalizer)
```

A 5 bps fee advantage yields ~1.2% more volume.

---

## 6. Edge Calculation

Edge measures profit at fair price, separating skill from luck.

### Formula (from engine.rs:155-161)

```
For each trade on your AMM:

  If isBuy = true (you bought X, trader sold X to you):
      edge = amountX × fair_price - amountY

  If isBuy = false (you sold X, trader bought X from you):
      edge = amountY - amountX × fair_price
```

### Interpretation

```
When you SELL X:
  - You give: amountX (worth amountX × fair_price)
  - You get: amountY
  - Edge = amountY - amountX × fair_price

  If amountY > fair value → positive edge (you profit)
  If amountY < fair value → negative edge (you lose)

When you BUY X:
  - You give: amountY
  - You get: amountX (worth amountX × fair_price)
  - Edge = amountX × fair_price - amountY

  If fair value > amountY → positive edge (you profit)
  If fair value < amountY → negative edge (you lose)
```

### Sources of Edge

| Source | Edge Sign | Why |
|--------|-----------|-----|
| Retail buys X from you | Positive | They pay spread above fair |
| Retail sells X to you | Positive | They accept spread below fair |
| Arb buys X from you | Negative | They exploit your underpricing |
| Arb sells X to you | Negative | They exploit your overpricing |

### Total Edge

```
Total_Edge = Σ(Retail_Edges) + Σ(Arb_Edges)
           = Σ(Retail_Edges) - Σ(Arb_Profits)
           = Retail_Profits - Arb_Losses
```

---

## 7. Strategy Math

Your strategy sees `TradeInfo` after each trade:

```solidity
struct TradeInfo {
    bool isBuy;        // Did you buy X?
    uint256 amountX;   // X traded (WAD precision, 1e18)
    uint256 amountY;   // Y traded
    uint256 timestamp; // Step number
    uint256 reserveX;  // Post-trade X reserves
    uint256 reserveY;  // Post-trade Y reserves
}
```

### Common Metrics

**Trade Ratio (size relative to pool):**
```solidity
tradeRatio = wdiv(amountY, reserveY)  // in WAD

// Interpretation:
// < 0.004 (0.4%)  → tiny retail
// < 0.015 (1.5%)  → normal retail
// > 0.02-0.03     → likely arb
```

**Inventory Ratio (reserve balance):**
```solidity
ratio = wdiv(reserveX × 100, reserveY)  // should be ~WAD if balanced

// Interpretation:
// < 0.85 WAD → X depleted, raise ask fees
// > 1.15 WAD → X excess, raise bid fees
```

**EWMA (Exponential Weighted Moving Average):**
```solidity
// Update EWMA of trade ratios
ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA)

// If current trade >> ewma, it's anomalous (likely arb)
```

### Fixed-Point Math

All values use WAD (1e18) precision:

```solidity
WAD = 1e18                    // 1.0
BPS = 1e14                    // 0.01% (1 basis point)
30 * BPS = 3e15              // 0.30% (30 bps)

wmul(a, b) = a × b / WAD     // Multiply two WAD numbers
wdiv(a, b) = a × WAD / b     // Divide to get WAD result
```

---

## 8. Critical Equations Summary

```
┌────────────────────────────────────────────────────────────────────────┐
│  CONSTANT PRODUCT                                                      │
│  x · y = k                                                             │
│  spot_price = y / x                                                    │
├────────────────────────────────────────────────────────────────────────┤
│  FEE MODEL                                                             │
│  γ = 1 - f                                                             │
│  net_input = γ × gross_input                                           │
├────────────────────────────────────────────────────────────────────────┤
│  ARBITRAGE (AMM underpriced)                                           │
│  Δx_out = x - √(k / (γ · p))                                          │
│  profit = Δx × p - Y_paid                                              │
├────────────────────────────────────────────────────────────────────────┤
│  ARBITRAGE (AMM overpriced)                                            │
│  Δx_in = (√(k·γ/p) - x) / γ                                           │
│  profit = Y_received - Δx × p                                          │
├────────────────────────────────────────────────────────────────────────┤
│  ORDER ROUTING                                                         │
│  A = √(x · γ · y)                                                      │
│  Δy₁ = (r(y₂ + γ₂Y) - y₁) / (γ₁ + rγ₂)   where r = A₁/A₂             │
├────────────────────────────────────────────────────────────────────────┤
│  EDGE                                                                  │
│  sell_edge = amountY - amountX × fair_price                           │
│  buy_edge = amountX × fair_price - amountY                            │
│  total_edge = Σ(retail_edge) - Σ(arb_profit)                          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 9. File References

| File | Contents |
|------|----------|
| `amm_sim_rs/src/simulation/engine.rs:155-161` | Edge calculation |
| `amm_sim_rs/src/market/arbitrageur.rs:24-25` | Arb formulas |
| `amm_sim_rs/src/market/router.rs:35-75` | Routing split |
| `contracts/src/AMMStrategyBase.sol` | WAD math helpers |
