# Strategy Analysis

This document analyzes existing strategies in the codebase, comparing their approaches and understanding what makes some more successful than others.

---

## 1. Strategy Inventory

### By Philosophy

| Category | Strategies | Core Idea |
|----------|------------|-----------|
| **Static** | Vanilla (30 bps), Starter (50 bps), Low25bps, Static80bps, Best78bps | Fixed fees, no adaptation |
| **Winning Family** | WinningV1-V5 | Undercut + protect, fast decay |
| **MaxEdge Family** | MaxEdge, MaxEdgeV1, V2, Final | High base, extreme protection |
| **Hybrid/Regime** | Hybrid, Regime, RegimeV2 | Mode switching |
| **Aggressive** | Aggressive, GreedyEdge | Ultra-low base for retail |
| **Defensive** | Defensive, SmartAsymmetric | Conservative arb protection |

---

## 2. Parameter Comparison Table

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                        STRATEGY PARAMETER COMPARISON                                │
├──────────────┬─────────┬───────────┬───────────┬──────────┬─────────┬─────────────┤
│ Strategy     │ BASE_FEE│POST_ARB   │ARB_THRESH │DECAY/STEP│ALPHA    │ RETAIL_FEE  │
├──────────────┼─────────┼───────────┼───────────┼──────────┼─────────┼─────────────┤
│ Normalizer   │ 30 bps  │ N/A       │ N/A       │ N/A      │ N/A     │ N/A         │
├──────────────┼─────────┼───────────┼───────────┼──────────┼─────────┼─────────────┤
│ WinningV1    │ 25 bps  │ 55 bps    │ 4.0%      │ 3 bps    │ 5%      │ 20 bps      │
│ WinningV2    │ 25 bps  │ 38 bps    │ 3.3%      │ 3 bps    │ N/A     │ N/A         │
│ WinningV3    │ 26 bps  │ 45 bps    │ 2.5%      │ 4 bps    │ 10%     │ 24 bps*     │
│ WinningV4    │ 27 bps  │ 55 bps    │ 2.0%      │ 5 bps    │ 12.5%   │ 22 bps      │
│ WinningV5    │ 24 bps  │ 65 bps    │ 2.0%      │ 7 bps    │ 16.7%   │ 20 bps      │
├──────────────┼─────────┼───────────┼───────────┼──────────┼─────────┼─────────────┤
│ MaxEdgeFinal │ 55 bps  │ 125 bps   │ 3.3%      │ 27 bps   │ 12.5%   │ 52 bps*     │
├──────────────┼─────────┼───────────┼───────────┼──────────┼─────────┼─────────────┤
│ Aggressive   │ 18 bps  │ ~40 bps   │ varies    │ varies   │ varies  │ 18 bps      │
│ GreedyEdge   │ 60 bps  │ 400 bps   │ tiered    │ N/A      │ N/A     │ 60 bps      │
└──────────────┴─────────┴───────────┴───────────┴──────────┴─────────┴─────────────┘

* Derived from code (BASE_FEE - X bps in certain conditions)
```

---

## 3. Winning Strategy Evolution

The Winning family shows iterative refinement:

### V1 (Original Multi-Signal)

```solidity
// contracts/src/WinningStrategy.sol

BASE_FEE = 25 * BPS;         // Undercut normalizer
LOW_VOL_FEE = 20 * BPS;      // Even lower in calm markets
HIGH_VOL_FEE = 40 * BPS;     // Higher in volatile markets
POST_ARB_SPIKE = 55 * BPS;   // After large trades
LARGE_TRADE_THRESHOLD = WAD / 25;  // 4% = arb

// Features:
// - EWMA volatility tracking
// - Consecutive trade detection (momentum)
// - Inventory imbalance multiplier (1.2x)
// - Time decay to base fee
```

**Philosophy:** Multi-signal approach with volatility regime switching.

### V2 (Simplified + Focus on Retail)

```solidity
// contracts/src/WinningV2Strategy.sol

BASE_FEE = 25 * BPS;
POST_ARB_FEE = 38 * BPS;     // Lower spike (stay competitive)
ARB_THRESHOLD = WAD / 30;     // 3.3%
DECAY_PER_STEP = 3 * BPS;

// Comment insight:
// "Key insight: we compete FOR retail, not against arb"
```

**Philosophy:** Simpler is better. Focus on retail capture, modest arb protection.

### V3 (More Aggressive Detection)

```solidity
// contracts/src/WinningV3Strategy.sol

BASE_FEE = 26 * BPS;          // Slightly higher base
POST_ARB_FEE = 45 * BPS;      // Moderate spike
ARB_THRESHOLD = WAD / 40;     // 2.5% (more sensitive)
DECAY_PER_STEP = 4 * BPS;     // Faster decay

// Additions:
// - EWMA with α = 10%
// - Retail discount to 24 bps
// - Inventory protection at 80%/120%
```

**Philosophy:** Tighter arb detection, explicit retail discount.

### V4 (Track Arb Frequency)

```solidity
// contracts/src/WinningV4Strategy.sol

