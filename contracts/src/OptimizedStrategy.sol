// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Optimized Strategy - Dynamic fee switching
/// @notice High fees normally, very low after arb to steal retail
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_FEE = 0;
    uint256 constant SLOT_LAST_TS = 1;
    uint256 constant SLOT_MODE = 2;  // 0 = defensive, 1 = aggressive

    // Optimal static level
    uint256 constant DEFENSIVE_FEE = 78 * BPS;

    // Aggressive retail capture (way under normalizer)
    uint256 constant AGGRESSIVE_FEE = 20 * BPS;

    // Thresholds
    uint256 constant ARB_THRESHOLD = WAD / 40;  // 2.5% = arb
    uint256 constant RETAIL_THRESHOLD = WAD / 150;  // 0.67% = retail

    // Time to stay aggressive after arb
    uint256 constant AGGRESSIVE_STEPS = 5;

    // Raise rate back to defensive
    uint256 constant RAISE_PER_STEP = 12 * BPS;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_FEE] = DEFENSIVE_FEE;
        return (DEFENSIVE_FEE, DEFENSIVE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 fee = slots[SLOT_FEE];
        uint256 mode = slots[SLOT_MODE];
        uint256 lastTs = slots[SLOT_LAST_TS];

        // Trade analysis
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        bool isArb = tradeRatio > ARB_THRESHOLD;
        bool isRetail = tradeRatio < RETAIL_THRESHOLD;

        // Time since last trade
        uint256 stepsPassed = trade.timestamp > lastTs ? trade.timestamp - lastTs : 0;
        slots[SLOT_LAST_TS] = trade.timestamp;

        if (isArb) {
            // Just got arb'd - price now corrected
            // Go AGGRESSIVE to steal retail from normalizer
            fee = AGGRESSIVE_FEE;
            mode = 1;  // Aggressive mode
        } else if (mode == 1) {
            // In aggressive mode - raise fees over time
            if (stepsPassed > 0) {
                uint256 raise = stepsPassed * RAISE_PER_STEP;
                fee = fee + raise;
                if (fee >= DEFENSIVE_FEE) {
                    fee = DEFENSIVE_FEE;
                    mode = 0;  // Back to defensive
                }
            }
        } else {
            // Defensive mode - time-based raise if needed
            if (fee < DEFENSIVE_FEE && stepsPassed > 0) {
                uint256 raise = stepsPassed * RAISE_PER_STEP;
                fee = fee + raise > DEFENSIVE_FEE ? DEFENSIVE_FEE : fee + raise;
            }
        }

        // Inventory protection (less aggressive)
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        uint256 bidFee = fee;
        uint256 askFee = fee;

        if (ratio < WAD * 75 / 100) {
            // X very depleted - increase ask
            askFee = askFee + 20 * BPS;
            if (askFee > MAX_FEE) askFee = MAX_FEE;
        } else if (ratio > WAD * 125 / 100) {
            // X very excess - increase bid
            bidFee = bidFee + 20 * BPS;
            if (bidFee > MAX_FEE) bidFee = MAX_FEE;
        }

        slots[SLOT_FEE] = fee;
        slots[SLOT_MODE] = mode;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "OptimizedV1";
    }
}
