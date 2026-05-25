#!/usr/bin/env python3
"""Test high fee levels to find the peak."""

import subprocess
import re

TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    uint256 constant FEE = {fee} * BPS;

    function afterInitialize(uint256, uint256) external pure override returns (uint256, uint256) {{
        return (FEE, FEE);
    }}

    function afterSwap(TradeInfo calldata) external pure override returns (uint256, uint256) {{
        return (FEE, FEE);
    }}

    function getName() external pure override returns (string memory) {{
        return "Fixed{fee}bps";
    }}
}}
'''

def test_fee(fee: int, sims: int = 100) -> float:
    """Test a fixed fee strategy and return the edge."""
    strategy_path = "/media/dipankar/2953642b-b922-46d5-8f28-9430486eec8c/dipankar/Github/amm-challenge/contracts/src/TestFees.sol"
    with open(strategy_path, 'w') as f:
        f.write(TEMPLATE.format(fee=fee))

    result = subprocess.run(
        ['amm-match', 'run', strategy_path, '--simulations', str(sims)],
        capture_output=True,
        text=True
    )

    output = result.stdout + result.stderr
    match = re.search(r'Edge:\s*([-\d.]+)', output)
    if match:
        return float(match.group(1))
    return 0.0

def main():
    # Test high fees
    fees_to_test = [80, 100, 150, 200, 300, 500, 800, 1000]
    results = []

    print("Testing high fee strategies (100 sims each)...")
    print("-" * 40)

    for fee in fees_to_test:
        edge = test_fee(fee, sims=100)
        results.append((fee, edge))
        print(f"{fee:4d} bps: {edge:8.2f} edge")

    print("-" * 40)

    best_fee, best_edge = max(results, key=lambda x: x[1])
    print(f"\nBest high fee: {best_fee} bps with edge {best_edge:.2f}")

if __name__ == "__main__":
    main()