BASE_FEE = 27 * BPS;          // Higher base
POST_ARB_FEE = 55 * BPS;      // Higher spike
ARB_THRESHOLD = WAD / 50;     // 2% (very sensitive)
DECAY_PER_STEP = 5 * BPS;     // Faster decay
RETAIL_FEE = 22 * BPS;        // Ultra-competitive

// New features:
// - Track arb count vs total count
// - If >25% arbs, raise base to 28 bps
// - Asymmetric +12 bps on hit side
// - Inventory protection at 75%/125%
```

**Philosophy:** Adaptive base fee based on arb frequency.

### V5 (Maximum Margin)

```solidity
// contracts/src/WinningV5Strategy.sol

BASE_FEE = 24 * BPS;          // Lowest base
POST_ARB_FEE = 65 * BPS;      // Highest spike
ARB_THRESHOLD = WAD / 50;     // 2%
DECAY_PER_STEP = 7 * BPS;     // Fastest decay
RETAIL_FEE = 20 * BPS;        // Lowest for tiny trades

// Features:
// - Fast EWMA (α = 1/6 ≈ 16.7%)
// - Retail detection at <0.4% trade ratio
// - Strong asymmetric protection (+15 bps)
// - Inventory protection at 70%/130%
```

**Philosophy:** Extreme parameters - lowest base, highest spike, fastest decay.

### Evolution Summary

```
V1 → V2: Simplify, lower spike (55→38)
V2 → V3: Tighten arb detection (3.3%→2.5%), add EWMA
V3 → V4: Track arb frequency, adaptive base, very sensitive (2%)
V4 → V5: Extreme parameters (24/65/7bps), fastest decay
```

---

## 4. Why Winning Strategies Work

### Core Insight

> "We compete FOR retail, not against arb"

This is the fundamental realization. Key implications:

1. **Base fee must beat normalizer** to capture retail flow
2. **Arb losses are unavoidable** but bounded
3. **Volume compounds** - small fee advantage → significant volume edge
4. **Fast recovery** after arbs is crucial to resume retail capture

### Mathematical Advantage

At 25 bps vs 30 bps (normalizer):

```
Your γ = 0.9975, Normalizer γ = 0.9970

For equal reserves:
A_you = √(100 × 0.9975 × 10000) = 998.75
A_norm = √(100 × 0.9970 × 10000) = 998.50

r = 1.00025

For 100 Y order, you get ~50.6% vs 49.4%
```

Small fee advantage = meaningful volume advantage.

### Spike + Decay Pattern

```
Fee │
    │   ┌─── 65 bps (spike)
    │   │
    │   │╲
    │   │ ╲       ← 7 bps/step decay
    │   │  ╲
    │───┴───╲──── 24 bps (base)
    │
    └────────────► Time (steps)
         5 steps

After spike, decay to base in: (65-24)/7 ≈ 6 steps
During those 6 steps: normalizer attracts retail
After decay: you're competitive again
```

The faster the decay, the less retail you lose to the normalizer.

---

## 5. Why MaxEdge Approaches Fail

### MaxEdgeFinal Parameters

```solidity
BASE_FEE = 55 * BPS;      // 25 bps ABOVE normalizer
POST_ARB_FEE = 125 * BPS; // 1.25%
DECAY_PER_STEP = 27 * BPS;
```

### The Problem

```
At 55 bps vs 30 bps normalizer:

Your γ = 0.9945, Normalizer γ = 0.9970

A_you = √(100 × 0.9945 × 10000) = 997.25
A_norm = √(100 × 0.9970 × 10000) = 998.50

r = 0.9987  (< 1!)

For 100 Y order:
Δy_you = (0.9987 × (10000 + 0.997 × 100) - 10000) / (0.9945 + 0.9987 × 0.997)
       ≈ 49.3 Y

You get less than half! (~49.3% vs 50.7%)
```

With 55 bps, you're **losing** the retail competition.

### Why It Seems Logical But Fails

```
MaxEdge Thinking:
"High fees → high edge per trade → maximize edge"

