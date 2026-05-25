// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Asymmetric V2 Strategy
/// @notice Very different bid vs ask fees, inventory-based switching
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_NET_FLOW = 2;  // Signed flow (buy - sell)

    // Fee options (testing extreme asymmetry)
    uint256 constant COMPETITIVE_FEE = 40 * BPS;  // Attract flow
    uint256 constant NEUTRAL_FEE = 70 * BPS;      // Balanced
    uint256 constant PROTECTIVE_FEE = 95 * BPS;   // Protect reserves

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = NEUTRAL_FEE;
        slots[SLOT_ASK_FEE] = NEUTRAL_FEE;
        slots[SLOT_NET_FLOW] = WAD;  // Start at neutral (WAD = 0 flow)
        return (NEUTRAL_FEE, NEUTRAL_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        // Track net flow (X bought - X sold by AMM)
        uint256 netFlow = slots[SLOT_NET_FLOW];
        if (trade.isBuy) {
            // AMM bought X - add to flow
            netFlow = netFlow + trade.amountX;
        } else {
            // AMM sold X - subtract from flow
            if (netFlow > trade.amountX) {
                netFlow = netFlow - trade.amountX;
            } else {
                netFlow = 0;
            }
        }
        slots[SLOT_NET_FLOW] = netFlow;

        // Calculate inventory skew (using reserve ratio)
        uint256 xValue = trade.reserveX * 100;  // X at fair value
        uint256 totalValue = xValue + trade.reserveY;
        uint256 xPct = wdiv(xValue, totalValue);  // Should be ~50%

        // Set asymmetric fees based on inventory
        uint256 bidFee;
        uint256 askFee;

        if (xPct < WAD * 45 / 100) {
            // X depleted (<45%)
            // Make it expensive to buy X (we sell) → high ask
            // Make it cheap to sell X to us (we buy) → low bid
            bidFee = COMPETITIVE_FEE;
            askFee = PROTECTIVE_FEE;
        } else if (xPct > WAD * 55 / 100) {
            // X excess (>55%)
            // Make it cheap to buy X → low ask
            // Make it expensive to sell X to us → high bid
            bidFee = PROTECTIVE_FEE;
            askFee = COMPETITIVE_FEE;
        } else {
            // Balanced - use neutral fees
            bidFee = NEUTRAL_FEE;
            askFee = NEUTRAL_FEE;
        }

        // Additional protection: spike both after very large trades
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        if (tradeRatio > WAD / 20) {  // >5% = definitely arb
            bidFee = clampFee(bidFee + 15 * BPS);
            askFee = clampFee(askFee + 15 * BPS);
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "AsymmetricV2";
    }
}
