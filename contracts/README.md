# Contracts

All strategies inherit from `AMMStrategyBase` and implement the `IAMMStrategy` interface.

## Canonical (4)

| File | Contract | Role |
|------|----------|------|
| `IAMMStrategy.sol` | `interface IAMMStrategy` | Interface: `afterInitialize`, `afterSwap`, `getName` |
| `AMMStrategyBase.sol` | `abstract AMMStrategyBase` | Base: 32 storage slots, WAD math, fee clamping |
| `StarterStrategy.sol` | `Strategy` | Template to copy for new strategies (50 bps fixed) |
| `VanillaStrategy.sol` | `VanillaStrategy` | Normalizer AMM (30 bps fixed) — the baseline opponent |

## Static Baselines (5)

Fixed-fee calibration points for understanding the edge curve:

| File | Fee | getName() |
|------|-----|-----------|
| `Fixed30Strategy.sol` | 30 bps | `"Fixed30bps"` |
| `Low25bps.sol` | 25 bps | `"Static25bps"` |
| `TestFees.sol` | 40 bps | `"Static40bps"` |
| `Best78bps.sol` | 78 bps | `"Static78bps"` |
| `Static80bps.sol` | 80 bps | `"Static80bps"` |

## Winning Lineage (5)

Iterative progression of adaptive multi-signal strategies:

| File | getName() | Key Innovation |
|------|-----------|---------------|
| `WinningStrategy.sol` | `"AdaptiveMultiSignal"` | V1: EWMA, direction, consecutive, imbalance signals |
| `WinningV2Strategy.sol` | `"WinningV2"` | V2 iteration |
| `WinningV3Strategy.sol` | `"WinningV3"` | V3 iteration |
| `WinningV4Strategy.sol` | `"WinningV4"` | V4 iteration |
| `WinningV5Strategy.sol` | `"WinningV5"` | V5: extreme arb protection, 24 bps base, fast decay, EWMA |

## Arbitrage Protection (8)

Strategies focused on detecting and defending against arbitrage flow:

| File | getName() |
|------|-----------|
| `MaxEdgeStrategy.sol` | `"MaxEdge10pct"` |
| `MaxEdgeFinalStrategy.sol` | `"MaxEdgeFinal"` |
| `MaxEdgeV1Strategy.sol` | `"MaxEdgeV1"` |
| `MaxEdgeV2Strategy.sol` | `"MaxEdgeV2"` |
| `DefensiveStrategy.sol` | `"DefensiveArb"` |
| `GreedyEdgeStrategy.sol` | `"GreedyEdge"` |
| `GridSearchStrategy.sol` | `"GridSearch"` |
| `OptimalStrategy.sol` | `"Optimal"` |

## Retail Capture (3)

Strategies that aggressively compete for retail order flow:

| File | getName() |
|------|-----------|
| `AggressiveStrategy.sol` | `"AggressiveCapture"` |
| `BurstStrategy.sol` | `"BurstStrategy"` |
| `AllInStrategy.sol` | `"AllInStrategy"` |

## Regime Detection (2)

Strategies that identify market regimes and adapt fees accordingly:

| File | getName() |
|------|-----------|
| `RegimeStrategy.sol` | `"RegimeDetector"` |
| `RegimeV2Strategy.sol` | `"RegimeV2"` |

## Asymmetric (5)

Strategies with different buy/sell fees:

| File | getName() |
|------|-----------|
| `AsymmetricV2Strategy.sol` | `"AsymmetricV2"` |
| `SmartAsymmetricStrategy.sol` | `"SmartAsymmetric"` |
| `InvertedStrategy.sol` | `"InvertedStrategy"` |
| `CounterStrategy.sol` | `"CounterStrategy"` |
| `HybridStrategy.sol` | `"HybridStrategy"` |

## Other

| File | getName() |
|------|-----------|
| `OptimizedStrategy.sol` | `"OptimizedV1"` |
