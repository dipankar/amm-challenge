// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title All-In Strategy
/// @notice Maximizes retail capture with extreme fee levels
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_FEE = 0;
    uint256 constant SLOT_LAST_TS = 1;
    uint256 constant SLOT_TRADES = 2;
    uint256 constant SLOT_ARBS = 3;

    // Start very high to protect from initial arbs
    uint256 constant INITIAL_FEE = 95 * BPS;

    // After detecting retail pattern, go low
    uint256 constant RETAIL_FEE = 45 * BPS;  // Still profitable but competitive

    // After arb, spike massively
    uint256 constant ARB_FEE = 98 * BPS;

    // Thresholds
    uint256 constant ARB_SIZE = WAD / 25;  // 4% = arb

    // Decay per step
    uint256 constant DECAY = 5 * BPS;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_FEE] = INITIAL_FEE;
        return (INITIAL_FEE, INITIAL_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 fee = slots[SLOT_FEE];
        uint256 trades = slots[SLOT_TRADES] + 1;
        uint256 arbs = slots[SLOT_ARBS];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        bool isArb = tradeRatio > ARB_SIZE;

        if (isArb) {
            arbs = arbs + 1;
            fee = ARB_FEE;
        } else {
            // Retail - decay toward competitive level
            if (fee > RETAIL_FEE) {
                fee = fee > RETAIL_FEE + DECAY ? fee - DECAY : RETAIL_FEE;
            }
        }

        // After warmup, adapt based on arb ratio
        if (trades > 50) {
            uint256 arbRatio = wdiv(arbs * WAD, trades * WAD);
            if (arbRatio > WAD / 3) {
                // High arb environment (>33%) - stay defensive
                if (fee < 70 * BPS) fee = 70 * BPS;
            } else if (arbRatio < WAD / 10) {
                // Low arb environment (<10%) - be aggressive
                if (fee > 50 * BPS && !isArb) fee = 50 * BPS;
            }
        }

        slots[SLOT_FEE] = fee;
        slots[SLOT_TRADES] = trades;
        slots[SLOT_ARBS] = arbs;

        return (fee, fee);
    }

    function getName() external pure override returns (string memory) {
        return "AllInStrategy";
    }
}
