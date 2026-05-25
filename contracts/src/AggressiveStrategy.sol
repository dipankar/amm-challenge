// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Aggressive Strategy - Ultra-Low Base Fees with Strong Arb Protection
/// @notice Maximizes retail capture with aggressive arb spike
contract Strategy is AMMStrategyBase {
    /*//////////////////////////////////////////////////////////////
                              SLOT ALLOCATION
    //////////////////////////////////////////////////////////////*/

    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_EWMA_VOL = 2;
    uint256 constant SLOT_LAST_DIRECTION = 3;
    uint256 constant SLOT_CONSECUTIVE = 4;
    uint256 constant SLOT_LAST_TIMESTAMP = 5;

    /*//////////////////////////////////////////////////////////////
                         AGGRESSIVE PARAMETERS
    //////////////////////////////////////////////////////////////*/

    // Much lower base to dominate retail capture
    uint256 constant BASE_FEE = 18 * BPS;         // Way under 30 bps normalizer
    uint256 constant LOW_VOL_FEE = 15 * BPS;      // Very aggressive in calm
    uint256 constant HIGH_VOL_FEE = 35 * BPS;     // Still competitive in vol

    // Strong arb protection
    uint256 constant POST_ARB_SPIKE = 75 * BPS;   // Aggressive spike after arb
    uint256 constant EXTRA_SPIKE = 15 * BPS;      // Additional for direction

    // Sensitive detection
    uint256 constant LARGE_TRADE_THRESHOLD = WAD / 33;  // ~3% is large
    uint256 constant VOL_THRESHOLD = WAD / 150;         // Lower vol threshold

    // Fast recovery
    uint256 constant DECAY_PER_STEP = 5 * BPS;          // Quick decay to win retail back
    uint256 constant CONSEC_ADJUST = 8 * BPS;           // Stronger direction adjustment

    // EWMA
    uint256 constant EWMA_DECAY = 90 * WAD / 100;       // Faster adaptation
    uint256 constant EWMA_NEW = WAD - EWMA_DECAY;

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
        // 1. Trade size ratio
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // 2. Update volatility EWMA
        uint256 ewmaVol = slots[SLOT_EWMA_VOL];
        ewmaVol = wmul(ewmaVol, EWMA_DECAY) + wmul(tradeRatio, EWMA_NEW);
        slots[SLOT_EWMA_VOL] = ewmaVol;

        // 3. Detect large trade (arb)
        bool isLargeTrade = tradeRatio > LARGE_TRADE_THRESHOLD;

        // 4. Track consecutive direction
        uint256 lastDir = slots[SLOT_LAST_DIRECTION];
        uint256 thisDir = trade.isBuy ? 1 : 2;
        uint256 consec = slots[SLOT_CONSECUTIVE];
        if (thisDir == lastDir && lastDir != 0) {
            consec = consec < 5 ? consec + 1 : 5;
        } else {
            consec = 1;
        }
        slots[SLOT_LAST_DIRECTION] = thisDir;
        slots[SLOT_CONSECUTIVE] = consec;

        // 5. Time decay
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 stepsPassed = trade.timestamp > slots[SLOT_LAST_TIMESTAMP]
            ? trade.timestamp - slots[SLOT_LAST_TIMESTAMP] : 0;
        slots[SLOT_LAST_TIMESTAMP] = trade.timestamp;

        if (stepsPassed > 0 && stepsPassed < 50) {
            uint256 decay = stepsPassed * DECAY_PER_STEP;
            if (bidFee > BASE_FEE + decay) bidFee = bidFee - decay;
            else if (bidFee > BASE_FEE) bidFee = BASE_FEE;
            if (askFee > BASE_FEE + decay) askFee = askFee - decay;
            else if (askFee > BASE_FEE) askFee = BASE_FEE;
        }

        // 6. Volatility regime
        uint256 regimeFee = ewmaVol > VOL_THRESHOLD ? HIGH_VOL_FEE : LOW_VOL_FEE;
        if (bidFee < regimeFee) bidFee = regimeFee;
        if (askFee < regimeFee) askFee = regimeFee;

        // 7. Post-arb spike
        if (isLargeTrade) {
            bidFee = POST_ARB_SPIKE;
            askFee = POST_ARB_SPIKE;
            // Extra spike on hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + EXTRA_SPIKE);
            } else {
                askFee = clampFee(askFee + EXTRA_SPIKE);
            }
        }

        // 8. Consecutive adjustment
        if (consec > 1) {
            uint256 adj = (consec - 1) * CONSEC_ADJUST;
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + adj);
            } else {
                askFee = clampFee(askFee + adj);
            }
        }

        // 9. Inventory protection
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        if (ratio < WAD * 80 / 100) {
            askFee = clampFee(wmul(askFee, WAD * 130 / 100));
        } else if (ratio > WAD * 120 / 100) {
            bidFee = clampFee(wmul(bidFee, WAD * 130 / 100));
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "AggressiveCapture";
    }
}
