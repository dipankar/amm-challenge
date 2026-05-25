// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Optimal Strategy - Grid Search Optimized
/// @notice Parameters found via systematic grid search (200 sims each)
/// @dev Key insight: 1% threshold catches arbs without false positives on retail
///
/// Grid search results (margin over 30 bps normalizer):
///   base=24, post=175, arb=1%, decay=12 => margin +65.32, edge ~390
///   base=24, post=150, arb=0.83%, decay=12 => margin +65.32, edge ~394
///
/// Core strategy:
/// 1. Undercut normalizer with 24 bps base to capture retail
/// 2. Spike to 175 bps when trade > 1% of reserves (likely arb)
/// 3. Decay 12 bps/step back to base (fast recovery)
/// 4. Asymmetric +10 bps on the side that was hit
contract Strategy is AMMStrategyBase {
    /*//////////////////////////////////////////////////////////////
                              STORAGE SLOTS
    //////////////////////////////////////////////////////////////*/

    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TS = 2;

    /*//////////////////////////////////////////////////////////////
                      OPTIMIZED PARAMETERS
    //////////////////////////////////////////////////////////////*/

    // Base fee: undercut normalizer (30 bps) to capture retail flow
    uint256 constant BASE_FEE = 24 * BPS;

    // Post-arb spike: strong protection after detecting large trade
    uint256 constant POST_ARB_FEE = 175 * BPS;

    // Arb threshold: 1% of reserves = likely arb
    // More sensitive than typical 2-3%, but doesn't trigger on retail
    uint256 constant ARB_THRESHOLD = WAD / 100;  // 1%

    // Decay rate: fast recovery to stay competitive
    // Returns to base in ~13 steps: (175-24)/12 ≈ 12.6 steps
    uint256 constant DECAY_PER_STEP = 12 * BPS;

    // Asymmetric protection: extra fee on the side that was just hit
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

        // Calculate trade size relative to reserves
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Time decay toward base fee
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

        // Arb detection: spike on large trades (>1% of reserves)
        if (tradeRatio > ARB_THRESHOLD) {
            // Spike both sides
            bidFee = POST_ARB_FEE;
            askFee = POST_ARB_FEE;

            // Asymmetric: extra protection on the side that was hit
            if (trade.isBuy) {
                // AMM bought X (trader sold X) - protect bid side
                bidFee = clampFee(bidFee + ASYMMETRIC_EXTRA);
            } else {
                // AMM sold X (trader bought X) - protect ask side
                askFee = clampFee(askFee + ASYMMETRIC_EXTRA);
            }
        }

        // Store and return
        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "Optimal";
    }
}
