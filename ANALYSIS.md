# Research Methodology Post-Mortem

## Summary

Our SigmaAdaptive strategy scores **526.54** vs our previous best WinningV5 at **295.57** — a **+231 point delta**. This gap came from a fundamental architectural difference, not parameter tuning. Here's why our research process missed it.

---

## The Two Paradigms

### Our Paradigm: Trade Classification

```
Observe trade → Is it big? → ARB → Spike fee → Decay back to base
                           → RETAIL → Low/competitive fee
```

All 29 experimental strategies, all 7 gap-analysis hypotheses, and all grid searches operated within this single paradigm. The research question was always "how do I better classify each trade as arb or retail?"

### The Winning Paradigm: State Estimation

```
Observe trade → Estimate hidden state (pHat, sigmaHat, tox, dir, act)
              → Fee = f(state_estimate)
              → No classification needed
```

The key insight: **fair price is hidden but estimable.** Every trade gives you an implied price. Track these through an adaptive volatility-gated filter to estimate the true fair price. Then toxicity = |spot − pHat| / pHat tells you how mispriced you are — and therefore what fee to charge. No arb-vs-retail classification needed.

---

## The Winning Techniques

Reference: [jiayaoqijia/amm-challenge-yq](https://github.com/jiayaoqijia/amm-challenge-yq) (scores ~523.21 locally)

| Technique | How It Works | Edge Impact |
|-----------|-------------|-------------|
| **pHat with adaptive sigma gate** | gate = max(sigmaHat × 10, 3%). Tight in low vol for fast tracking, wide in high vol for noise rejection. Alpha = 0.26 on first-in-step, 0.05 on subsequent. | **−0.42** when removed (only feature that survives ablation) |
| **Cubic toxicity** | 15000 bps × tox³ for superlinear arb deterrence at high toxicity | Within noise individually, contributes to composite |
| **Trade-aligned boost** | 2500 bps × tradeRatio when trade direction matches spot−pHat divergence | Real-time per-trade arb detection |
| **Asymmetric stale discount** | Attract side gets 1.124× larger discount than protect side | Improves retail capture |
| **Multi-layer fee decomposition** | fBase (sigma + lambda + flow) + fMid (tox linear/quad/cubic + activity + sigma×tox interaction) + directional skew | Composite architecture |
| **pHat implied price reconstruction** | pImplied = spot × (1−fee) for buys, spot / (1−fee) for sells — accounts for fee impact when backing out fair price | Enables accurate state estimation |

---

## How We Got Stuck

### 1. Early success anchored us to the wrong architecture

WinningV1 through V5 showed clear improvement over static fees. Each iteration felt like progress. But we were climbing a local hill while the global peak required a different architecture entirely. The V1→V5 progression was parameter refinement, not paradigm exploration.

### 2. The grid search reinforced the local optimum

We found ~390 edge at BASE=24, POST_ARB=175, THRESHOLD=1%, DECAY=12 (research/07_grid_search_results.md). This created an anchoring effect — the problem became "how do we tweak from here?" rather than "is this even the right architecture?"

### 3. The gap analysis proposed only intra-paradigm hypotheses

All 7 hypotheses in research/06_gap_analysis.md are variations within the detection paradigm:
- Lower base fee, smarter decay, predictive detection, regime switching, normalizer exploitation, pattern recognition, parameter micro-optimization

None asked: "what if we estimate the hidden market state instead of classifying individual trades?"

### 4. We generalized incorrectly from a correct observation

We correctly identified that MaxEdge approaches (55 bps base) fail because they lose retail to the normalizer. But we concluded "high base = death" rather than "static high base = death, but dynamic state-estimating fees can work at any level."

### 5. No competitive intelligence

The winning reference implementation was publicly available on GitHub. The Algebra Finance write-up was on Medium. We never looked. The leaderboard showed scores around 522 — barely above the 30 bps baseline (~522.13) — which should have signaled that the problem wasn't about finding slightly better parameters of the same architecture, but about solving a fundamentally harder estimation problem.

---

## What We Did Right

- **Systematic experimentation infrastructure**: `parallel_harness.py`, `grid_search.py`, structured experiment directories
- **Good documentation**: The research/ documents correctly analyze the math, tradeoffs, and failure modes
- **Correct mechanical understanding**: The strategy analysis correctly explains why routing favors lower fees, why static high fees fail, how edge is computed
- **Iterative approach**: Building V1 through V5 incrementally is sound methodology — we just iterated within too narrow a space

---

## Lessons for Future Research

### 1. Start with competitive intelligence

Before writing strategy code, search for existing solutions, leaderboard patterns, and open-source implementations. The winning architecture was discoverable through public information.

### 2. Frame problems as state estimation, not classification

The challenge says "you cannot see the fair price." The right response is "so let me estimate it" — not "so let me classify trades without it." Whenever a competition hides information from you, the first research question should be: "can I reconstruct it from what I CAN observe?"

### 3. Explore orthogonal architectures before fine-tuning

If all your strategies are spike-and-decay variants, you're not exploring — you're hill-climbing. Test fundamentally different approaches at low simulation counts before committing to parameter sweeps.

### 4. Use ablations to find signal from noise

The winning implementation's ablation study showed only the pHat mechanism survived (−0.42 when removed, everything else within ±0.3 noise). If we'd ablated our own strategies, we'd have found that all our complexity (EWMA, momentum, inventory, consecutive tracking) was adding noise around a fundamentally limited core.

### 5. Question your paradigm when progress plateaus

After V5 and the grid search both plateaued around 300−400, that was a signal that the architecture itself was the bottleneck, not the parameters. A plateau after systematic search means you're at a local maximum — the next improvement requires a different hill.

### 6. Ask "what information is theoretically available?"

The TradeInfo struct gives: amounts, direction, reserves, timestamp. From these you can reconstruct: implied price, spot price, trade size ratio, time gaps, reserve drift. The question "what hidden variables can I estimate from these observables?" leads to pHat, sigmaHat, lambdaHat, toxicity. We asked "how do I classify this trade?" instead.

### 7. Look for the information-theoretic bottleneck

The competition limits you to 32 storage slots and 250k gas. The winning strategy uses 11 slots for state estimation. Our strategies used 4 slots (bidFee, askFee, lastTs, EWMA). We weren't using the available information capacity — a sign we weren't tracking enough state.
