# Gap Analysis: Reaching 522 Edge

This document analyzes what's needed to reach the target of 522 edge.

---

## 1. Current State Assessment

### Known Baselines

| Strategy | Estimated Edge | Notes |
|----------|---------------|-------|
| Normalizer (30 bps static) | 250-350 | Baseline benchmark |
| Static 25 bps | ~300-400 | Simple undercut |
| WinningV2 | ~350-450 | Simplified adaptive |
| WinningV5 | ~400-500? | Aggressive retail |
| **Target** | **522** | Competition leader |

### Gap to Close

```
    Edge    │
            │
    522  ───┼─────────────────────────────────── TARGET
            │                              ?????
    500  ───┼─────────────────────────────●?????
            │                          ●
    450  ───┼───────────────────────●
            │                    ●
    400  ───┼────────────────●
            │             ●
    350  ───┼──────────●  WinningV2
            │       ●
    300  ───┼────●  Normalizer
            │
            └───────────────────────────────────►
               Static    V1    V2    V3    V4    V5    ???
```

**Estimated gap: ~50-150 edge points**

---

## 2. Edge Decomposition

Total edge has two components:

```
Edge = Retail_Edge - Arb_Losses

Where:
  Retail_Edge = Σ(retail trades) × (fee captured)
  Arb_Losses = Σ(arb trades) × (profit extracted)
```

### Improvement Levers

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                          IMPROVEMENT LEVERS                                     │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  1. INCREASE RETAIL EDGE                                                       │
│     ├── Capture more retail volume (lower fees)                               │
│     ├── Capture higher % of each trade (better routing)                       │
│     └── Increase edge per retail trade (optimal fee timing)                   │
│                                                                                │
│  2. DECREASE ARB LOSSES                                                        │
│     ├── Detect arbs more accurately                                           │
│     ├── Spike faster after detection                                          │
│     └── Reduce severity of each arb trade                                     │
│                                                                                │
│  3. EXPLOIT NORMALIZER WEAKNESSES                                              │
│     ├── Normalizer is rigid (never adapts)                                    │
│     ├── After your spike, normalizer attracts arbs                            │
│     └── You can strategically let normalizer take hits                        │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Hypotheses for Reaching 522 Edge

### Hypothesis 1: Even Lower Base Fee

**Current:** 24-27 bps
**Proposed:** 20-22 bps

```
Risk/Reward:
+ More retail volume (nonlinear routing benefit)
+ More edge per retail trade relative to normalizer
- More arb exposure (narrower no-arb band)
- Need stronger protection mechanism to compensate
```

**Experiment:** Test 20, 21, 22 bps with aggressive arb protection.

### Hypothesis 2: Smarter Decay Curves

**Current:** Linear decay (fee -= X per step)
**Proposed:** Non-linear decay

```solidity
// Current
fee = fee - steps * DECAY_PER_STEP;

// Proposed: Exponential decay
fee = BASE_FEE + (fee - BASE_FEE) * exp(-decay_rate * steps);

// Proposed: Hyperbolic decay
fee = BASE_FEE + (fee - BASE_FEE) / (1 + steps / half_life);
```

**Intuition:** Fast decay initially (get competitive), slow decay later (maintain protection).

```
Fee │
    │   ┌─── spike
    │   │╲
    │   │ ╲╲╲        Linear (current)
    │   │    ╲╲╲╲
    │───┴────────╲── base
    │
    │   ┌─── spike
    │   │╲
    │   │  ╲         Exponential (proposed)
    │   │    ╲╲╲
    │───┴────────╲── base
```

### Hypothesis 3: Predictive Arb Detection

**Current:** React AFTER arb trade happens
**Proposed:** Predict arb conditions BEFORE they hit

Signals that predict arbs:
- Large gap since last trade (price likely moved)
- High recent EWMA (volatile market)
- Recent inventory imbalance (directional pressure)

```solidity
// Instead of waiting for arb trade, preemptively raise fees
if (steps_since_last > 5 && ewma > baseline * 2) {
    // Likely price moved, arb incoming
    fee = DEFENSIVE_FEE;  // Higher than base but lower than post-arb
}
```

### Hypothesis 4: Regime-Dependent Parameters

**Current:** Fixed parameters across all market conditions
**Proposed:** Detect market regime and adapt

```
Regime Detection:
- High vol: ewma > 1.5% → use defensive params
- Low vol: ewma < 0.5% → use aggressive params
- Normal: use balanced params

Parameter Switching:
              │ High Vol    │ Normal      │ Low Vol
─────────────┼─────────────┼─────────────┼─────────────
BASE_FEE     │ 28 bps      │ 25 bps      │ 22 bps
POST_ARB_FEE │ 70 bps      │ 55 bps      │ 45 bps
DECAY        │ 4 bps       │ 6 bps       │ 8 bps
```

