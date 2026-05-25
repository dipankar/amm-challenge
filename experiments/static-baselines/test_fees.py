#!/usr/bin/env python3
"""Test different fixed fee levels to understand the edge curve."""

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

def test_fee(fee: int, sims: int = 50) -> float:
    """Test a fixed fee strategy and return the edge."""
    # Write strategy file
    strategy_path = "/media/dipankar/2953642b-b922-46d5-8f28-9430486eec8c/dipankar/Github/amm-challenge/contracts/src/TestFees.sol"
    with open(strategy_path, 'w') as f:
        f.write(TEMPLATE.format(fee=fee))

    # Run simulation
    result = subprocess.run(
        ['amm-match', 'run', strategy_path, '--simulations', str(sims)],
        capture_output=True,
        text=True
    )

    # Parse edge from output
    output = result.stdout + result.stderr
    match = re.search(r'Edge:\s*([-\d.]+)', output)
    if match:
        return float(match.group(1))
    else:
        print(f"Failed to parse output for {fee} bps:")
        print(output)
        return 0.0

def main():
    fees_to_test = [15, 20, 25, 28, 30, 32, 35, 40, 50, 60, 80]
    results = []

    print("Testing fixed fee strategies...")
    print("-" * 40)

    for fee in fees_to_test:
        edge = test_fee(fee, sims=50)
        results.append((fee, edge))
        print(f"{fee:3d} bps: {edge:8.2f} edge")

    print("-" * 40)

    # Find optimal
    best_fee, best_edge = max(results, key=lambda x: x[1])
    print(f"\nBest fixed fee: {best_fee} bps with edge {best_edge:.2f}")

if __name__ == "__main__":
    main()
