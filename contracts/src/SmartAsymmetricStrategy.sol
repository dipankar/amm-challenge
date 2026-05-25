// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Smart Asymmetric Strategy
/// @notice Uses price impact and inventory to set optimal asymmetric fees
contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_LAST_TIMESTAMP = 2;
    uint256 constant SLOT_LAST_PRICE = 3;  // Track implied price changes

    // Balanced parameters
    uint256 constant BASE_FEE = 28 * BPS;       // Slightly under normalizer
    uint256 constant FLOOR_FEE = 20 * BPS;      // Floor
    uint256 constant MAX_SPIKE = 80 * BPS;      // Ceiling after arb

    // Detection thresholds
    uint256 constant SMALL_TRADE = WAD / 100;   // 1% = definitely retail
    uint256 constant LARGE_TRADE = WAD / 25;    // 4% = likely arb

    // Adjustment rates
    uint256 constant DECAY_RATE = 4 * BPS;
    uint256 constant SPIKE_AMOUNT = 40 * BPS;

    function afterInitialize(uint256, uint256)
        external
        override
        returns (uint256, uint256)
    {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_LAST_PRICE] = WAD * 100;  // Initial price = 100
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256, uint256)
    {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];

        // Calculate trade ratio
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        // Time-based decay
        uint256 lastTs = slots[SLOT_LAST_TIMESTAMP];
        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps < 100) {
                uint256 decay = steps * DECAY_RATE;
                if (bidFee > BASE_FEE) {
                    bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
                }
                if (askFee > BASE_FEE) {
                    askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
                }
            }
        }
        slots[SLOT_LAST_TIMESTAMP] = trade.timestamp;

        // Calculate current implied price (Y/X ratio)
        uint256 currentPrice = wdiv(trade.reserveY, trade.reserveX);
        uint256 lastPrice = slots[SLOT_LAST_PRICE];

        // If price changed significantly, this was likely arb
        uint256 priceChange = currentPrice > lastPrice
            ? wdiv(currentPrice - lastPrice, lastPrice)
            : wdiv(lastPrice - currentPrice, lastPrice);

        slots[SLOT_LAST_PRICE] = currentPrice;

        // Strategy logic based on trade size and price impact
        if (tradeRatio > LARGE_TRADE) {
            // Large trade - likely arb, spike fees
            if (trade.isBuy) {
                // AMM bought X (price going down)
                // Widen bid more (protect against more selling)
                bidFee = clampFee(MAX_SPIKE);
                askFee = clampFee(askFee + SPIKE_AMOUNT / 2);
            } else {
                // AMM sold X (price going up)
                // Widen ask more (protect against more buying)
                askFee = clampFee(MAX_SPIKE);
                bidFee = clampFee(bidFee + SPIKE_AMOUNT / 2);
            }
        } else if (tradeRatio > SMALL_TRADE) {
            // Medium trade - could be either
            // Moderate widening on hit side
            if (trade.isBuy) {
                bidFee = clampFee(bidFee + 15 * BPS);
            } else {
                askFee = clampFee(askFee + 15 * BPS);
            }
        }
        // Small trades: keep competitive (already decayed)

        // Inventory skew adjustment
        // Initial: 100 X, 10000 Y at price 100
        // If X is depleted, make selling X more expensive (higher ask)
        // If X is excess, make buying X more expensive (higher bid)
        uint256 xValue = trade.reserveX * 100; // X valued at 100 Y each
        uint256 totalValue = xValue + trade.reserveY;
        uint256 xPct = wdiv(xValue, totalValue);

        // Target: 50% in each
        if (xPct < WAD * 45 / 100) {
            // X depleted - increase ask fee
            askFee = clampFee(wmul(askFee, WAD * 115 / 100));
        } else if (xPct > WAD * 55 / 100) {
            // X excess - increase bid fee
            bidFee = clampFee(wmul(bidFee, WAD * 115 / 100));
        }

        // Ensure minimum fee
        if (bidFee < FLOOR_FEE) bidFee = FLOOR_FEE;
        if (askFee < FLOOR_FEE) askFee = FLOOR_FEE;

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "SmartAsymmetric";
    }
}
