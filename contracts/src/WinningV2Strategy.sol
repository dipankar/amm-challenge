// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Winning V2 Strategy - Optimized to beat normalizer
/// @notice Based on discovery that 25 bps beats normalizer by +13 margin
/// @dev Key insight: we compete FOR retail, not against arb
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;

    // Optimal base fee (slightly under normalizer to win retail)
    uint256 constant BASE_FEE = 25 * BPS;

    // After arb, raise fees but stay under high levels
    // (Going too high gives normalizer MORE retail)
    uint256 constant POST_ARB_FEE = 38 * BPS;

    // Arb detection
    uint256 constant ARB_THRESHOLD = WAD / 30;  // ~3.3%

    // Fast decay to get back to competitive
    uint256 constant DECAY_PER_STEP = 3 * BPS;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 lastTs = slots[SLOT_LAST_TS];

        // Time decay
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 50) {
                uint256 decay = steps * DECAY_PER_STEP;
                if (bidFee > BASE_FEE) {
                    bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
                }
                if (askFee > BASE_FEE) {
                    askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
                }
            }
        }
        slots[SLOT_LAST_TS] = trade.timestamp;

        // Arb detection
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        if (tradeRatio > ARB_THRESHOLD) {
            // Arb detected - raise fees moderately
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;

            // Asymmetric: protect the side that was hit more
            if (trade.isBuy) {
                bidFee = bidFee + 5 * BPS;
            } else {
                askFee = askFee + 5 * BPS;
            }
        }

        // Light inventory protection (don't go too high)
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 85 / 100) {
            // X depleted
            if (askFee < 30 * BPS) askFee = 30 * BPS;
        } else if (ratio > WAD * 115 / 100) {
            // X excess
            if (bidFee < 30 * BPS) bidFee = 30 * BPS;
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "WinningV2";
    }
}
