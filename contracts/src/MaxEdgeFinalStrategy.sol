// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title MaxEdge Final Strategy - Optimized for maximum absolute edge
/// @notice High base fee with arb spikes and fast decay
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;

    // Optimized parameters for max edge
    uint256 constant BASE_FEE = 55 * BPS;      // 0.55%
    uint256 constant POST_ARB_FEE = 125 * BPS; // 1.25%
    uint256 constant ARB_THRESHOLD = WAD / 30; // 3.33%
    uint256 constant DECAY_PER_STEP = 27 * BPS;
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

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        // Time decay
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

        // Arb detection
        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;

        if (isArb) {
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;
            // Extra protection on hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 20 * BPS);
            } else {
                askFee = clampFee(askFee + 20 * BPS);
            }
        } else if (tradeRatio < ewma / 3) {
            // Small retail trade - slightly lower fees
            bidFee = BASE_FEE - 3 * BPS;
            askFee = BASE_FEE - 3 * BPS;
        }

        // Inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 75 / 100) {
            askFee = clampFee(askFee + 15 * BPS);
        } else if (ratio > WAD * 125 / 100) {
            bidFee = clampFee(bidFee + 15 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "MaxEdgeFinal";
    }
}
