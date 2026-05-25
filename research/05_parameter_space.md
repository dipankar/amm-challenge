# Parameter Space Analysis

This document maps the parameter space for AMM fee strategies and identifies optimal regions.

---

## 1. Parameter Overview

Every adaptive strategy has these key parameters:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           PARAMETER CATEGORIES                                  │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  FEES                  │ DETECTION              │ DYNAMICS                    │
│  ──────────────────────┼────────────────────────┼───────────────────────────  │
│  BASE_FEE              │ ARB_THRESHOLD          │ DECAY_PER_STEP              │
│  POST_ARB_FEE          │ EWMA_ALPHA             │ MAX_DECAY_STEPS             │
│  RETAIL_FEE            │ RETAIL_THRESHOLD       │ CONSEC_ADJUST               │
│  ASYMMETRIC_EXTRA      │ EWMA_MULTIPLIER        │                             │
│                        │ INVENTORY_THRESHOLDS   │                             │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Base Fee (BASE_FEE)

The default fee when not spiking. Critical for retail capture.

### Range Analysis

```
    Retail   │
    Volume   │
    Share    │
             │  ●●●●●●●●●●
      60% ───┼──────────●●●●●●
             │                ●●●●
      50% ───┼─────────────────────●●●●
             │                         ●●●
      40% ───┼────────────────────────────●●●
             │                               ●●●
             └────────────────────────────────────► Base Fee
                 20    25    30    35    40    50  (bps)
                       ▲     ▲
                       │     │
              Winning  │     Normalizer
              Strategies
```

### Optimal Zone: 24-27 bps

| Fee | vs Normalizer | Retail Share | Risk |
|-----|---------------|--------------|------|
| 20 bps | -10 bps | ~54% | Higher arb exposure |
| 24 bps | -6 bps | ~52% | **Sweet spot (V5)** |
| 25 bps | -5 bps | ~51% | **Classic (V1, V2)** |
| 27 bps | -3 bps | ~50.3% | **Safer (V4)** |
| 30 bps | 0 | 50% | Neutral |
| 35 bps | +5 bps | ~48% | Losing retail |

### Code Examples

```solidity
// Aggressive retail capture
uint256 constant BASE_FEE = 24 * BPS;  // WinningV5

// Balanced
uint256 constant BASE_FEE = 25 * BPS;  // WinningV1, V2

// Conservative
uint256 constant BASE_FEE = 27 * BPS;  // WinningV4

// Too high (anti-pattern)
uint256 constant BASE_FEE = 55 * BPS;  // MaxEdgeFinal - loses retail
```

---

## 3. Post-Arb Fee (POST_ARB_FEE)

The spike fee after detecting arbitrage.

### Range Analysis

```
    Arb        │
    Protection │
    (relative) │
               │                     ●
        MAX ───┼─────────────────────●──
               │                   ●
               │                 ●
               │               ●
    MODERATE ──┼──────────●────────────
               │       ●
               │     ●
    MINIMAL ───┼───●───────────────────
               │
               └───────────────────────► Post-Arb Fee
                   38   45   55   65   125  (bps)
```

### Optimal Zone: 45-65 bps

| Fee | Protection Level | Trade-off |
|-----|------------------|-----------|
| 38 bps | Light | Fast recovery, less protection |
| 45 bps | Moderate | **Balanced (V3)** |
| 55 bps | Good | **Standard (V1, V4)** |
| 65 bps | Strong | **Aggressive (V5)** |
| 125 bps | Extreme | Overkill, loses retail during spike |

### Key Insight

```
Spike height matters less than spike duration.

Why:
- During spike, normalizer gets ALL retail
- A 65 bps spike for 6 steps ≈ 125 bps spike for 3 steps
  (in terms of total retail lost)

Prefer: Moderate spike + fast decay
```

---

## 4. Decay Rate (DECAY_PER_STEP)

How fast fees return to base after spiking.

### Recovery Time Calculation

