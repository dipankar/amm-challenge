// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Regime Detection Strategy V2
/// @notice More aggressive regime adaptation with inventory management
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_EWMA_SIZE = 2;
    uint256 constant SLOT_LARGE_COUNT = 3;
    uint256 constant SLOT_TOTAL_COUNT = 4;
    uint256 constant SLOT_STEPS = 5;

    // Wider fee range
    uint256 constant HIGH_VOL_FEE = 98 * BPS;   // Near max in high vol
    uint256 constant BASE_FEE = 75 * BPS;       // Default
    uint256 constant LOW_VOL_FEE = 50 * BPS;    // More competitive in low vol

    // Thresholds
    uint256 constant LARGE_TRADE = WAD / 35;    // ~2.9%

    // EWMA
    uint256 constant ALPHA = WAD / 15;  // ~7% weight

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_EWMA_SIZE] = WAD / 50;
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 ewmaSize = slots[SLOT_EWMA_SIZE];
        uint256 largeCount = slots[SLOT_LARGE_COUNT];
        uint256 totalCount = slots[SLOT_TOTAL_COUNT];
        uint256 steps = slots[SLOT_STEPS] + 1;
        slots[SLOT_STEPS] = steps;

        // Trade analysis
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        bool isLarge = tradeRatio > LARGE_TRADE;

        // Update EWMA
        ewmaSize = wmul(ewmaSize, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA_SIZE] = ewmaSize;

        // Update counters
        totalCount = totalCount + 1;
        if (isLarge) largeCount = largeCount + 1;
        slots[SLOT_LARGE_COUNT] = largeCount;
        slots[SLOT_TOTAL_COUNT] = totalCount;

        // Determine regime after warmup
        uint256 baseFee = BASE_FEE;
        if (totalCount > 20) {
            uint256 largeRatio = wdiv(largeCount * WAD, totalCount * WAD);

            if (largeRatio > WAD * 30 / 100) {
                // Very high vol (>30% large trades)
                baseFee = HIGH_VOL_FEE;
            } else if (largeRatio > WAD * 20 / 100) {
                // High vol
                baseFee = 90 * BPS;
            } else if (largeRatio < WAD * 10 / 100) {
                // Low vol
                baseFee = LOW_VOL_FEE;
            } else if (largeRatio < WAD * 15 / 100) {
                // Medium-low vol
                baseFee = 65 * BPS;
            }
        }

        uint256 bidFee = baseFee;
        uint256 askFee = baseFee;

        // Short-term spike after large trade
        if (isLarge) {
            bidFee = clampFee(bidFee + 15 * BPS);
            askFee = clampFee(askFee + 15 * BPS);
        }

        // Inventory management
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 80 / 100) {
            // X depleted
            askFee = clampFee(wmul(askFee, WAD * 125 / 100));
        } else if (ratio > WAD * 120 / 100) {
            // X excess
            bidFee = clampFee(wmul(bidFee, WAD * 125 / 100));
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "RegimeV2";
    }
}
