// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Inverted Strategy - High default, low after arb
/// @notice Start at high fees (protect from arb), drop after arb to capture retail
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;

    // High default fee (protects from arb)
    uint256 constant HIGH_FEE = 85 * BPS;

    // Low fee to capture retail (undercut normalizer)
    uint256 constant LOW_FEE = 25 * BPS;

    // Arb detection threshold
    uint256 constant ARB_THRESHOLD = WAD / 30;  // ~3.3% of reserves

    // How fast to raise fees back up
    uint256 constant RAISE_RATE = 10 * BPS;  // Per step

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = HIGH_FEE;
        slots[SLOT_ASK_FEE] = HIGH_FEE;
        return (HIGH_FEE, HIGH_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];

        // Trade size ratio
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        bool isArb = tradeRatio > ARB_THRESHOLD;

        // Time-based raise (fees climb back up over time)
        uint256 lastTs = slots[SLOT_LAST_TS];
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps < 50) {
                uint256 raise = steps * RAISE_RATE;
                if (bidFee < HIGH_FEE) {
                    bidFee = bidFee + raise > HIGH_FEE ? HIGH_FEE : bidFee + raise;
                }
                if (askFee < HIGH_FEE) {
                    askFee = askFee + raise > HIGH_FEE ? HIGH_FEE : askFee + raise;
                }
            }
        }
        slots[SLOT_LAST_TS] = trade.timestamp;

        // After arb detected, DROP fees to capture retail
        if (isArb) {
            // Drop both fees to steal retail from normalizer
            bidFee = LOW_FEE;
            askFee = LOW_FEE;
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "InvertedStrategy";
    }
}
