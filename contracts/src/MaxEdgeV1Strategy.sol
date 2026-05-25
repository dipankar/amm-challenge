// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title MaxEdge V1 - Maximize absolute edge with competitive base
/// @notice Low base fees to capture volume, extremely high arb fees to extract value
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;

    // Competitive base to win volume
    uint256 constant BASE_FEE = 28 * BPS;

    // MAXIMUM arb fee - extract as much as possible
    uint256 constant POST_ARB_FEE = MAX_FEE;  // 10% = 1000 bps

    // Very sensitive arb detection
    uint256 constant ARB_THRESHOLD = WAD / 50;  // 2%

    // Moderate decay
    uint256 constant DECAY_PER_STEP = 3 * BPS;

    // EWMA smoothing
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

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Update EWMA
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        // Time decay toward base
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

        // Arb detection - be aggressive
        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 3;

        if (isArb) {
            // MAXIMUM fees after arb
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;
        } else if (tradeRatio < ewma / 2) {
            // Small trade = retail, be competitive
            bidFee = BASE_FEE - 2 * BPS;
            askFee = BASE_FEE - 2 * BPS;
        }

        // Inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 80 / 100) {
            askFee = clampFee(askFee + 20 * BPS);
        } else if (ratio > WAD * 120 / 100) {
            bidFee = clampFee(bidFee + 20 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "MaxEdgeV1";
    }
}
