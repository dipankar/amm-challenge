#!/usr/bin/env python3
"""Test WinningV3 thoroughly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from visualize import load_strategy, run_single_simulation

def test_strategy(strategy_path: Path, n_seeds: int = 50):
    strategy = load_strategy(strategy_path)
    name = strategy.get_name()

    our_edges = []
    norm_edges = []
    margins = []
    wins = 0

    for seed in range(n_seeds):
        result = run_single_simulation(strategy, seed=seed)
        if result:
            our = float(result.edges.get('submission', 0))
            norm = float(result.edges.get('normalizer', 0))
            our_edges.append(our)
            norm_edges.append(norm)
            margins.append(our - norm)
            if our > norm:
                wins += 1

    avg_ours = sum(our_edges) / len(our_edges)
    avg_norm = sum(norm_edges) / len(norm_edges)
    avg_margin = sum(margins) / len(margins)
    min_margin = min(margins)
    max_margin = max(margins)

    print(f"\n{name} (n={n_seeds}):")
    print(f"  Our Edge: {avg_ours:.2f}")
    print(f"  Norm Edge: {avg_norm:.2f}")
    print(f"  Avg Margin: {avg_margin:+.2f}")
    print(f"  Min Margin: {min_margin:+.2f}")
    print(f"  Max Margin: {max_margin:+.2f}")
    print(f"  Wins: {wins}/{n_seeds} ({100*wins/n_seeds:.0f}%)")

    return avg_margin, wins

PROJECT_ROOT = Path(__file__).parent.parent.parent

strategies = [
    (PROJECT_ROOT / "contracts/src/Low25bps.sol", "Static 25 bps"),
    (PROJECT_ROOT / "contracts/src/WinningV2Strategy.sol", "WinningV2"),
    (PROJECT_ROOT / "contracts/src/WinningV3Strategy.sol", "WinningV3"),
]

print("Testing strategies (50 seeds each)...")
print("=" * 60)

for path, label in strategies:
    test_strategy(path, n_seeds=50)
