// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title SigmaAdaptive — State-estimating adaptive fee strategy
/// @notice Estimates fair price (pHat), volatility (sigmaHat), and toxicity
///         from observed trades. Uses adaptive sigma-gated price tracking,
///         cubic toxicity response, and asymmetric directional fees.
///
///         Research lineage: WinningV5 → SigmaAdaptive
///         Key innovations (from jiayaoqijia/amm-challenge-yq):
///         - pHat with adaptive sigma-gated updates
///         - Cubic toxicity term for superlinear arb deterrence
///         - Trade-aligned boost (real-time per-trade arb detection)
///         - Asymmetric stale direction discount
contract Strategy is AMMStrategyBase {
    // ── Storage slot layout (12 of 32 used) ──
    uint256 constant SLOT_BID_FEE     = 0;  // current bid fee
    uint256 constant SLOT_ASK_FEE     = 1;  // current ask fee
    uint256 constant SLOT_LAST_TS     = 2;  // last trade timestamp
    uint256 constant SLOT_PHAT        = 3;  // estimated fair price
    uint256 constant SLOT_SIGMA_HAT   = 4;  // estimated volatility
    uint256 constant SLOT_LAMBDA_HAT  = 5;  // estimated arrival rate
    uint256 constant SLOT_SIZE_HAT    = 6;  // estimated trade size
    uint256 constant SLOT_TOX_EMA     = 7;  // toxicity EMA
    uint256 constant SLOT_DIR_STATE   = 8;  // directional pressure (WAD-centered)
    uint256 constant SLOT_ACT_EMA     = 9;  // activity EMA
    uint256 constant SLOT_STEP_COUNT  = 10; // trades in current step
    uint256 constant SLOT_FIRST_IN    = 11; // whether pHat was updated this step

    // ── pHat estimation ──
    uint256 constant PHAT_ALPHA_FIRST = WAD * 26 / 100;   // 26% weight on first-in-step
    uint256 constant PHAT_ALPHA_REST  = WAD * 5 / 100;    // 5% weight on subsequent
    uint256 constant GATE_MULTIPLIER  = 10;                // gate = max(sigmaHat * 10, min)
    uint256 constant GATE_MIN         = WAD * 3 / 100;     // minimum gate 3%

    // ── sigma estimation ──
    uint256 constant SIGMA_ALPHA      = WAD * 176 / 1000;  // ~17.6% weight
    uint256 constant SIGMA_DECAY      = WAD * 824 / 1000;  // 1 - alpha for decay

    // ── EMA decay per idle step (linear approx) ──
    uint256 constant DIR_DECAY_STEP   = WAD * 5 / 100;     // dirState → center @ 5%/step
    uint256 constant ACT_DECAY_STEP   = WAD * 10 / 100;    // actEma → 0 @ 10%/step
    uint256 constant SIZE_DECAY_STEP  = WAD * 10 / 100;    // sizeHat → 0 @ 10%/step
    uint256 constant TOX_DECAY_STEP   = WAD * 3 / 100;     // toxEma → 0 @ 3%/step

    // ── Signal update blends ──
    uint256 constant SIGNAL_THRESHOLD = WAD / 500;          // 0.2% min trade ratio
    uint256 constant DIR_PUSH_SCALE   = 2;                  // dir push = tradeRatio * 2
    uint256 constant DIR_PUSH_CAP     = WAD / 4;            // cap push at 25%
    uint256 constant ACT_ALPHA        = WAD * 15 / 1000;    // 1.5% blend
    uint256 constant SIZE_ALPHA       = WAD * 182 / 1000;   // 18.2% blend
    uint256 constant TOX_ALPHA        = WAD * 949 / 1000;   // 94.9% weight (very fast)
    uint256 constant TOX_CAP          = WAD / 5;            // cap tox at 20%

    // ── Base fee components ──
    uint256 constant FEE_FLOOR        = 3 * BPS;            // minimum fee 3bps
    uint256 constant SIGMA_COEF       = 200;                // * BPS scaled: 200e14 * sigmaHat / WAD
    uint256 constant LAMBDA_COEF      = 12 * BPS;           // arrival rate coefficient
    uint256 constant FLOW_COEF        = 5000 * BPS;          // lambda * size coefficient

    // ── Toxicity fee components ──
    uint256 constant TOX_LINEAR_COEF  = 250 * BPS;          // linear tox
    uint256 constant TOX_QUAD_COEF   = 12000 * BPS;         // quadratic tox
    uint256 constant TOX_CUBIC_COEF  = 15000 * BPS;         // cubic tox
    uint256 constant ACTIVITY_COEF   = 90000 * BPS;         // activity contribution
    uint256 constant SIGMA_TOX_COEF  = 500 * BPS;           // sigma*tox interaction

    // ── Directional skew ──
    uint256 constant SKEW_BASE_COEF   = 20 * BPS;           // base skew per dirDev
    uint256 constant SKEW_TOX_COEF    = 100 * BPS;          // tox-weighted skew

    // ── Stale direction discount ──
    uint256 constant STALE_SHIFT_BASE = 7000 * BPS;         // base stale shift
    uint256 constant STALE_ATTRACT_RATIO = WAD * 112 / 100; // attract = protect * 1.12

    // ── Trade-aligned toxicity boost ──
    uint256 constant TRADE_ALIGNED_COEF = 2500 * BPS;       // boost = coef * tradeRatio

    // ══════════════════════════════════════════════════════════════════════════
    // Lifecycle
    // ══════════════════════════════════════════════════════════════════════════

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256, uint256)
    {
        uint256 initialFee = FEE_FLOOR;
        slots[SLOT_BID_FEE]   = initialFee;
        slots[SLOT_ASK_FEE]   = initialFee;

        // Initial fair price estimate = initial spot price
        slots[SLOT_PHAT]      = wdiv(initialY, initialX);

        // Initial sigma estimate ~0.095% (nominal midpoint)
        slots[SLOT_SIGMA_HAT] = 950000000000000;  // 0.00095 WAD

        // Initial lambda ~0.8
        slots[SLOT_LAMBDA_HAT] = 800000000000000000; // 0.8 WAD

        // Initial size ~0.2% of reserves
        slots[SLOT_SIZE_HAT]  = WAD / 500;

        // Dir state centered at WAD (neutral)
        slots[SLOT_DIR_STATE] = WAD;

        return (initialFee, initialFee);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // Main fee-setting logic
    // ══════════════════════════════════════════════════════════════════════════

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        // ── Load state ──
        uint256 bidFee     = slots[SLOT_BID_FEE];
        uint256 askFee     = slots[SLOT_ASK_FEE];
        uint256 lastTs     = slots[SLOT_LAST_TS];
        uint256 pHat       = slots[SLOT_PHAT];
        uint256 sigmaHat   = slots[SLOT_SIGMA_HAT];
        uint256 lambdaHat  = slots[SLOT_LAMBDA_HAT];
        uint256 sizeHat    = slots[SLOT_SIZE_HAT];
        uint256 toxEma     = slots[SLOT_TOX_EMA];
        uint256 dirState   = slots[SLOT_DIR_STATE];
        uint256 actEma     = slots[SLOT_ACT_EMA];
        uint256 stepCount  = slots[SLOT_STEP_COUNT];
        uint256 firstIn    = slots[SLOT_FIRST_IN];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        uint256 spot       = wdiv(trade.reserveY, trade.reserveX);

        // ──────────────────────────────────────────────────────────────────
        // 1. STATE DECAY — on new timestep, decay all EMAs toward neutral
        // ──────────────────────────────────────────────────────────────────
        if (trade.timestamp > lastTs) {
            uint256 elapsed = trade.timestamp - lastTs;
            if (elapsed > 8) elapsed = 8;

            for (uint256 i = 0; i < elapsed; i++) {
                // dirState decays toward WAD (center)
                if (dirState > WAD) {
                    dirState = dirState > WAD + DIR_DECAY_STEP
                        ? dirState - DIR_DECAY_STEP : WAD;
                } else if (dirState < WAD) {
                    dirState = dirState + DIR_DECAY_STEP > WAD
                        ? WAD : dirState + DIR_DECAY_STEP;
                }

                actEma   = actEma > ACT_DECAY_STEP ? actEma - ACT_DECAY_STEP : 0;
                sizeHat  = sizeHat > SIZE_DECAY_STEP ? sizeHat - SIZE_DECAY_STEP : 0;
                toxEma   = toxEma > TOX_DECAY_STEP ? toxEma - TOX_DECAY_STEP : 0;
            }

            // Update lambdaHat from step trade count
            // lambdaHat = lambdaHat * 0.99 + (stepTrades/elapsed) * 0.01 ... simplified:
            // Use a fixed blend from observed step density
            {
                uint256 obsRate = wdiv(stepCount * WAD, elapsed * WAD / WAD);
                if (obsRate > 2 * WAD) obsRate = 2 * WAD; // cap at 2.0
                lambdaHat = wmul(lambdaHat, WAD * 99 / 100)
                          + wmul(obsRate, WAD / 100);
            }

            // Reset per-step counters
            stepCount = 0;
            firstIn   = 0;
        }

        // ──────────────────────────────────────────────────────────────────
        // 2. PRICE ESTIMATION (pHat) with adaptive sigma-gated updates
        // ──────────────────────────────────────────────────────────────────
        {
            // Reconstruct implied price accounting for fee
            uint256 feeUsed = trade.isBuy ? bidFee : askFee;
            uint256 gamma   = WAD - feeUsed;  // 1 - fee
            uint256 pImplied;
            if (trade.isBuy) {
                pImplied = wmul(spot, gamma);
            } else {
                pImplied = wdiv(spot, gamma);
            }

            // Compute absolute return
            uint256 ret = wdiv(absDiff(pImplied, pHat), pHat);

            // Adaptive gate: tight in low vol, wide in high vol
            uint256 gate = sigmaHat * GATE_MULTIPLIER;
            if (gate < GATE_MIN) gate = GATE_MIN;

            if (ret <= gate) {
                uint256 alpha = (firstIn == 0) ? PHAT_ALPHA_FIRST : PHAT_ALPHA_REST;
                pHat    = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                firstIn = 1;
            }

            // Update sigma estimate on first trade of step
            if (firstIn == 1 && ret <= gate) {
                if (ret > WAD / 10) ret = WAD / 10; // cap at 10%
                sigmaHat = wmul(sigmaHat, SIGMA_DECAY) + wmul(ret, SIGMA_ALPHA);
            }
        }

        // ──────────────────────────────────────────────────────────────────
        // 3. SIGNAL UPDATES — directional pressure, activity, size, toxicity
        // ──────────────────────────────────────────────────────────────────
        if (tradeRatio > SIGNAL_THRESHOLD) {
            // Directional push
            uint256 push = tradeRatio * DIR_PUSH_SCALE;
            if (push > DIR_PUSH_CAP) push = DIR_PUSH_CAP;
            if (trade.isBuy) {
                dirState = dirState + push;
                if (dirState > 2 * WAD) dirState = 2 * WAD;
            } else {
                if (dirState > push) {
                    dirState = dirState - push;
                } else {
                    dirState = 0;
                }
            }

            // Activity EMA
            actEma = wmul(actEma, WAD - ACT_ALPHA) + wmul(tradeRatio, ACT_ALPHA);

            // Size EMA (capped)
            sizeHat = wmul(sizeHat, WAD - SIZE_ALPHA) + wmul(tradeRatio, SIZE_ALPHA);
            if (sizeHat > WAD) sizeHat = WAD;
        }

        // Toxicity: |spot - pHat| / pHat
        {
            uint256 tox = wdiv(absDiff(spot, pHat), pHat);
            if (tox > TOX_CAP) tox = TOX_CAP;
            toxEma = wmul(toxEma, WAD - TOX_ALPHA) + wmul(tox, TOX_ALPHA);
        }

        stepCount++;

        // ──────────────────────────────────────────────────────────────────
        // 4. FEE COMPUTATION
        // ──────────────────────────────────────────────────────────────────

        // 4a. Base fee: volatility + arrival rate + flow components
        uint256 flowRate = wmul(lambdaHat, sizeHat);
        uint256 fBase = FEE_FLOOR
            + wmul(SIGMA_COEF * BPS, sigmaHat) / WAD
            + wmul(LAMBDA_COEF, lambdaHat)
            + wmul(FLOW_COEF, flowRate);

        // 4b. Toxicity components (linear + quadratic + cubic)
        uint256 tox2  = wmul(toxEma, toxEma);
        uint256 tox3  = wmul(tox2, toxEma);
        uint256 toxComponent =
            wmul(TOX_LINEAR_COEF, toxEma)
          + wmul(TOX_QUAD_COEF,  tox2)
          + wmul(TOX_CUBIC_COEF,  tox3);

        // 4c. Activity + sigma*tox interaction
        uint256 interaction = wmul(SIGMA_TOX_COEF, wmul(sigmaHat, toxEma));

        uint256 fMid = fBase + toxComponent + wmul(ACTIVITY_COEF, actEma) + interaction;

        // 4d. Directional skew
        {
            uint256 dirDev = dirState > WAD ? dirState - WAD : WAD - dirState;
            bool sellPressure = dirState >= WAD; // more buys than sells = sell pressure
            uint256 skew = wmul(SKEW_BASE_COEF, dirDev)
                         + wmul(SKEW_TOX_COEF, wmul(dirDev, toxEma));

            if (sellPressure) {
                // Protect ask (AMM sells X) — widen
                askFee = fMid + skew;
                // Attract bid (AMM buys X) — discount
                bidFee = fMid > skew ? fMid - skew : FEE_FLOOR;
            } else {
                // Protect bid — widen
                bidFee = fMid + skew;
                // Attract ask — discount
                askFee = fMid > skew ? fMid - skew : FEE_FLOOR;
            }
        }

        // 4e. Asymmetric stale direction
        {
            uint256 staleShift = wmul(STALE_SHIFT_BASE, toxEma);
            uint256 attractShift = wmul(staleShift, STALE_ATTRACT_RATIO);

            if (spot >= pHat) {
                // Spot >= fair → overpricing X → protect bid, attract ask (sell)
                bidFee += staleShift;
                askFee = askFee > attractShift ? askFee - attractShift : FEE_FLOOR;
            } else {
                // Spot < fair → underpricing X → protect ask, attract bid (buy)
                askFee += staleShift;
                bidFee = bidFee > attractShift ? bidFee - attractShift : FEE_FLOOR;
            }
        }

        // 4f. Trade-aligned toxicity boost
        {
            bool tradeAligned = (trade.isBuy && spot >= pHat)
                             || (!trade.isBuy && spot < pHat);
            if (tradeAligned) {
                uint256 boost = wmul(TRADE_ALIGNED_COEF, tradeRatio);
                if (trade.isBuy) {
                    bidFee += boost;  // buying into overpriced → arb, widen bid
                } else {
                    askFee += boost;  // selling into underpriced → arb, widen ask
                }
            }
        }

        // 4g. Final clamp
        bidFee = clampFee(bidFee);
        askFee = clampFee(askFee);

        // ── Store updated state ──
        slots[SLOT_BID_FEE]    = bidFee;
        slots[SLOT_ASK_FEE]    = askFee;
        slots[SLOT_LAST_TS]    = trade.timestamp;
        slots[SLOT_PHAT]       = pHat;
        slots[SLOT_SIGMA_HAT]  = sigmaHat;
        slots[SLOT_LAMBDA_HAT] = lambdaHat;
        slots[SLOT_SIZE_HAT]   = sizeHat;
        slots[SLOT_TOX_EMA]    = toxEma;
        slots[SLOT_DIR_STATE]  = dirState;
        slots[SLOT_ACT_EMA]    = actEma;
        slots[SLOT_STEP_COUNT] = stepCount;
        slots[SLOT_FIRST_IN]   = firstIn;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "SigmaAdaptive";
    }
}