```
Steps to recover = (POST_ARB_FEE - BASE_FEE) / DECAY_PER_STEP

Example (WinningV5):
  (65 - 24) / 7 = ~6 steps

Example (WinningV2):
  (38 - 25) / 3 = ~4 steps

Example (MaxEdgeFinal):
  (125 - 55) / 27 = ~3 steps
```

### Range Analysis

```
    Recovery  │
    Steps     │
              │
       15  ───┼───●  (too slow - lose retail)
              │
       10  ───┼──────●
              │
        5  ───┼─────────●──●──●  (optimal zone)
              │
        2  ───┼────────────────●  (too fast - no protection)
              │
              └───────────────────► Decay (bps/step)
                  3    5    7    27
```

### Optimal Zone: 5-7 bps/step

| Decay | Recovery (65→25 bps) | Trade-off |
|-------|---------------------|-----------|
| 3 bps | ~13 steps | Slow - lose retail during recovery |
| 4 bps | ~10 steps | Moderate |
| 5 bps | ~8 steps | **Good (V4)** |
| 7 bps | ~6 steps | **Fast (V5)** |
| 27 bps | ~2 steps | Too fast - barely protected |

---

## 5. Arb Threshold (ARB_THRESHOLD)

Trade ratio above which we classify as arb.

### Distribution of Trade Sizes

```
    Frequency │
              │
              │ ████  Retail (0.1-1%)
              │ ████████
              │ ████████████
              │ ████████████████
              │ ████████████████████
              │ ██████████████████████ ██
              │ ██████████████████████ ████  Arb (2-5%)
              └─────────────────────────────────► Trade Ratio
                 0.5%   1%   1.5%   2%   3%   4%   5%
                                    ▲
                                    │
                              Typical threshold
```

### Sensitivity Trade-off

| Threshold | Classification | Risk |
|-----------|----------------|------|
| 1.5% | Very sensitive | False positives (spike on large retail) |
| 2.0% | Sensitive | **Good detection (V4, V5)** |
| 2.5% | Balanced | **Safe default (V3)** |
| 3.3% | Moderate | **Conservative (V2)** |
| 4.0% | Conservative | Miss some arbs |

### Code Examples

```solidity
// Sensitive (may flag large retail)
uint256 constant ARB_THRESHOLD = WAD / 50;  // 2.0%

// Balanced
uint256 constant ARB_THRESHOLD = WAD / 40;  // 2.5%

// Conservative
uint256 constant ARB_THRESHOLD = WAD / 30;  // 3.3%

// Very conservative
uint256 constant ARB_THRESHOLD = WAD / 25;  // 4.0%
```

---

## 6. EWMA Alpha

Smoothing factor for trade size average.

### Responsiveness Trade-off

```
    Adaptation │
    Speed      │
               │
      FAST  ───┼──────────────────────●  (noisy but adaptive)
               │                   ●
               │              ●
               │         ●
      SLOW  ───┼────●──────────────────  (stable but slow)
               │
               └───────────────────────► Alpha
                   5%   10%   12.5%  16.7%
                        ▲            ▲
                        │            │
                      V3           V5
```

### Optimal Zone: 10-17%

| Alpha | Half-life | Use Case |
|-------|-----------|----------|
| 5% | ~14 trades | Very stable baseline |
| 10% | ~7 trades | **Balanced (V3)** |
| 12.5% | ~5 trades | **Responsive (MaxEdge)** |
| 16.7% | ~4 trades | **Fast adaptation (V5)** |

---

## 7. Asymmetric Extra

Additional fee on the side that was just hit.

### Range Analysis

| Extra | Effect | Strategy |
|-------|--------|----------|
| 5 bps | Light asymmetry | V2 |
| 8 bps | Moderate | V3 |
| 12 bps | Strong | V4 |
| 15 bps | Aggressive | V5 |
| 20 bps | Maximum | MaxEdgeFinal |

### Why Asymmetry Works

```
Scenario: Price just dropped (you bought X / arb sold X to you)

Without asymmetry:
  BID = 55 bps, ASK = 55 bps
  If price continues down, arb can sell more X to you

With asymmetry (+15 bps on BID):
  BID = 70 bps, ASK = 55 bps
  Arb needs 15 bps MORE mispricing to profit on BID side
  Gives price time to stabilize
```

