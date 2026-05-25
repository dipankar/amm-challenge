#!/usr/bin/env python3
"""Test strategies and report margin against normalizer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from visualize import load_strategy, run_single_simulation

def test_strategy(strategy_path: Path, n_seeds: int = 20):
    """Test a strategy across multiple seeds."""
    strategy = load_strategy(strategy_path)
    name = strategy.get_name()

    our_edges = []
    norm_edges = []
    wins = 0

    for seed in range(n_seeds):
        result = run_single_simulation(strategy, seed=seed)
        if result:
            our = float(result.edges.get('submission', 0))
            norm = float(result.edges.get('normalizer', 0))
            our_edges.append(our)
            norm_edges.append(norm)
            if our > norm:
                wins += 1

    avg_ours = sum(our_edges) / len(our_edges)
    avg_norm = sum(norm_edges) / len(norm_edges)
    margin = avg_ours - avg_norm

    print(f"\n{name}:")
    print(f"  Our Edge: {avg_ours:.2f}")
    print(f"  Norm Edge: {avg_norm:.2f}")
    print(f"  Margin: {margin:+.2f}")
    print(f"  Wins: {wins}/{n_seeds} ({100*wins/n_seeds:.0f}%)")

    return margin, wins, n_seeds

def main():
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    strategies = [
        PROJECT_ROOT / "contracts/src/Low25bps.sol",
        PROJECT_ROOT / "contracts/src/WinningV2Strategy.sol",
        PROJECT_ROOT / "contracts/src/RegimeStrategy.sol",
    ]

    print("Testing strategies against normalizer (20 seeds each)...")
    print("=" * 60)

    results = []
    for s in strategies:
        margin, wins, total = test_strategy(s, n_seeds=20)
        results.append((s, margin, wins, total))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for s, margin, wins, total in sorted(results, key=lambda x: -x[1]):
        name = Path(s).stem
        print(f"{name:30s}: margin={margin:+.2f}, wins={wins}/{total}")

if __name__ == "__main__":
    main()
