# Detection Mechanisms

This document covers how strategies detect arb vs retail trades and adapt fees accordingly.

---

## 1. The Detection Problem

Your strategy sees `TradeInfo` after each trade but **cannot directly see**:
- Whether the trade was arb or retail
- The fair price
- The normalizer's state
- Future order flow

You must **infer** trade type from observable signals.

---

## 2. Primary Signal: Trade Ratio

The most important signal is trade size relative to reserves:

```solidity
tradeRatio = wdiv(trade.amountY, trade.reserveY)
```

### Why This Works

**Arb trades are typically large:**
- Arbs compute optimal size to extract maximum profit
- For typical mispricings, this is 2-5% of reserves
- They have no reason to trade small amounts

**Retail trades are typically small:**
- Individual retail orders average ~20 Y (0.2% of initial 10,000)
- Even after splitting, retail rarely exceeds 1%
- LogNormal distribution means most are near the mean

### Threshold Values

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TRADE RATIO INTERPRETATION                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Ratio         │  Classification     │  Typical Action                 │
│  ──────────────┼─────────────────────┼───────────────────────────────  │
│  < 0.4%        │  Tiny retail        │  Ultra-low fees (20 bps)        │
│  0.4% - 1.5%   │  Normal retail      │  Base fees (24-27 bps)          │
│  1.5% - 2.5%   │  Large retail/???   │  Base fees or slight increase   │
│  > 2.5%        │  Likely arb         │  Spike fees (45-65 bps)         │
│  > 4%          │  Definitely arb     │  Maximum spike                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Strategy Examples

```solidity
// WinningV2 - moderate threshold
ARB_THRESHOLD = WAD / 30;  // 3.3%

// WinningV4/V5 - sensitive threshold
ARB_THRESHOLD = WAD / 50;  // 2.0%

// WinningV3 - middle ground
ARB_THRESHOLD = WAD / 40;  // 2.5%

// WinningV1 - conservative
LARGE_TRADE_THRESHOLD = WAD / 25;  // 4.0%
```

---

## 3. EWMA Smoothing

Exponential Weighted Moving Average smooths trade ratios over time:

```solidity
ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA)
```

### Mathematical Form

```
EWMA_new = (1 - α) × EWMA_old + α × current_value

Where α = smoothing factor (e.g., 0.1 = 10%)
```

### Why Use EWMA?

1. **Adapts to market conditions** - In high-vol environments, "normal" is larger
2. **Reduces noise** - Single outlier doesn't trigger false positive
3. **Provides baseline** - Can compare current trade to recent average

### Alpha Values in Practice

```
┌────────────────────────────────────────────────────────────────────────┐
│                      EWMA ALPHA COMPARISON                              │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  α Value     │  Strategy      │  Half-life   │  Behavior              │
│  ────────────┼────────────────┼──────────────┼──────────────────────  │
│  5%  (1/20)  │  -             │  ~14 trades  │  Very smooth, slow     │
│  10% (1/10)  │  WinningV3     │  ~7 trades   │  Moderate              │
│  12.5% (1/8) │  MaxEdgeFinal  │  ~5 trades   │  Responsive            │
│  16.7% (1/6) │  WinningV5     │  ~4 trades   │  Fast adaptation       │
│                                                                        │
│  Half-life = ln(0.5) / ln(1 - α)                                      │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### EWMA-Based Arb Detection

```solidity
// Absolute threshold OR relative to recent average
bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;

// WinningV4 uses 4x multiple
bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 4;

// WinningV5 uses 5x multiple
bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 5;
```

### Visual Example

```
Trade   │
Ratio   │
        │
  5%  ──┼─────────────────●─────────────────── Arb Threshold (2%)
        │                  ╲
        │                   ╲
  3%  ──┼────────────────●───●──────────────── EWMA × 3
        │               ╱     ╲
        │              ╱       ╲ EWMA
  1%  ──┼─────●───●───●─────────●───●───●─────
        │    ╱   ╲   ╱           ╲  ╱   ╲
        │   ●     ●─●             ●●     ●
        └─────────────────────────────────────► Trade #
                 ▲
                 │
            This spike exceeds
            both thresholds → ARB
```

---

## 4. Inventory Imbalance Detection

Monitor reserve ratio to detect directional pressure:

```solidity
uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
```

### Why Multiply by 100?

Initial state: 100 X, 10,000 Y at price 100.
Ratio should equal ~1.0 (WAD) when balanced.

```
ratio = (reserveX × 100) / reserveY
      = (100 × 100) / 10000
      = 10000 / 10000
      = 1.0 (= WAD)
