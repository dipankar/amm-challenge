// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Defensive Strategy - Maximize Reserve Preservation
/// @notice Aggressive arb detection, only competitive when safe
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_EWMA_SIZE = 0;
    uint256 constant SLOT_BID_FEE = 1;
    uint256 constant SLOT_ASK_FEE = 2;
    uint256 constant SLOT_LAST_TS = 3;
    uint256 constant SLOT_TRADE_COUNT = 4;
    uint256 constant SLOT_ARB_COUNT = 5;

    // Be competitive, not aggressive
    uint256 constant BASE_FEE = 29 * BPS;  // Just under normalizer
    uint256 constant SAFE_FEE = 25 * BPS;  // When confident it's retail

    // Extreme arb protection
    uint256 constant ARB_FEE = 95 * BPS;   // Near maximum

    // Very sensitive arb detection
    uint256 constant ARB_THRESHOLD_LOW = WAD / 50;   // 2% = suspicious
    uint256 constant ARB_THRESHOLD_HIGH = WAD / 25;  // 4% = definite arb

    // Fast decay for competitiveness
    uint256 constant DECAY_RATE = 6 * BPS;

    // EWMA smoothing
    uint256 constant ALPHA = WAD / 10;  // 10% weight on new data

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_EWMA_SIZE] = WAD / 200;  // Start with 0.5% average
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];

        // Trade metrics
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA of trade sizes
        uint256 ewmaSize = slots[SLOT_EWMA_SIZE];
        ewmaSize = wmul(ewmaSize, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA_SIZE] = ewmaSize;

        // Update trade count
        uint256 tradeCount = slots[SLOT_TRADE_COUNT] + 1;
        slots[SLOT_TRADE_COUNT] = tradeCount;

        // Time decay
        uint256 lastTs = slots[SLOT_LAST_TS];
        uint256 steps = 0;
        if (trade.timestamp > lastTs) {
            steps = trade.timestamp - lastTs;
        }
        slots[SLOT_LAST_TS] = trade.timestamp;

        // Apply decay
        if (steps > 0 && steps < 50) {
            uint256 decay = steps * DECAY_RATE;
            if (bidFee > BASE_FEE) {
                bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
            }
            if (askFee > BASE_FEE) {
                askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
            }
        }

        // Arb detection logic
        bool definiteArb = tradeRatio > ARB_THRESHOLD_HIGH;
        bool suspiciousArb = tradeRatio > ARB_THRESHOLD_LOW;
        bool likelyRetail = tradeRatio < ewmaSize;

        if (definiteArb) {
            // Full defensive mode
            bidFee = ARB_FEE;
            askFee = ARB_FEE;
            slots[SLOT_ARB_COUNT] = slots[SLOT_ARB_COUNT] + 1;
        } else if (suspiciousArb) {
            // Partial defense - widen the side that was hit
            uint256 spike = 40 * BPS;
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + spike);
                askFee = clampFee(askFee + spike / 2);
            } else {
                askFee = clampFee(askFee + spike);
                bidFee = clampFee(bidFee + spike / 2);
            }
        } else if (likelyRetail) {
            // Confident it's retail - be more competitive
            if (bidFee > SAFE_FEE) bidFee = SAFE_FEE;
            if (askFee > SAFE_FEE) askFee = SAFE_FEE;
        }

        // Inventory protection (but less aggressive)
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 80 / 100) {
            askFee = clampFee(askFee + 15 * BPS);
        } else if (ratio > WAD * 120 / 100) {
            bidFee = clampFee(bidFee + 15 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "DefensiveArb";
    }
}
