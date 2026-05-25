#!/usr/bin/env python3
"""Fine-tune around the optimal static fee level."""

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

def test_fee(fee: int, sims: int = 200) -> float:
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
    # Fine-tune around 75-100 bps
    fees_to_test = [70, 75, 78, 80, 82, 85, 88, 90, 95, 100]
    results = []

    print("Fine-tuning static fee around optimal region (200 sims each)...")
    print("-" * 50)

    for fee in fees_to_test:
        edge = test_fee(fee, sims=200)
        results.append((fee, edge))
        print(f"{fee:3d} bps: {edge:8.2f} edge")

    print("-" * 50)

    best_fee, best_edge = max(results, key=lambda x: x[1])
    print(f"\nOptimal static fee: {best_fee} bps with edge {best_edge:.2f}")

if __name__ == "__main__":
    main()