```

### Imbalance Thresholds

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    INVENTORY IMBALANCE DETECTION                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Ratio        │  Meaning                │  Action                       │
│  ─────────────┼─────────────────────────┼─────────────────────────────  │
│  < 0.70 WAD   │  X severely depleted    │  +15 bps on ASK (V5)          │
│  < 0.75 WAD   │  X depleted             │  +12-15 bps on ASK            │
│  < 0.80 WAD   │  X low                  │  +8 bps on ASK (V3)           │
│  < 0.85 WAD   │  X slightly low         │  raise ASK to 30 bps (V2)     │
│  ─────────────┼─────────────────────────┼─────────────────────────────  │
│  0.85 - 1.15  │  Balanced               │  No adjustment                │
│  ─────────────┼─────────────────────────┼─────────────────────────────  │
│  > 1.15 WAD   │  X slightly excess      │  raise BID to 30 bps (V2)     │
│  > 1.20 WAD   │  X excess               │  +8 bps on BID (V3)           │
│  > 1.25 WAD   │  X very excess          │  +12-15 bps on BID            │
│  > 1.30 WAD   │  X severely excess      │  +15 bps on BID (V5)          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Strategy Comparison

```solidity
// WinningV2 - gentle protection
if (ratio < WAD * 85 / 100) {
    if (askFee < 30 * BPS) askFee = 30 * BPS;
}

// WinningV4 - moderate protection
if (ratio < WAD * 75 / 100) {
    askFee = clampFee(askFee + 12 * BPS);
}

// WinningV5 - aggressive protection
if (ratio < WAD * 70 / 100) {
    askFee = clampFee(askFee + 15 * BPS);
}
```

---

## 5. Directional Momentum

Track consecutive trades in same direction:

```solidity
uint256 lastDir = slots[SLOT_LAST_DIRECTION];
uint256 thisDir = trade.isBuy ? 1 : 2;
uint256 consec = slots[SLOT_CONSECUTIVE];

if (thisDir == lastDir && lastDir != 0) {
    consec = consec + 1;
    if (consec > 5) consec = 5; // Cap
} else {
    consec = 1;
}
```

### Why Track Momentum?

- **Arbs often come in bursts** - price moves trigger multiple arb trades
- **Retail is random** - 50/50 buy/sell, no momentum
- **Multiple same-direction = higher probability of arb**

### Asymmetric Adjustment

```solidity
if (consec > 1) {
    uint256 consecAdjust = (consec - 1) * CONSEC_ADJUST;  // 5 bps per trade

    if (trade.isBuy) {
        // AMM buying X → price going down
        bidFee = clampFee(bidFee + consecAdjust);
    } else {
        // AMM selling X → price going up
        askFee = clampFee(askFee + consecAdjust);
    }
}
```

### Visual Example

```
Trade # │ Dir │ Consec │ Extra Fee (5 bps/trade)
────────┼─────┼────────┼─────────────────────────
   1    │ Buy │   1    │  0 bps
   2    │ Buy │   2    │  5 bps on BID
   3    │ Buy │   3    │  10 bps on BID
   4    │ Buy │   4    │  15 bps on BID
   5    │ Sell│   1    │  0 bps (reset)
   6    │ Sell│   2    │  5 bps on ASK
```

---

## 6. Time-Based Signals

### Timestamp Tracking

```solidity
uint256 lastTs = slots[SLOT_LAST_TS];
uint256 steps = trade.timestamp - lastTs;
slots[SLOT_LAST_TS] = trade.timestamp;
```

### Gap Analysis

- **Large gap (many steps since last trade)**: Market quiet, likely retail starting
- **Small gap (rapid trades)**: Could be arb session

### Window Limits

```solidity
// Only decay if reasonable time passed
if (steps > 0 && steps < 30) {
    uint256 decay = steps * DECAY_PER_STEP;
    // Apply decay...
}
// If steps >= 30, reset to base (too long since last trade)
```

---

## 7. Arb Frequency Tracking (WinningV4)

Track ratio of arbs to total trades:

```solidity
uint256 arbCount = slots[SLOT_ARB_COUNT];
uint256 totalCount = slots[SLOT_TOTAL_COUNT] + 1;

if (isArb) {
    arbCount = arbCount + 1;
}

slots[SLOT_ARB_COUNT] = arbCount;
slots[SLOT_TOTAL_COUNT] = totalCount;

// Adaptive response
if (totalCount > 100) {
    uint256 arbRatio = wdiv(arbCount * WAD, totalCount * WAD);
    if (arbRatio > WAD / 4) {  // >25% arbs
        if (bidFee < 28 * BPS) bidFee = 28 * BPS;
        if (askFee < 28 * BPS) askFee = 28 * BPS;
    }
}
```

### Why This Helps

- **High arb environment**: Raise base fee defensively
- **Low arb environment**: Can be more aggressive on retail

---

## 8. Retail Detection

Inverse of arb detection - identify trades that are definitely retail:

```solidity
// WinningV4: Very small trades
if (tradeRatio < WAD / 200) {  // <0.5%
    bidFee = RETAIL_FEE;  // 22 bps
    askFee = RETAIL_FEE;
}

