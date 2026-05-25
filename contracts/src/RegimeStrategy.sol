// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Regime Detection Strategy
/// @notice Adapts fees based on detected market regime
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_FEE = 0;
    uint256 constant SLOT_EWMA_SIZE = 1;
    uint256 constant SLOT_LARGE_COUNT = 2;
    uint256 constant SLOT_TOTAL_COUNT = 3;
    uint256 constant SLOT_LAST_TS = 4;

    // Base fee (slightly above optimal static)
    uint256 constant BASE_FEE = 80 * BPS;

    // Regime-based adjustments
    uint256 constant HIGH_VOL_FEE = 95 * BPS;
    uint256 constant LOW_VOL_FEE = 60 * BPS;

    // Thresholds
    uint256 constant LARGE_TRADE = WAD / 30;

    // EWMA decay
    uint256 constant ALPHA = WAD / 20;  // 5% weight on new

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_FEE] = BASE_FEE;
        slots[SLOT_EWMA_SIZE] = WAD / 50;  // 2% starting estimate
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 fee = slots[SLOT_FEE];
        uint256 ewmaSize = slots[SLOT_EWMA_SIZE];
        uint256 largeCount = slots[SLOT_LARGE_COUNT];
        uint256 totalCount = slots[SLOT_TOTAL_COUNT];

        // Trade analysis
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        bool isLarge = tradeRatio > LARGE_TRADE;

        // Update EWMA of trade sizes
        ewmaSize = wmul(ewmaSize, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA_SIZE] = ewmaSize;

        // Update counters
        totalCount = totalCount + 1;
        if (isLarge) {
            largeCount = largeCount + 1;
        }
        slots[SLOT_LARGE_COUNT] = largeCount;
        slots[SLOT_TOTAL_COUNT] = totalCount;

        // Calculate large trade ratio (proxy for volatility)
        uint256 largeRatio = totalCount > 10 ? wdiv(largeCount * WAD, totalCount * WAD) : WAD / 4;

        // Regime detection
        // High vol: more large trades → higher fees
        // Low vol: fewer large trades → can be more competitive
        if (largeRatio > WAD / 4) {
            // High volatility regime (>25% large trades)
            fee = HIGH_VOL_FEE;
        } else if (largeRatio < WAD / 10) {
            // Low volatility regime (<10% large trades)
            fee = LOW_VOL_FEE;
        } else {
            // Medium regime
            fee = BASE_FEE;
        }

        // Short-term adjustment based on recent trade
        if (isLarge) {
            // Just had large trade - bump up temporarily
            fee = fee + 10 * BPS;
            if (fee > MAX_FEE) fee = MAX_FEE;
        }

        slots[SLOT_FEE] = fee;

        return (fee, fee);
    }

    function getName() external pure override returns (string memory) {
        return "RegimeDetector";
    }
}
