// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Greedy Edge Strategy - Three-tier fee structure for max edge extraction
/// @notice 60 bps retail, 150 bps medium, 400 bps arb - aggressive greedy pricing
/// @dev Best params from grid search: retail=60, medium=150, arb=400, small=150, large=40 (edge=423.71)
contract Strategy is AMMStrategyBase {
    // Three-tier fee structure (optimized for edge=423.71 @ 0.8% wins)
    uint256 constant RETAIL_FEE = 60 * BPS;     // 2x normalizer - greedy extraction
    uint256 constant MEDIUM_FEE = 150 * BPS;    // 1.5% for medium trades
    uint256 constant ARB_FEE = 400 * BPS;       // 4% for large arb trades

    // Thresholds
    uint256 constant SMALL_THRESH = WAD / 150;  // <0.67% of reserves = retail
    uint256 constant LARGE_THRESH = WAD / 40;   // >2.5% of reserves = arb

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        return (RETAIL_FEE, RETAIL_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        uint256 fee;

        if (tradeRatio < SMALL_THRESH) {
            // Small trades still pay a high base fee.
            fee = RETAIL_FEE;
        } else if (tradeRatio > LARGE_THRESH) {
            // Large arb trade - extract maximum
            fee = ARB_FEE;
        } else {
            // Medium trade - fixed medium fee
            fee = MEDIUM_FEE;
        }

        fee = clampFee(fee);
        return (fee, fee);
    }

    function getName() external pure override returns (string memory) {
        return "GreedyEdge";
    }
}
