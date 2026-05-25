// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Hybrid Strategy - Optimized for 500+ edge
/// @notice High default with smart retail detection
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA_SIZE = 3;
    uint256 constant SLOT_TRADE_COUNT = 4;

    // Optimized fee levels based on testing
    uint256 constant DEFAULT_FEE = 80 * BPS;  // Default (optimal static)
    uint256 constant RETAIL_FEE = 35 * BPS;   // For retail capture (still good spread)
    uint256 constant ARB_PROTECT = 95 * BPS;  // Max protection after arb

    // Detection thresholds
    uint256 constant SMALL_TRADE = WAD / 200;  // 0.5% = definitely retail
    uint256 constant LARGE_TRADE = WAD / 25;   // 4% = likely arb

    // Fee dynamics
    uint256 constant RAISE_RATE = 8 * BPS;     // Per step

    // EWMA decay
    uint256 constant ALPHA = WAD / 8;  // 12.5% weight

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = DEFAULT_FEE;
        slots[SLOT_ASK_FEE] = DEFAULT_FEE;
        slots[SLOT_EWMA_SIZE] = WAD / 100;  // Start at 1% average
        return (DEFAULT_FEE, DEFAULT_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];

        // Calculate trade ratio
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA of trade sizes
        uint256 ewma = slots[SLOT_EWMA_SIZE];
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA_SIZE] = ewma;
        slots[SLOT_TRADE_COUNT] = slots[SLOT_TRADE_COUNT] + 1;

        // Classify trade
        bool isLarge = tradeRatio > LARGE_TRADE;
        bool isSmall = tradeRatio < SMALL_TRADE;
        bool isBelowAvg = tradeRatio < ewma;

        // Time-based fee increase
        uint256 lastTs = slots[SLOT_LAST_TS];
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps < 30) {
                uint256 raise = steps * RAISE_RATE;
                if (bidFee < DEFAULT_FEE) {
                    bidFee = bidFee + raise > DEFAULT_FEE ? DEFAULT_FEE : bidFee + raise;
                }
                if (askFee < DEFAULT_FEE) {
                    askFee = askFee + raise > DEFAULT_FEE ? DEFAULT_FEE : askFee + raise;
                }
            }
        }
        slots[SLOT_LAST_TS] = trade.timestamp;

        // Strategy logic
        if (isLarge) {
            // Large trade = arb. Next step could be:
            // - Another arb (price still moving) → stay protected
            // - Retail (price corrected) → could lower
            // Conservative: raise protection on hit side, lower other side
            if (trade.isBuy) {
                bidFee = ARB_PROTECT;
                askFee = RETAIL_FEE;  // Attract flow in opposite direction
            } else {
                askFee = ARB_PROTECT;
                bidFee = RETAIL_FEE;
            }
        } else if (isSmall || isBelowAvg) {
            // Small/below average = likely retail
            // Lower fees to capture more
            if (bidFee > RETAIL_FEE) bidFee = RETAIL_FEE + 10 * BPS;
            if (askFee > RETAIL_FEE) askFee = RETAIL_FEE + 10 * BPS;
        }
        // Medium trades: let time-based raise continue

        // Inventory skew protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 80 / 100) {
            // X depleted - protect ask
            if (askFee < 60 * BPS) askFee = 60 * BPS;
        } else if (ratio > WAD * 120 / 100) {
            // X excess - protect bid
            if (bidFee < 60 * BPS) bidFee = 60 * BPS;
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "HybridStrategy";
    }
}