### Hypothesis 5: Strategic Normalizer Exploitation

**Insight:** After you spike fees, normalizer temporarily more attractive.

**Proposed:** Use normalizer as arb magnet during recovery.

```
Phase 1: You detect arb, spike to 65 bps
Phase 2: Normalizer at 30 bps attracts next arb wave
Phase 3: You decay to 35 bps (still above normalizer)
Phase 4: When normalizer takes hit, you drop to 25 bps
Phase 5: Capture the "clean" retail while normalizer recovers

Key insight: Arbs hit BOTH AMMs, but normalizer can't adapt.
If you time your fee recovery, you can capture retail
when normalizer is "dirty" (post-arb).
```

### Hypothesis 6: Trade Pattern Recognition

**Current:** Each trade evaluated independently
**Proposed:** Recognize multi-trade patterns

```
Patterns to detect:
1. Arb burst: 2-3 large same-direction trades in sequence
2. Retail wave: Many small random-direction trades
3. Quiet → activity: Long gap then sudden trades
4. Oscillation: Alternating direction (market searching)

Response by pattern:
- Arb burst: Stay elevated longer after detecting
- Retail wave: Drop to aggressive retail fees
- Quiet → activity: Start elevated, decay fast
- Oscillation: Widen spread asymmetrically
```

### Hypothesis 7: Micro-Optimization of Existing Parameters

Instead of new mechanisms, find optimal existing parameters:

```
Grid search space:
- BASE_FEE: [20, 21, 22, 23, 24, 25, 26]
- POST_ARB: [40, 45, 50, 55, 60, 65, 70]
- DECAY: [4, 5, 6, 7, 8]
- THRESHOLD: [1.5%, 2%, 2.5%, 3%]
- ALPHA: [8%, 10%, 12%, 15%]
- ASYMMETRIC: [8, 10, 12, 15]

Total combinations: 7 × 7 × 5 × 4 × 4 × 4 = 15,680
```

Current strategies may not be at the true optimum.

---

## 4. Unexplored Design Spaces

### Dynamic Asymmetry

Instead of fixed +15 bps on hit side:

```solidity
// Scale asymmetry by trade size
uint256 asymmetric = wmul(tradeRatio, 5 * WAD);  // ~5x trade ratio in bps
asymmetric = asymmetric > 20 * BPS ? 20 * BPS : asymmetric;

if (trade.isBuy) {
    bidFee = clampFee(bidFee + asymmetric);
}
```

### Momentum-Scaled Response

```solidity
// Bigger spike if momentum building
uint256 spike = POST_ARB_FEE;
if (consec > 2) {
    spike = spike + (consec - 2) * 5 * BPS;
}
```

### Inventory-Aware Base Fee

```solidity
// Lower base when balanced, higher when stressed
uint256 baseFee = BASE_FEE;
if (ratio < 0.85 || ratio > 1.15) {
    baseFee = baseFee + 3 * BPS;  // Defensive when imbalanced
}
```

### Time-of-Simulation Effects

```solidity
// Early in simulation: more aggressive
// Late in simulation: more conservative
if (trade.timestamp < 2000) {
    fee = fee - 2 * BPS;  // Early aggression
} else if (trade.timestamp > 8000) {
    fee = fee + 2 * BPS;  // Late defense
}
```

---

## 5. Research Questions

### Must Answer

1. **What base fee maximizes retail edge?**
   - Test 20-27 bps systematically
   - Find crossover point where arb losses > retail gains

2. **What's the optimal recovery time?**
   - Test decay from 3 to 10 bps/step
   - Find where retail loss during spike is minimized

3. **Is current arb detection optimal?**
   - Test thresholds from 1.5% to 4%
   - Find where false positives balance false negatives

### Should Investigate

4. **Does regime switching help?**
   - Test adaptive parameters vs fixed
   - Measure edge variance across simulation types

5. **Can we exploit normalizer rigidity?**
   - Test strategic fee timing
   - Measure benefit of "letting normalizer take hit"

6. **Does trade history matter?**
   - Test multi-trade pattern detection
   - Measure information value of recent trades

### Nice to Explore

7. **Non-linear decay functions**
8. **Dynamic asymmetry scaling**
9. **Early/late simulation behavior**
10. **Inventory-aware base fees**

---

## 6. Potential Strategy Architectures

### Architecture A: Extreme Retail Capture

```solidity
BASE_FEE = 20 * BPS;       // Ultra-competitive
POST_ARB = 70 * BPS;       // Strong protection
DECAY = 8 * BPS;           // Very fast recovery
RETAIL_FEE = 18 * BPS;     // Aggressive retail discount
THRESHOLD = 2%;            // Sensitive detection
```

**Philosophy:** Maximize retail volume, accept some arb losses.

### Architecture B: Minimal Arb Exposure

