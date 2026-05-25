// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Winning V5 Strategy - Maximum margin
/// @notice Extreme arb protection, ultra-competitive for retail
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;
    uint256 constant SLOT_EWMA = 3;

    // Lower base for more retail capture
    uint256 constant BASE_FEE = 24 * BPS;

    // Extreme post-arb spike
    uint256 constant POST_ARB_FEE = 65 * BPS;

    // Very sensitive
    uint256 constant ARB_THRESHOLD = WAD / 50;  // 2%

    // Ultra fast decay
    uint256 constant DECAY_PER_STEP = 7 * BPS;

    // Ultra competitive for retail
    uint256 constant RETAIL_FEE = 20 * BPS;

    // EWMA
    uint256 constant ALPHA = WAD / 6;

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
        bool isArb = tradeRatio > ARB_THRESHOLD || tradeRatio > ewma * 5;

        if (isArb) {
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;

            // Strong asymmetric protection
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 15 * BPS);
            } else {
                askFee = clampFee(askFee + 15 * BPS);
            }
        } else if (tradeRatio < WAD / 250) {  // <0.4% = tiny trade
            // Ultra competitive for small trades
            bidFee = RETAIL_FEE;
            askFee = RETAIL_FEE;
        } else if (tradeRatio < ewma / 2) {
            // Likely retail
            if (bidFee > BASE_FEE) bidFee = BASE_FEE - 2 * BPS;
            if (askFee > BASE_FEE) askFee = BASE_FEE - 2 * BPS;
        }

        // Inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 70 / 100) {
            askFee = clampFee(askFee + 15 * BPS);
        } else if (ratio > WAD * 130 / 100) {
            bidFee = clampFee(bidFee + 15 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "WinningV5";
    }
}
