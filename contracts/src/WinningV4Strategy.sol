// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Winning V4 Strategy - Pushing the limits
/// @notice Even more aggressive arb protection while staying retail-competitive
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;
    uint256 constant SLOT_ARB_COUNT = 4;
    uint256 constant SLOT_TOTAL_COUNT = 5;

    // Slightly higher base to capture more spread
    uint256 constant BASE_FEE = 27 * BPS;

    // More aggressive post-arb spike
    uint256 constant POST_ARB_FEE = 55 * BPS;

    // Very sensitive arb detection
    uint256 constant ARB_THRESHOLD = WAD / 50;  // 2%

    // Faster decay to recover retail
    uint256 constant DECAY_PER_STEP = 5 * BPS;

    // Super competitive for known retail
    uint256 constant RETAIL_FEE = 22 * BPS;

    // EWMA
    uint256 constant ALPHA = WAD / 8;

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
        uint256 arbCount = slots[SLOT_ARB_COUNT];
        uint256 totalCount = slots[SLOT_TOTAL_COUNT] + 1;

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        // Time decay
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 25) {
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
        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 4;

        if (isArb) {
            arbCount = arbCount + 1;
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;

            // Extra on hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 12 * BPS);
            } else {
                askFee = clampFee(askFee + 12 * BPS);
            }
        } else if (tradeRatio < WAD / 200) {  // Very small trade (<0.5%)
            // Definitely retail - be ultra competitive
            bidFee = RETAIL_FEE;
            askFee = RETAIL_FEE;
        } else if (tradeRatio < ewma / 2) {
            // Likely retail - be competitive
            if (bidFee > BASE_FEE - 2 * BPS) bidFee = BASE_FEE - 2 * BPS;
            if (askFee > BASE_FEE - 2 * BPS) askFee = BASE_FEE - 2 * BPS;
        }

        // Inventory protection (moderate)
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 75 / 100) {
            askFee = clampFee(askFee + 12 * BPS);
        } else if (ratio > WAD * 125 / 100) {
            bidFee = clampFee(bidFee + 12 * BPS);
        }

        // Adaptive: if seeing lots of arbs, stay higher
        slots[SLOT_ARB_COUNT] = arbCount;
        slots[SLOT_TOTAL_COUNT] = totalCount;

        if (totalCount > 100) {
            uint256 arbRatio = wdiv(arbCount * WAD, totalCount * WAD);
            if (arbRatio > WAD / 4) {  // >25% arbs
                // High arb environment - be more defensive
                if (bidFee < 28 * BPS) bidFee = 28 * BPS;
                if (askFee < 28 * BPS) askFee = 28 * BPS;
            }
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "WinningV4";
    }
}