Reality:
High fees → lose retail to normalizer → near-zero volume → near-zero edge
```

The 55 bps strategy might capture more edge **per trade**, but it executes **far fewer trades**.

### GreedyEdge is Even Worse

```solidity
// 3-tier system
if (large trade) fee = 400 bps;      // 4%!
else if (medium) fee = 150 bps;
else fee = 60 bps;                   // Still 2x normalizer
```

60 bps base = no retail. 400 bps spike = irrelevant (no trades to spike on).

---

## 6. Patterns and Anti-Patterns

### Winning Patterns

| Pattern | Implementation | Why It Works |
|---------|---------------|--------------|
| **Undercut Base** | 24-27 bps vs 30 | Capture retail flow |
| **Quick Spike** | 45-65 bps post-arb | Brief protection |
| **Fast Decay** | 5-7 bps/step | Return to competitive ASAP |
| **Asymmetric** | +12-15 bps on hit side | Protect direction |
| **Retail Discount** | 20-22 bps for tiny trades | Maximize small orders |
| **EWMA Smoothing** | α = 10-17% | Avoid overreaction |

### Anti-Patterns

| Anti-Pattern | Example | Why It Fails |
|--------------|---------|--------------|
| **High Base** | 55+ bps | Lose retail to normalizer |
| **Extreme Spike** | 125+ bps | Doesn't help if no trades |
| **Slow Decay** | <3 bps/step | Lose too much retail during recovery |
| **No Adaptation** | Static 50 bps | Can't protect against arbs OR compete |
| **Overtriggering** | <1% threshold | Flag retail as arb |

---

## 7. Component Analysis

### Arb Detection Methods

**1. Absolute Threshold**
```solidity
tradeRatio > WAD / 50  // >2%
```
Simple but effective. Most retail trades are <1%.

**2. EWMA Relative**
```solidity
tradeRatio > ewma * 4  // 4x recent average
```
Adapts to market conditions. Catches outliers.

**3. Combined**
```solidity
bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;
```
Belt and suspenders - catches both types.

### Time Decay Implementations

**Linear Decay (Most Common)**
```solidity
if (steps > 0 && steps < 30) {
    uint256 decay = steps * DECAY_PER_STEP;
    bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
}
```

**Max Steps Cap**
```solidity
if (steps > 0 && steps < 30)  // Cap at 30 steps
```
Prevents overflow on large gaps.

### Inventory Protection

```solidity
uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);

if (ratio < WAD * 75 / 100) {     // X depleted (<75%)
    askFee = clampFee(askFee + 15 * BPS);
} else if (ratio > WAD * 125 / 100) {  // X excess (>125%)
    bidFee = clampFee(bidFee + 15 * BPS);
}
```

Protects the depleted side to prevent cascade.

---

## 8. Strategy Complexity vs Performance

```
    Performance
    (Edge)
    ▲
    │           WinningV4●
    │                WinningV3●  WinningV5●
    │            WinningV2●
    │                       ●WinningV1
    │
    │     Static25●
    │
    │  Static30●(normalizer)
    │
    │                               ●MaxEdgeFinal
    │
    │  Static50●
    │
    └────────────────────────────────────────► Complexity
         Simple         Medium         Complex
```

The Winning strategies hit a sweet spot: **enough complexity to adapt, but not overthinking**.

---

## 9. Code Snippets: Key Patterns

### Minimal Winning Core

```solidity
function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
    uint256 fee = slots[0];
    uint256 lastTs = slots[1];

    // Decay toward base
    uint256 steps = trade.timestamp - lastTs;
    if (steps > 0 && fee > BASE_FEE) {
        fee = fee > BASE_FEE + steps * DECAY ? fee - steps * DECAY : BASE_FEE;
    }
    slots[1] = trade.timestamp;

    // Arb detection
    if (wdiv(trade.amountY, trade.reserveY) > ARB_THRESHOLD) {
        fee = POST_ARB_FEE;
    }

    slots[0] = fee;
    return (fee, fee);
}
```

This minimal version captures the essence: **decay + spike**.

### Full-Featured Pattern

```solidity
function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
    uint256 bidFee = slots[SLOT_BID_FEE];
    uint256 askFee = slots[SLOT_ASK_FEE];
    uint256 ewma = slots[SLOT_EWMA];

    uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

    // 1. Update EWMA
    ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);

    // 2. Time decay
    // (decay both fees toward base)

    // 3. Arb detection
    bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 4;

    if (isArb) {
        bidFee = POST_ARB_FEE;
        askFee = POST_ARB_FEE;
        // Asymmetric on hit side
        if (trade.isBuy) bidFee += EXTRA;
        else askFee += EXTRA;
    } else if (tradeRatio < RETAIL_THRESHOLD) {
        // Retail discount
        bidFee = RETAIL_FEE;
        askFee = RETAIL_FEE;
    }

    // 4. Inventory protection
    // (raise fee on depleted side)

    return (bidFee, askFee);
}
```

---

## 10. Key Takeaways

1. **Undercut the normalizer** - 24-27 bps beats 30 bps for retail
2. **Spike + decay** - Brief protection, fast recovery
3. **Asymmetric protection** - Protect the hit direction
4. **Don't overthink arb** - You'll never avoid it entirely
5. **Retail discount** - Tiny trades are definitely retail
6. **Avoid high base** - >30 bps loses the retail game
7. **Fast decay** - 5-7 bps/step gets you competitive quickly

---

## File References

| File | Purpose |
|------|---------|
| `contracts/src/WinningStrategy.sol` | V1 multi-signal |
| `contracts/src/WinningV2Strategy.sol` | V2 simplified |
| `contracts/src/WinningV3Strategy.sol` | V3 tighter detection |
| `contracts/src/WinningV4Strategy.sol` | V4 arb frequency |
| `contracts/src/WinningV5Strategy.sol` | V5 extreme params |
| `contracts/src/MaxEdgeFinalStrategy.sol` | High-fee failure case |
