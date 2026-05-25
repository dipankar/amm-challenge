// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Winning V3 Strategy - Maximum margin against normalizer
/// @notice Aggressive arb protection while staying competitive for retail
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;

    // Competitive base (slightly under normalizer)
    uint256 constant BASE_FEE = 26 * BPS;

    // After arb spike (but not so high we lose retail)
    uint256 constant POST_ARB_FEE = 45 * BPS;

    // Arb detection - be sensitive
    uint256 constant ARB_THRESHOLD = WAD / 40;  // 2.5%

    // Fast decay
    uint256 constant DECAY_PER_STEP = 4 * BPS;

    // EWMA for volatility
    uint256 constant ALPHA = WAD / 10;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_EWMA] = WAD / 100;
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
        uint256 ewma = slots[SLOT_EWMA];

        // Trade size
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        // Time decay toward base
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 30) {
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

        // Arb detection with adaptive threshold
        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;

        if (isArb) {
            // Spike both fees
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;

            // Extra protection on hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 8 * BPS);
            } else {
                askFee = clampFee(askFee + 8 * BPS);
            }
        } else if (tradeRatio < ewma / 2) {
            // Definitely retail - be extra competitive
            if (bidFee > 24 * BPS) bidFee = 24 * BPS;
            if (askFee > 24 * BPS) askFee = 24 * BPS;
        }

        // Inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 80 / 100) {
            askFee = clampFee(askFee + 8 * BPS);
        } else if (ratio > WAD * 120 / 100) {
            bidFee = clampFee(bidFee + 8 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "WinningV3";
    }
}
