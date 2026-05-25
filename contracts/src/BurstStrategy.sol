// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Burst Strategy - Spike High, Decay Fast
/// @notice Maximum protection after arb, fastest recovery for retail
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_STEPS_SINCE_ARB = 2;

    // Competitive base fee (slightly under normalizer)
    uint256 constant BASE_FEE = 27 * BPS;

    // Massive spike after arb detected
    uint256 constant ARB_SPIKE = 90 * BPS;  // 0.9% - near max

    // Very fast decay
    uint256 constant DECAY_PER_STEP = 8 * BPS;  // Recover in ~8 steps

    // Detection threshold
    uint256 constant ARB_THRESHOLD = WAD / 30;  // ~3.3% of reserves = arb

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_STEPS_SINCE_ARB] = 1000; // No recent arb
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 stepsSinceArb = slots[SLOT_STEPS_SINCE_ARB];

        // Calculate trade size ratio
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Is this an arb trade?
        bool isArb = tradeRatio > ARB_THRESHOLD;

        if (isArb) {
            // Massive spike on both sides
            bidFee = ARB_SPIKE;
            askFee = ARB_SPIKE;

            // Extra on the hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 5 * BPS);
            } else {
                askFee = clampFee(askFee + 5 * BPS);
            }
            stepsSinceArb = 0;
        } else {
            // Decay rapidly
            stepsSinceArb = stepsSinceArb + 1;

            // Fast linear decay
            uint256 targetFee = BASE_FEE;
            uint256 decay = stepsSinceArb * DECAY_PER_STEP;

            if (bidFee > targetFee) {
                if (bidFee > targetFee + decay) {
                    bidFee = bidFee - decay;
                } else {
                    bidFee = targetFee;
                }
            }

            if (askFee > targetFee) {
                if (askFee > targetFee + decay) {
                    askFee = askFee - decay;
                } else {
                    askFee = targetFee;
                }
            }
        }

        // Small inventory adjustment
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 85 / 100) {
            // X depleted
            askFee = clampFee(askFee + 10 * BPS);
        } else if (ratio > WAD * 115 / 100) {
            // X excess
            bidFee = clampFee(bidFee + 10 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;
        slots[SLOT_STEPS_SINCE_ARB] = stepsSinceArb;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "BurstStrategy";
    }
}
