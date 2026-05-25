// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Grid Search Strategy - Clean parameterized implementation
/// @notice Core insight: Spike on large trades (likely arb), decay back to competitive base
/// @dev Parameters are designed to be easily modified for grid search
contract Strategy is AMMStrategyBase {
    /*//////////////////////////////////////////////////////////////
                              STORAGE SLOTS
    //////////////////////////////////////////////////////////////*/

    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;

    /*//////////////////////////////////////////////////////////////
                         TUNABLE PARAMETERS
    //////////////////////////////////////////////////////////////*/

    // Base fee - the competitive rate to capture retail
    // Must be below normalizer (30 bps) to win retail flow
    uint256 constant BASE_FEE = 25 * BPS;

    // Post-arb spike - fee after detecting large trade
    // Higher = more protection, but lose retail during spike
    uint256 constant POST_ARB_FEE = 55 * BPS;

    // Arb threshold - trade ratio above which we classify as arb
    // Lower = more sensitive (catch more arbs, risk false positives)
    // WAD / 50 = 2%, WAD / 40 = 2.5%, WAD / 30 = 3.3%
    uint256 constant ARB_THRESHOLD = WAD / 40;  // 2.5%

    // Decay rate - how fast we return to base after spike
    // Higher = faster recovery = less retail lost during spike
    uint256 constant DECAY_PER_STEP = 5 * BPS;

    // Asymmetric protection - extra fee on the side that was just hit
    uint256 constant ASYMMETRIC_EXTRA = 10 * BPS;

    /*//////////////////////////////////////////////////////////////
                              INITIALIZATION
    //////////////////////////////////////////////////////////////*/

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
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
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 lastTs = slots[SLOT_LAST_TS];

        // 1. Calculate trade size ratio (how big relative to reserves)
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // 2. Time decay - return toward base fee
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

        // 3. Arb detection - spike if large trade
        if (tradeRatio > ARB_THRESHOLD) {
            // Spike both sides
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;

            // Asymmetric: extra protection on the side that was hit
            if (trade.isBuy) {
                // AMM bought X (trader sold X to us) - protect bid side
                bidFee = clampFee(bidFee + ASYMMETRIC_EXTRA);
            } else {
                // AMM sold X (trader bought X from us) - protect ask side
                askFee = clampFee(askFee + ASYMMETRIC_EXTRA);
            }
        }

        // 4. Store and return
        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "GridSearch";
    }
}
