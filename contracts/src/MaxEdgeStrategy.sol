// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Max Edge Strategy - Maximum 10% fee for maximum edge
/// @notice Uses maximum allowed fee to capture maximum profit per trade
contract Strategy is AMMStrategyBase {
    // Maximum allowed fee: 10% = 1000 bps
    uint256 constant FEE = 1000 * BPS;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        return (FEE, FEE);
    }

    function afterSwap(TradeInfo calldata)
        external
        override
        returns (uint256, uint256)
    {
        return (FEE, FEE);
    }

    function getName() external pure override returns (string memory) {
        return "MaxEdge10pct";
    }
}
