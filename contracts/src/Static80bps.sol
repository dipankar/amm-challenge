// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Static 80bps Strategy
contract Strategy is AMMStrategyBase {
    uint256 constant FEE = 80 * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        return (FEE, FEE);
    }

    function afterSwap(TradeInfo calldata) external override returns (uint256, uint256) {
        return (FEE, FEE);
    }

    function getName() external pure override returns (string memory) {
        return "Static80bps";
    }
}