// WinningV5: Tiny trades
if (tradeRatio < WAD / 250) {  // <0.4%
    bidFee = RETAIL_FEE;  // 20 bps
    askFee = RETAIL_FEE;
}

// Alternative: Compare to EWMA
if (tradeRatio < ewma / 2) {
    // Below-average trade = likely retail
    bidFee = BASE_FEE - 2 * BPS;
    askFee = BASE_FEE - 2 * BPS;
}
```

---

## 9. Detection Matrix

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                        MULTI-SIGNAL DETECTION MATRIX                            │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│                         │ Trade Ratio │ EWMA Check │ Momentum │ Inventory     │
│  ───────────────────────┼─────────────┼────────────┼──────────┼─────────────  │
│  Definitely Retail      │   <0.5%     │  < ewma/2  │  reset   │  balanced     │
│  Probably Retail        │   <1.5%     │  < ewma    │  1-2     │  balanced     │
│  Uncertain              │   1.5-2.5%  │  ~ewma     │  2-3     │  slight       │
│  Probably Arb           │   >2.5%     │  > ewma×2  │  3+      │  moderate     │
│  Definitely Arb         │   >4%       │  > ewma×4  │  4+      │  severe       │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Implementation Patterns

### Simple Detection (V2 style)

```solidity
function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
    uint256 fee = slots[0];

    // Simple threshold
    uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
    if (tradeRatio > WAD / 30) {  // >3.3%
        fee = POST_ARB_FEE;
    } else {
        // Time decay
        fee = decayToBase(fee, trade.timestamp);
    }

    return (fee, fee);
}
```

### Multi-Signal Detection (V4/V5 style)

```solidity
function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
    uint256 bidFee = slots[SLOT_BID_FEE];
    uint256 askFee = slots[SLOT_ASK_FEE];
    uint256 ewma = slots[SLOT_EWMA];

    uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

    // Update EWMA
    ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
    slots[SLOT_EWMA] = ewma;

    // Multi-signal arb detection
    bool isArb = tradeRatio > ARB_THRESHOLD      // Absolute
              || tradeRatio > ewma * 4;           // Relative

    if (isArb) {
        bidFee = POST_ARB_FEE;
        askFee = POST_ARB_FEE;

        // Asymmetric
        if (trade.isBuy) bidFee += 15 * BPS;
        else askFee += 15 * BPS;

    } else if (tradeRatio < WAD / 200) {
        // Definitely retail
        bidFee = RETAIL_FEE;
        askFee = RETAIL_FEE;

    } else if (tradeRatio < ewma / 2) {
        // Probably retail
        bidFee = BASE_FEE - 2 * BPS;
        askFee = BASE_FEE - 2 * BPS;

    } else {
        // Time decay
        bidFee = decayToBase(bidFee);
        askFee = decayToBase(askFee);
    }

    // Inventory protection
    uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
    if (ratio < WAD * 75 / 100) {
        askFee += 15 * BPS;
    } else if (ratio > WAD * 125 / 100) {
        bidFee += 15 * BPS;
    }

    return (bidFee, askFee);
}
```

---

## 11. Detection Tuning Guidelines

### Arb Threshold

| Threshold | Trade-off |
|-----------|-----------|
| 2% | Very sensitive - catches more arbs but may flag large retail |
| 2.5% | Balanced - good default |
| 3.3% | Conservative - misses some arbs but fewer false positives |
| 4% | Very conservative - only catches obvious arbs |

### EWMA Alpha

| Alpha | Trade-off |
|-------|-----------|
| 5% | Very smooth - slow to adapt but stable |
| 10% | Balanced - moderate adaptation |
| 16.7% | Responsive - fast adaptation but more noise |

### Retail Threshold

| Threshold | Trade-off |
|-----------|-----------|
| 0.4% | Aggressive - more ultra-low fees, risk of arb gaming |
| 0.5% | Balanced - safe retail detection |
| 1% | Conservative - only tiny trades get discount |

---

## 12. Key Takeaways

1. **Trade ratio is primary signal** - Size relative to reserves
2. **EWMA adapts to conditions** - What's "normal" changes
3. **Combine signals** - Absolute OR relative OR momentum
4. **Inventory matters** - Protect depleted side
5. **Fast retail, slow arb** - Retail discount immediately, spike cautiously
6. **Asymmetric protection** - Hit side gets extra protection
7. **Err on side of retail** - Better to miss an arb than lose retail

---

## File References

| File | Detection Pattern |
|------|-------------------|
| `WinningV2Strategy.sol` | Simple threshold |
| `WinningV3Strategy.sol` | EWMA + threshold |
| `WinningV4Strategy.sol` | Multi-signal + arb frequency |
| `WinningV5Strategy.sol` | Aggressive retail detection |
| `WinningStrategy.sol` | Momentum tracking |
