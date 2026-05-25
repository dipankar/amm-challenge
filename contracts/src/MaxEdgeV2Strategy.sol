// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title MaxEdge V2 - Balance volume capture with profit extraction
/// @notice Higher base than WinningV4 to extract more from each trade
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;

    // Push base higher - extract more but still competitive
    uint256 constant BASE_FEE = 29 * BPS;

    // Higher arb fee to extract more
    uint256 constant POST_ARB_FEE = 80 * BPS;

    // Arb detection
    uint256 constant ARB_THRESHOLD = WAD / 50;  // 2%

    // Very fast decay to recover retail quickly
    uint256 constant DECAY_PER_STEP = 10 * BPS;

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

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        // Very fast decay
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 20) {
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

            // Extra on hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 15 * BPS);
            } else {
                askFee = clampFee(askFee + 15 * BPS);
            }
        } else if (tradeRatio < ewma / 3) {
            // Very small trade = definitely retail
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
        return "MaxEdgeV2";
    }
}
