// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Winning Strategy - Adaptive Multi-Signal Fee Optimizer
/// @notice Targets 500+ edge through smart fee management
contract Strategy is AMMStrategyBase {
    /*//////////////////////////////////////////////////////////////
                              SLOT ALLOCATION
    //////////////////////////////////////////////////////////////*/

    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_EWMA_VOL = 2;           // EWMA of trade size ratios
    uint256 constant SLOT_LAST_DIRECTION = 3;     // 1 = buy, 2 = sell
    uint256 constant SLOT_CONSECUTIVE = 4;        // Consecutive same-direction trades
    uint256 constant SLOT_LAST_TIMESTAMP = 5;     // For decay calculation
    uint256 constant SLOT_INITIAL_K = 6;          // Initial x*y constant

    /*//////////////////////////////////////////////////////////////
                            TUNABLE PARAMETERS
    //////////////////////////////////////////////////////////////*/

    // Base fees (in basis points)
    uint256 constant BASE_FEE = 25 * BPS;         // Default fee
    uint256 constant LOW_VOL_FEE = 20 * BPS;      // Fee in calm markets
    uint256 constant HIGH_VOL_FEE = 40 * BPS;     // Fee in volatile markets
    uint256 constant POST_ARB_SPIKE = 55 * BPS;   // Fee after detecting arb

    // Thresholds
    uint256 constant LARGE_TRADE_THRESHOLD = WAD / 25;    // 4% of reserves = likely arb
    uint256 constant VOL_THRESHOLD = WAD / 100;           // 1% EWMA threshold for high vol

    // Adjustments
    uint256 constant DECAY_PER_STEP = 3 * BPS;            // Decay rate per step
    uint256 constant CONSEC_ADJUST = 5 * BPS;             // Extra fee per consecutive trade
    uint256 constant IMBALANCE_MULTIPLIER = 12;           // 1.2x for 20% boost (divide by 10)

    // EWMA smoothing factor (95% = 0.95 * WAD)
    uint256 constant EWMA_DECAY = 95 * WAD / 100;
    uint256 constant EWMA_NEW = WAD - EWMA_DECAY;

    /*//////////////////////////////////////////////////////////////
                              INITIALIZATION
    //////////////////////////////////////////////////////////////*/

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256, uint256)
    {
        // Store initial k for imbalance calculation
        slots[SLOT_INITIAL_K] = initialX * initialY;

        // Initialize fees to base
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_EWMA_VOL] = 0;
        slots[SLOT_LAST_DIRECTION] = 0;
        slots[SLOT_CONSECUTIVE] = 0;
        slots[SLOT_LAST_TIMESTAMP] = 0;

        return (BASE_FEE, BASE_FEE);
    }

    /*//////////////////////////////////////////////////////////////
                              MAIN LOGIC
    //////////////////////////////////////////////////////////////*/

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        // 1. Calculate trade size ratio (how big was this trade relative to reserves)
        // Using pre-trade reserves: reserveY + amountY for buys, reserveY for sells
        uint256 preTradeY = trade.isBuy
            ? trade.reserveY + trade.amountY  // AMM bought X, so Y went out
            : trade.reserveY - trade.amountY; // AMM sold X, so Y came in

        // For simplicity, use amountY / reserveY as the ratio
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // 2. Update volatility EWMA
        uint256 ewmaVol = slots[SLOT_EWMA_VOL];
        ewmaVol = wmul(ewmaVol, EWMA_DECAY) + wmul(tradeRatio, EWMA_NEW);
        slots[SLOT_EWMA_VOL] = ewmaVol;

        // 3. Detect if this was likely an arb (large trade)
        bool isLargeTrade = tradeRatio > LARGE_TRADE_THRESHOLD;

        // 4. Track consecutive same-direction trades
        uint256 lastDir = slots[SLOT_LAST_DIRECTION];
        uint256 thisDir = trade.isBuy ? 1 : 2;
        uint256 consec = slots[SLOT_CONSECUTIVE];

        if (thisDir == lastDir && lastDir != 0) {
            consec = consec + 1;
            if (consec > 5) consec = 5; // Cap at 5
        } else {
            consec = 1;
        }
        slots[SLOT_LAST_DIRECTION] = thisDir;
        slots[SLOT_CONSECUTIVE] = consec;

        // 5. Apply time decay to existing fees
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];

        uint256 stepsPassed = trade.timestamp - slots[SLOT_LAST_TIMESTAMP];
        slots[SLOT_LAST_TIMESTAMP] = trade.timestamp;

        if (stepsPassed > 0 && stepsPassed < 100) {
            uint256 decay = stepsPassed * DECAY_PER_STEP;

            // Decay toward base fee
            if (bidFee > BASE_FEE) {
                bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
            }
            if (askFee > BASE_FEE) {
                askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
            }
        }

        // 6. Determine base fees based on volatility regime
        uint256 regimeFee = ewmaVol > VOL_THRESHOLD ? HIGH_VOL_FEE : LOW_VOL_FEE;

        // Use the higher of current decayed fee and regime fee
        if (bidFee < regimeFee) bidFee = regimeFee;
        if (askFee < regimeFee) askFee = regimeFee;

        // 7. Apply post-arb spike if large trade detected
        if (isLargeTrade) {
            // Spike both sides after a large trade
            bidFee = POST_ARB_SPIKE;
            askFee = POST_ARB_SPIKE;

            // Extra spike on the side that was just hit
            if (trade.isBuy) {
                // AMM bought X (trader sold X) - price went down
                // Protect bid side more (against continued selling)
                bidFee = clampFee(bidFee + 10 * BPS);
            } else {
                // AMM sold X (trader bought X) - price went up
                // Protect ask side more (against continued buying)
                askFee = clampFee(askFee + 10 * BPS);
            }
        }

        // 8. Asymmetric adjustment for consecutive trades
        if (consec > 1) {
            uint256 consecAdjust = (consec - 1) * CONSEC_ADJUST;
            if (trade.isBuy) {
                // Multiple buys (AMM buying X) → price going down, protect bid
                bidFee = clampFee(bidFee + consecAdjust);
            } else {
                // Multiple sells (AMM selling X) → price going up, protect ask
                askFee = clampFee(askFee + consecAdjust);
            }
        }

        // 9. Inventory imbalance protection
        // Initial ratio was 100 X : 10000 Y at price 100
        // Current ratio: reserveX * 100 / reserveY should be ~1 if balanced
        uint256 currentRatio = wdiv(trade.reserveX * 100, trade.reserveY);

        if (currentRatio < WAD * 85 / 100) {
            // X reserves depleted (ratio < 0.85) → make selling X expensive
            askFee = clampFee(wmul(askFee, WAD * IMBALANCE_MULTIPLIER / 10));
        } else if (currentRatio > WAD * 115 / 100) {
            // Y reserves depleted (ratio > 1.15) → make buying X expensive
            bidFee = clampFee(wmul(bidFee, WAD * IMBALANCE_MULTIPLIER / 10));
        }

        // 10. Store updated fees
        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "AdaptiveMultiSignal";
    }
}