---

## 8. Inventory Thresholds

When to start protecting reserves.

### Threshold Comparison

```
    Fee         │
    Increase    │
                │
      +15 bps ──┼──●────────────────────────●──  V5 bounds
                │     ●                  ●
      +12 bps ──┼────────●────────────●────────  V4 bounds
                │           ●      ●
       +8 bps ──┼──────────────●●──────────────  V3 bounds
                │
                └──────────────────────────────► Reserve Ratio
                  70%   75%  80%   1.0   120%  125%  130%
                        ▲                       ▲
                   X depleted              X excess
```

### Optimal Bounds

| Style | Low Bound | High Bound | Extra Fee |
|-------|-----------|------------|-----------|
| Loose | 85% | 115% | +8 bps |
| Moderate | 75-80% | 120-125% | +12-15 bps |
| Tight | 70% | 130% | +15 bps |

---

## 9. Retail Fee (RETAIL_FEE)

Ultra-low fee for confirmed retail trades.

### When to Apply

```solidity
// WinningV4: <0.5% trade ratio
if (tradeRatio < WAD / 200) {
    bidFee = RETAIL_FEE;  // 22 bps
    askFee = RETAIL_FEE;
}

// WinningV5: <0.4% trade ratio
if (tradeRatio < WAD / 250) {
    bidFee = RETAIL_FEE;  // 20 bps
    askFee = RETAIL_FEE;
}
```

### Optimal Values

| Retail Fee | Retail Share Boost | Risk |
|------------|-------------------|------|
| 18 bps | +4-5% | Aggressive, may lose edge per trade |
| 20 bps | +3-4% | **Good (V5)** |
| 22 bps | +2-3% | **Safe (V4)** |
| 24 bps | +1-2% | Conservative |

---

## 10. Parameter Interaction Matrix

Parameters don't exist in isolation. Key interactions:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                       PARAMETER INTERACTIONS                                    │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  BASE_FEE ←→ POST_ARB_FEE                                                      │
│  • Bigger gap = more protection but slower recovery                            │
│  • Ideal gap: 30-40 bps (e.g., 25→65)                                          │
│                                                                                │
│  POST_ARB_FEE ←→ DECAY_PER_STEP                                                │
│  • Higher spike needs faster decay to maintain competitiveness                 │
│  • Recovery time = gap / decay should be 5-8 steps                            │
│                                                                                │
│  ARB_THRESHOLD ←→ EWMA_ALPHA                                                   │
│  • Sensitive threshold (2%) needs stable EWMA (lower alpha)                   │
│  • Conservative threshold (4%) can use responsive EWMA (higher alpha)          │
│                                                                                │
│  BASE_FEE ←→ RETAIL_FEE                                                        │
│  • Retail fee should be 2-5 bps below base                                    │
│  • Too big gap: waste edge on retail you'd win anyway                         │
│                                                                                │
│  ASYMMETRIC_EXTRA ←→ POST_ARB_FEE                                              │
│  • Together determine spike on hit side: POST_ARB + ASYMMETRIC               │
│  • Total shouldn't exceed ~80 bps or normalizer wins too much                 │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Pareto Frontier

There's no single optimal point - there are trade-offs:

```
    Arb Protection
    (lower arb losses)
    ▲
    │      ●V5 (24/65/7)
    │     ●
    │    ●      Pareto Frontier
    │   ●          (optimal trade-offs)
    │  ●V4 (27/55/5)
    │ ●
    │●V3 (26/45/4)
    │ ●V2 (25/38/3)
    │
    │                    ●MaxEdge (55/125/27)
    │                      (dominated - loses both)
    │
    └──────────────────────────────────────────► Retail Capture
                                        (higher retail edge)
```

### Winning Configurations

| Strategy | Edge Composition |
|----------|------------------|
| V2 | More retail, more arb losses |
| V5 | Less retail, less arb losses |

