// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Counter Strategy - Opposite logic
/// @notice High after arb (more may come), low after small trades (calm)
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_FEE = 0;
    uint256 constant SLOT_LAST_TS = 1;
    uint256 constant SLOT_SMALL_COUNT = 2;  // Consecutive small trades

    // Fee levels
    uint256 constant HIGH_FEE = 85 * BPS;  // After arb
    uint256 constant MED_FEE = 65 * BPS;   // Default
    uint256 constant LOW_FEE = 40 * BPS;   // After calm period

    // Thresholds
    uint256 constant LARGE_TRADE = WAD / 30;   // 3.3% = arb
    uint256 constant SMALL_TRADE = WAD / 100;  // 1% = retail

    // Need 3 consecutive small trades to go low
    uint256 constant SMALL_STREAK = 3;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_FEE] = MED_FEE;
        return (MED_FEE, MED_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 fee = slots[SLOT_FEE];
        uint256 smallCount = slots[SLOT_SMALL_COUNT];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        if (tradeRatio > LARGE_TRADE) {
            // Large trade - likely arb, more may follow
            fee = HIGH_FEE;
            smallCount = 0;
        } else if (tradeRatio < SMALL_TRADE) {
            // Small trade - likely retail, market calming
            smallCount = smallCount + 1;
            if (smallCount >= SMALL_STREAK) {
                // Calm period confirmed - go competitive
                fee = LOW_FEE;
            } else {
                // Slowly lower toward low fee
                if (fee > MED_FEE) {
                    fee = fee - 5 * BPS;
                }
            }
        } else {
            // Medium trade - drift toward medium fee
            smallCount = 0;
            if (fee > MED_FEE) {
                fee = fee - 3 * BPS;
            } else if (fee < MED_FEE) {
                fee = fee + 3 * BPS;
            }
        }

        slots[SLOT_FEE] = fee;
        slots[SLOT_SMALL_COUNT] = smallCount;

        return (fee, fee);
    }

    function getName() external pure override returns (string memory) {
        return "CounterStrategy";
    }
}