```solidity
BASE_FEE = 27 * BPS;       // Less aggressive
POST_ARB = 60 * BPS;       // Solid protection
DECAY = 5 * BPS;           // Moderate recovery
THRESHOLD = 2.5%;          // Balanced detection
ASYMMETRIC = 15 * BPS;     // Strong directional protection
```

**Philosophy:** Minimize arb losses, accept less retail.

### Architecture C: Adaptive Regime

```solidity
// Detect regime from EWMA
if (ewma > 1.5%) {
    // High vol regime
    USE_PARAMS = defensive_params;
} else if (ewma < 0.5%) {
    // Low vol regime
    USE_PARAMS = aggressive_params;
} else {
    USE_PARAMS = balanced_params;
}
```

**Philosophy:** Adapt to market conditions.

### Architecture D: Pattern-Based

```solidity
// Track last N trades
// Detect patterns
// Respond accordingly

if (detected_arb_burst) {
    stay_elevated_longer();
} else if (detected_retail_wave) {
    drop_to_minimum();
} else {
    standard_adaptive();
}
```

**Philosophy:** Use information from trade history.

---

## 7. Competitive Edge Analysis

To beat 522 edge, consider what the leader might be doing:

### Likely NOT Doing
- Static fees (too simple)
- Very high base (>30 bps) - loses retail
- Very slow decay (<3 bps) - loses retail during recovery
- No arb detection - loses to arbs

### Likely Doing
- Base fee 22-26 bps (undercut normalizer)
- Fast decay (6-8 bps/step)
- Sensitive arb detection (2-2.5%)
- Some asymmetric protection
- EWMA smoothing

### Possibly Doing (Edge Cases)
- Non-linear decay
- Regime detection
- Multi-trade pattern recognition
- Strategic normalizer exploitation
- Optimized parameters beyond our grid

---

## 8. Implementation Priority

### Phase 1: Parameter Optimization (Low Risk)

1. Systematic grid search on existing architecture
2. Find best (BASE, POST_ARB, DECAY, THRESHOLD) combination
3. Expected gain: 10-30 edge points

### Phase 2: Mechanism Improvements (Medium Risk)

1. Non-linear decay curves
2. Dynamic asymmetry
3. Regime-adaptive parameters
4. Expected gain: 20-50 edge points

### Phase 3: Novel Approaches (Higher Risk)

1. Pattern recognition
2. Predictive fee adjustment
3. Strategic normalizer exploitation
4. Expected gain: 30-100 edge points (if successful)

---

## 9. Testing Framework

To validate hypotheses:

```bash
# Run baseline
amm-match run WinningV5Strategy.sol --simulations 1000

# Compare variants
amm-match run HypothesisA.sol --simulations 1000
amm-match run HypothesisB.sol --simulations 1000

# Statistical comparison
# Need multiple runs to account for variance
# ~1000 simulations gives good confidence
```

### Metrics to Track

| Metric | Meaning |
|--------|---------|
| Average Edge | Primary goal |
| Edge Std Dev | Consistency |
| Retail Edge | Component 1 |
| Arb Losses | Component 2 |
| Retail Volume Share | vs normalizer |
| Avg Bid/Ask Fee | Fee level over time |

---

## 10. Summary: Path to 522

```
Current Best ───────────────────────────────── ~450 edge
                │
Phase 1:        │  Grid search optimization
Parameter       │  (+20-30 edge)
Tuning          │
                ▼
Intermediate ───────────────────────────────── ~470 edge
                │
Phase 2:        │  Non-linear decay
Mechanism       │  Dynamic asymmetry
Improvements    │  Regime detection
                │  (+30-50 edge)
                ▼
Near Target ────────────────────────────────── ~510 edge
                │
Phase 3:        │  Pattern recognition
Novel           │  Predictive fees
Approaches      │  Normalizer exploitation
                │  (+15-20 edge)
                ▼
TARGET ─────────────────────────────────────── 522 edge
```

---

## 11. Key Insights

1. **522 edge is achievable** - It's ~50% better than normalizer baseline
2. **Incremental gains compound** - Small improvements in each area add up
3. **The gap is in the details** - Major architecture is likely correct
4. **Testing is critical** - Many hypotheses, need to validate empirically
5. **Variance matters** - Need to average over many simulations
6. **Multiple paths** - Can optimize retail OR protection OR both

---

## 12. Next Steps

1. **Run baselines** - Get actual edge numbers for existing strategies
2. **Grid search** - Find optimal parameters in existing architecture
3. **Prototype new mechanisms** - Test most promising hypotheses
4. **Iterate** - Combine best findings into final strategy

---

## File References

| File | Purpose |
|------|---------|
| `test_*.py` | Parameter exploration scripts |
| `find_*.py` | Optimization scripts |
| `optimize_pareto.py` | Multi-objective optimization |
| `parallel_harness.py` | Parallel test runner |