Both can achieve similar total edge with different profiles.

---

## 12. Configuration Recipes

### Recipe 1: Aggressive Retail (V5-style)

```solidity
BASE_FEE = 24 * BPS;
POST_ARB_FEE = 65 * BPS;
ARB_THRESHOLD = WAD / 50;  // 2%
DECAY_PER_STEP = 7 * BPS;
RETAIL_FEE = 20 * BPS;
EWMA_ALPHA = WAD / 6;      // 16.7%
ASYMMETRIC = 15 * BPS;
```

**Philosophy:** Maximize retail capture, rely on fast decay for protection.

### Recipe 2: Balanced (V3-style)

```solidity
BASE_FEE = 26 * BPS;
POST_ARB_FEE = 45 * BPS;
ARB_THRESHOLD = WAD / 40;  // 2.5%
DECAY_PER_STEP = 4 * BPS;
RETAIL_FEE = 24 * BPS;
EWMA_ALPHA = WAD / 10;     // 10%
ASYMMETRIC = 8 * BPS;
```

**Philosophy:** Middle ground on all parameters.

### Recipe 3: Defensive (Conservative)

```solidity
BASE_FEE = 28 * BPS;
POST_ARB_FEE = 55 * BPS;
ARB_THRESHOLD = WAD / 30;  // 3.3%
DECAY_PER_STEP = 3 * BPS;
RETAIL_FEE = 26 * BPS;
EWMA_ALPHA = WAD / 12;     // 8%
ASYMMETRIC = 10 * BPS;
```

**Philosophy:** Prioritize arb protection, accept less retail.

---

## 13. Unexplored Regions

Parameters not well-tested in existing strategies:

### Non-Linear Decay

```solidity
// Instead of: fee -= DECAY * steps
// Try: fee *= DECAY_FACTOR^steps
// Or: fee = BASE + (spike - BASE) / (1 + steps/HALF_LIFE)
```

### Dynamic Alpha

```solidity
// Increase alpha during high volatility
if (tradeRatio > ewma * 2) {
    alpha = 0.25;  // Fast adaptation
} else {
    alpha = 0.10;  // Stable baseline
}
```

### Context-Aware Spikes

```solidity
// Higher spike if inventory already stressed
if (ratio < 0.8 && !trade.isBuy) {
    spike += 10 * BPS;  // Extra protection
}
```

### Trade Timing

```solidity
// Faster decay if no trades for many steps
if (steps > 10) {
    decay = DECAY_PER_STEP * 2;  // Double decay
}
```

---

## 14. Summary: Recommended Ranges

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                      RECOMMENDED PARAMETER RANGES                               │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Parameter            │ Optimal Range      │ Sweet Spot                       │
│  ─────────────────────┼────────────────────┼────────────────────────────────  │
│  BASE_FEE             │ 24-27 bps          │ 25 bps                           │
│  POST_ARB_FEE         │ 45-65 bps          │ 55 bps                           │
│  DECAY_PER_STEP       │ 5-7 bps            │ 6 bps                            │
│  ARB_THRESHOLD        │ 2.0-3.0%           │ 2.5%                             │
│  EWMA_ALPHA           │ 10-17%             │ 12.5%                            │
│  RETAIL_FEE           │ 20-24 bps          │ 22 bps                           │
│  ASYMMETRIC_EXTRA     │ 10-15 bps          │ 12 bps                           │
│  INVENTORY_LOW        │ 70-80%             │ 75%                              │
│  INVENTORY_HIGH       │ 120-130%           │ 125%                             │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## File References

| File | Notable Parameters |
|------|-------------------|
| `WinningV2Strategy.sol` | 25/38/3 - simple baseline |
| `WinningV3Strategy.sol` | 26/45/4 - balanced |
| `WinningV4Strategy.sol` | 27/55/5 - arb frequency tracking |
| `WinningV5Strategy.sol` | 24/65/7 - aggressive retail |
| `MaxEdgeFinalStrategy.sol` | 55/125/27 - anti-pattern |
