# Grid Search Results

This document captures the findings from our systematic parameter optimization.

---

## 1. Best Configuration Found

```solidity
BASE_FEE = 24 * BPS;           // Undercut normalizer (30 bps)
POST_ARB_FEE = 175 * BPS;      // Strong spike after arb
ARB_THRESHOLD = WAD / 100;     // 1% of reserves
DECAY_PER_STEP = 12 * BPS;     // Fast recovery (~13 steps)
ASYMMETRIC_EXTRA = 10 * BPS;   // Extra on hit side
```

**Results (500 simulations):**
- Edge: ~390
- Margin over normalizer: ~+65
- Win rate: 100%

---

## 2. Key Discoveries

### Discovery 1: 1% Threshold is Optimal

We expected 2-3% threshold based on existing strategies. But 1% performs significantly better:

```
Threshold    Margin
─────────────────────
3.3%         +23
2.5%         +23
2.0%         +29
1.5%         +50
1.0%         +65  ← optimal
0.83%        +65
0.67%        +42  ← starts losing
0.5%         -17  ← too sensitive
```

**Why 1% works:**
- Retail trades rarely exceed 1% of reserves (mean ~20Y out of 10,000Y = 0.2%)
- Arbs typically trade 2-5% but sometimes smaller
- 1% catches small arbs that 2% misses
- Below 0.67%, starts flagging retail as arb (false positives hurt)

### Discovery 2: Higher Spikes are Better (with fast decay)

```
POST_ARB_FEE    DECAY    Margin
───────────────────────────────
65 bps         7        +23
100 bps        7        +29
150 bps        10       +61
175 bps        12       +65  ← optimal
200 bps        12       +65
250 bps        12       +50  ← too high
```

Higher spikes work IF decay is fast enough:
- 175 bps spike with 12 bps/step decay = 13 steps to recover
- During spike, normalizer captures retail
- Must recover quickly to resume retail capture

### Discovery 3: 24 bps Base is Sweet Spot

```
BASE_FEE    Margin
──────────────────
20 bps     +18  (too aggressive, more arb exposure)
22 bps     +26
23 bps     +65
24 bps     +65  ← sweet spot
25 bps     +65
26 bps     +63
28 bps     +17  (too close to normalizer)
```

24 bps gives 6 bps advantage over normalizer without excessive arb exposure.

### Discovery 4: Decay Rate Matters More Than Expected

```
DECAY       Margin (at 1% threshold, 175 bps spike)
─────────────────────────────────────────────────────
5 bps/step   +48  (too slow - lose retail during recovery)
7 bps/step   +55
10 bps/step  +62
12 bps/step  +65  ← optimal
15 bps/step  +63  (too fast - less protection)
```

12 bps/step balances:
- Fast enough to not lose too much retail during spike
- Slow enough to provide meaningful arb protection

---

## 3. Parameter Interactions

### Spike ↔ Decay Relationship

```
Higher spike → needs faster decay to stay competitive
Lower spike → can use slower decay for more protection

Optimal combinations:
- 175 bps spike + 12 bps decay = 13 steps to recover
- 150 bps spike + 10 bps decay = 13 steps to recover
- 200 bps spike + 15 bps decay = 12 steps to recover
```

The "recovery time" (spike - base) / decay should be ~12-15 steps.

### Threshold ↔ Spike Relationship

```
More sensitive threshold → catches more arbs → can use lower spike
Less sensitive threshold → misses arbs → needs higher spike to compensate

But: too sensitive starts flagging retail as arb
```

---

## 4. Comparison to Existing Strategies

| Strategy | BASE | POST | THRESHOLD | DECAY | Margin |
|----------|------|------|-----------|-------|--------|
| WinningV2 | 25 | 38 | 3.3% | 3 | ~+20 |
| WinningV5 | 24 | 65 | 2.0% | 7 | ~+30 |
| **Optimal** | **24** | **175** | **1.0%** | **12** | **~+65** |

Key differences:
1. **Much higher spike** (175 vs 38-65)
2. **Much more sensitive threshold** (1% vs 2-3.3%)
3. **Much faster decay** (12 vs 3-7)

---

## 5. Why This Works

### The Core Mechanism

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  1. Base fee 24 bps → capture ~52% of retail (vs normalizer)   │
│                                                                 │
│  2. Trade > 1% of reserves detected                             │
│     ├── If arb: spike prevents follow-up arbs                   │
│     └── If large retail: rare, and we recover quickly          │
│                                                                 │
│  3. Spike to 175 bps                                            │
│     ├── Arbs need much larger mispricing to profit              │
│     └── Normalizer temporarily more attractive                  │
│                                                                 │
│  4. Decay 12 bps/step (~13 steps to base)                       │
│     ├── Return to competitive before too much retail lost      │
│     └── Still protected during high-volatility period          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why Sensitive Threshold + High Spike Works

Previous strategies used conservative thresholds (2-3%) to avoid false positives. But:

1. **Retail trades are predictably small** (LogNormal, mean ~0.2%)
2. **1% is safely above retail** but catches more arbs
3. **High spike makes each detection more valuable**
4. **Fast decay limits false positive cost**

---

## 6. Limitations

### Gap to 522 Edge

Our best achieves ~390 edge, still below the 522 target. Possible reasons:

1. **We're missing a mechanism** - EWMA? Inventory protection? Pattern detection?
2. **Different hyperparameter space** - Maybe even more extreme parameters work
3. **Multi-regime approach** - Adapting parameters based on market conditions
4. **Different objective** - Maybe 522 is measured differently

### Variance

With 500 simulations, we saw edge ~390 ± ~15. The true optimal parameters might shift slightly with more simulations.

### Robustness

The 1% threshold is tuned to the simulation's retail order distribution. If real-world retail differs, optimal threshold may change.

---

## 7. Next Steps to Reach 522

1. **Add EWMA smoothing** - Adapt threshold based on recent trade sizes
2. **Add inventory protection** - Widen fees when reserves imbalanced
3. **Regime detection** - Switch parameters based on volatility
4. **Pattern recognition** - Detect arb bursts vs retail waves
5. **Non-linear decay** - Fast initially, slower as approaching base

---

## 8. Files Created

| File | Description |
|------|-------------|
| `contracts/src/OptimalStrategy.sol` | Optimized strategy implementation |
| `contracts/src/GridSearchStrategy.sol` | Parameterized template |
| `grid_search.py` | Grid search script |

---

## 9. Running the Grid Search

```bash
# Quick test (72 combinations, 50 sims each)
python grid_search.py --quick

# Standard grid (768 combinations, 100 sims each)
python grid_search.py

# Fine-tuning (480 combinations, custom sims)
python grid_search.py --fine --sims 200

# Test the optimal strategy
amm-match run contracts/src/OptimalStrategy.sol --simulations 500
```
