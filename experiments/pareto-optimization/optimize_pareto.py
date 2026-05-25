#!/usr/bin/env python3
"""Sequential Pareto optimizer for AMM fee strategy parameters.

Objective:
- Maximize our absolute edge
- Minimize win rate (intentionally low-win regime)

This script avoids Python multiprocessing so it can run in sandboxed
environments where semaphore-based pools fail.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import amm_sim_rs
from amm_competition.competition.config import BASELINE_SETTINGS, BASELINE_VARIANCE
from amm_competition.competition.match import MatchRunner
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import load_vanilla_strategy
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator


SYM3_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant RETAIL_FEE = __RETAIL__ * BPS;
    uint256 constant MEDIUM_FEE = __MEDIUM__ * BPS;
    uint256 constant ARB_FEE = __ARB__ * BPS;
    uint256 constant SMALL_THRESH = WAD / __SMALL__;
    uint256 constant LARGE_THRESH = WAD / __LARGE__;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        return (RETAIL_FEE, RETAIL_FEE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        uint256 fee;
        if (tradeRatio < SMALL_THRESH) fee = RETAIL_FEE;
        else if (tradeRatio > LARGE_THRESH) fee = ARB_FEE;
        else fee = MEDIUM_FEE;
        return (clampFee(fee), clampFee(fee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoSym3";
    }
}
"""


ASYM_HIT_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant RETAIL_FEE = __RETAIL__ * BPS;
    uint256 constant MID_PASSIVE = __MID_PASSIVE__ * BPS;
    uint256 constant MID_HIT = __MID_HIT__ * BPS;
    uint256 constant ARB_PASSIVE = __ARB_PASSIVE__ * BPS;
    uint256 constant ARB_HIT = __ARB_HIT__ * BPS;
    uint256 constant SMALL_THRESH = WAD / __SMALL__;
    uint256 constant LARGE_THRESH = WAD / __LARGE__;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        return (RETAIL_FEE, RETAIL_FEE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        uint256 bidFee;
        uint256 askFee;

        if (tradeRatio < SMALL_THRESH) {
            bidFee = RETAIL_FEE;
            askFee = RETAIL_FEE;
        } else if (tradeRatio > LARGE_THRESH) {
            if (trade.isBuy) {
                bidFee = ARB_HIT;
                askFee = ARB_PASSIVE;
            } else {
                bidFee = ARB_PASSIVE;
                askFee = ARB_HIT;
            }
        } else {
            if (trade.isBuy) {
                bidFee = MID_HIT;
                askFee = MID_PASSIVE;
            } else {
                bidFee = MID_PASSIVE;
                askFee = MID_HIT;
            }
        }

        return (clampFee(bidFee), clampFee(askFee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoAsymHit";
    }
}
"""


EWMA_SPIKE_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_BID_FEE = 0;
    uint256 constant SLOT_ASK_FEE = 1;
    uint256 constant SLOT_SPIKE_LEFT = 2;
    uint256 constant SLOT_EWMA = 3;
    uint256 constant SLOT_LAST_TS = 4;

    uint256 constant BASE_FEE = __BASE__ * BPS;
    uint256 constant RETAIL_FEE = __DISCOUNT__ * BPS;
    uint256 constant SPIKE_FEE = __SPIKE__ * BPS;
    uint256 constant HIT_PREMIUM = __HIT_PREMIUM__ * BPS;
    uint256 constant DECAY_PER_STEP = __DECAY__ * BPS;
    uint256 constant HARD_THRESH = WAD / __HARD_DEN__;
    uint256 constant ALPHA = WAD / __ALPHA_DEN__;
    uint256 constant ARB_MULT = __ARB_MULT__;
    uint256 constant SPIKE_LEN = __SPIKE_LEN__;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        slots[SLOT_BID_FEE] = BASE_FEE;
        slots[SLOT_ASK_FEE] = BASE_FEE;
        slots[SLOT_EWMA] = WAD / 100;
        return (BASE_FEE, BASE_FEE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 bidFee = slots[SLOT_BID_FEE];
        uint256 askFee = slots[SLOT_ASK_FEE];
        uint256 spikeLeft = slots[SLOT_SPIKE_LEFT];
        uint256 ewma = slots[SLOT_EWMA];
        uint256 lastTs = slots[SLOT_LAST_TS];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        if (trade.timestamp > lastTs) {
            uint256 steps = trade.timestamp - lastTs;
            if (steps > 0 && steps < 50) {
                uint256 decay = steps * DECAY_PER_STEP;
                if (bidFee > BASE_FEE) bidFee = bidFee > BASE_FEE + decay ? bidFee - decay : BASE_FEE;
                if (askFee > BASE_FEE) askFee = askFee > BASE_FEE + decay ? askFee - decay : BASE_FEE;
            }
        }
        slots[SLOT_LAST_TS] = trade.timestamp;

        bool isArb = tradeRatio > HARD_THRESH || tradeRatio > ewma * ARB_MULT;

        if (isArb) {
            bidFee = SPIKE_FEE;
            askFee = SPIKE_FEE;
            if (trade.isBuy) bidFee = clampFee(bidFee + HIT_PREMIUM);
            else askFee = clampFee(askFee + HIT_PREMIUM);
            slots[SLOT_SPIKE_LEFT] = SPIKE_LEN;
        } else if (spikeLeft > 0) {
            uint256 carried = BASE_FEE + ((SPIKE_FEE - BASE_FEE) * spikeLeft / SPIKE_LEN);
            bidFee = carried;
            askFee = carried;
            slots[SLOT_SPIKE_LEFT] = spikeLeft - 1;
        } else if (tradeRatio < ewma / 3) {
            bidFee = RETAIL_FEE;
            askFee = RETAIL_FEE;
        } else {
            bidFee = BASE_FEE;
            askFee = BASE_FEE;
        }

        slots[SLOT_BID_FEE] = bidFee;
        slots[SLOT_ASK_FEE] = askFee;
        return (clampFee(bidFee), clampFee(askFee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoEwmaSpike";
    }
}
"""

PRESSURE_ASYM_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_PRESSURE = 0;

    uint256 constant BASE = __BASE__ * BPS;
    uint256 constant HIGH = __HIGH__ * BPS;
    uint256 constant PRESSURE_THRESH = __PRESSURE__ * BPS;
    uint256 constant LARGE_DEN = __LARGE_DEN__;
    uint256 constant ARB_BUMP = __ARB_BUMP__ * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        slots[SLOT_PRESSURE] = WAD / 2;
        return (BASE, BASE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 pressure = slots[SLOT_PRESSURE];
        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);

        if (trade.isBuy) {
            pressure = pressure + tradeRatio;
            if (pressure > WAD) pressure = WAD;
        } else {
            pressure = pressure > tradeRatio ? pressure - tradeRatio : 0;
        }
        slots[SLOT_PRESSURE] = pressure;

        uint256 bidFee = BASE;
        uint256 askFee = BASE;

        if (pressure > WAD / 2 + PRESSURE_THRESH) {
            bidFee = HIGH;
        } else if (pressure + PRESSURE_THRESH < WAD / 2) {
            askFee = HIGH;
        }

        if (tradeRatio > WAD / LARGE_DEN) {
            if (trade.isBuy) bidFee = clampFee(bidFee + ARB_BUMP);
            else askFee = clampFee(askFee + ARB_BUMP);
        }

        return (clampFee(bidFee), clampFee(askFee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoPressureAsym";
    }
}
"""

INVENTORY_SQUEEZE_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_REGIME = 0; // 0 neutral, 1 squeeze_bid, 2 squeeze_ask

    uint256 constant BASE = __BASE__ * BPS;
    uint256 constant SQUEEZE = __SQUEEZE__ * BPS;
    uint256 constant ENTER = __ENTER__ * BPS;
    uint256 constant EXIT = __EXIT__ * BPS;
    uint256 constant LARGE_DEN = __LARGE_DEN__;
    uint256 constant ARB_BUMP = __ARB_BUMP__ * BPS;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        slots[SLOT_REGIME] = 0;
        return (BASE, BASE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 regime = slots[SLOT_REGIME];
        uint256 ratio = wdiv(trade.reserveX * 100, trade.reserveY);
        uint256 upperEnter = WAD + ENTER;
        uint256 lowerEnter = WAD > ENTER ? WAD - ENTER : 0;
        uint256 upperExit = WAD + EXIT;
        uint256 lowerExit = WAD > EXIT ? WAD - EXIT : 0;

        if (regime == 0) {
            if (ratio > upperEnter) regime = 1;
            else if (ratio < lowerEnter) regime = 2;
        } else if (regime == 1) {
            if (ratio < upperExit) regime = 0;
        } else {
            if (ratio > lowerExit) regime = 0;
        }
        slots[SLOT_REGIME] = regime;

        uint256 bidFee = BASE;
        uint256 askFee = BASE;
        if (regime == 1) bidFee = SQUEEZE;
        else if (regime == 2) askFee = SQUEEZE;

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        if (tradeRatio > WAD / LARGE_DEN) {
            if (trade.isBuy) bidFee = clampFee(bidFee + ARB_BUMP);
            else askFee = clampFee(askFee + ARB_BUMP);
        }

        return (clampFee(bidFee), clampFee(askFee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoInvSqueeze";
    }
}
"""

REGIME_SWITCH_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_MODE = 0; // 0 capture, 1 extract
    uint256 constant SLOT_COOLDOWN = 1;
    uint256 constant SLOT_EWMA = 2;

    uint256 constant CAPTURE_FEE = __CAPTURE__ * BPS;
    uint256 constant EXTRACT_BASE = __EXTRACT__ * BPS;
    uint256 constant EXTRACT_SPIKE = __SPIKE__ * BPS;
    uint256 constant HIT_PREMIUM = __HIT_PREMIUM__ * BPS;
    uint256 constant HARD_DEN = __HARD_DEN__;
    uint256 constant UP_MULT = __UP_MULT__;
    uint256 constant DOWN_DIV = __DOWN_DIV__;
    uint256 constant EXTRACT_LEN = __EXTRACT_LEN__;
    uint256 constant ALPHA = WAD / __ALPHA_DEN__;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        slots[SLOT_MODE] = 0;
        slots[SLOT_COOLDOWN] = 0;
        slots[SLOT_EWMA] = WAD / 100;
        return (CAPTURE_FEE, CAPTURE_FEE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 mode = slots[SLOT_MODE];
        uint256 cooldown = slots[SLOT_COOLDOWN];
        uint256 ewma = slots[SLOT_EWMA];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        bool hardArb = tradeRatio > WAD / HARD_DEN;
        bool relArb = tradeRatio > ewma * UP_MULT;

        if (mode == 0) {
            if (hardArb || relArb) {
                mode = 1;
                cooldown = EXTRACT_LEN;
            }
        } else {
            if (cooldown > 0) cooldown -= 1;
            if (cooldown == 0 && tradeRatio < ewma / DOWN_DIV) {
                mode = 0;
            } else if (hardArb || relArb) {
                cooldown = EXTRACT_LEN;
            }
        }

        slots[SLOT_MODE] = mode;
        slots[SLOT_COOLDOWN] = cooldown;

        uint256 bidFee;
        uint256 askFee;
        if (mode == 0) {
            bidFee = CAPTURE_FEE;
            askFee = CAPTURE_FEE;
        } else {
            uint256 fee = (hardArb || relArb) ? EXTRACT_SPIKE : EXTRACT_BASE;
            bidFee = fee;
            askFee = fee;
            if (trade.isBuy) bidFee = clampFee(bidFee + HIT_PREMIUM);
            else askFee = clampFee(askFee + HIT_PREMIUM);
        }

        return (clampFee(bidFee), clampFee(askFee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoRegimeSwitch";
    }
}
"""

SYM3_TOXIC_FLOW_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {
    uint256 constant SLOT_SPIKE_LEFT = 0;
    uint256 constant SLOT_EWMA = 1;
    uint256 constant SLOT_BIAS = 2; // 0..200, 100 neutral

    uint256 constant RETAIL_FEE = __RETAIL__ * BPS;
    uint256 constant MEDIUM_FEE = __MEDIUM__ * BPS;
    uint256 constant ARB_FEE = __ARB__ * BPS;
    uint256 constant SMALL_THRESH = WAD / __SMALL__;
    uint256 constant LARGE_THRESH = WAD / __LARGE__;

    uint256 constant EXTRACT_BASE = __EXTRACT_BASE__ * BPS;
    uint256 constant EXTRACT_SPIKE = __EXTRACT_SPIKE__ * BPS;
    uint256 constant HIT_PREMIUM = __HIT_PREMIUM__ * BPS;
    uint256 constant FLOW_BUMP = __FLOW_BUMP__ * BPS;
    uint256 constant BIAS_STEP = __BIAS_STEP__;
    uint256 constant BIAS_THRESH = __BIAS_THRESH__;

    uint256 constant UP_MULT = __UP_MULT__;
    uint256 constant ALPHA = WAD / __ALPHA_DEN__;
    uint256 constant EXTRACT_LEN = __EXTRACT_LEN__;

    function afterInitialize(uint256, uint256) external override returns (uint256, uint256) {
        slots[SLOT_SPIKE_LEFT] = 0;
        slots[SLOT_EWMA] = WAD / 120;
        slots[SLOT_BIAS] = 100;
        return (RETAIL_FEE, RETAIL_FEE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256, uint256) {
        uint256 spikeLeft = slots[SLOT_SPIKE_LEFT];
        uint256 ewma = slots[SLOT_EWMA];
        uint256 bias = slots[SLOT_BIAS];

        uint256 tradeRatio = wdiv(trade.amountY, trade.reserveY);
        ewma = wmul(ewma, WAD - ALPHA) + wmul(tradeRatio, ALPHA);
        slots[SLOT_EWMA] = ewma;

        if (trade.isBuy) {
            uint256 next = bias + BIAS_STEP;
            bias = next > 200 ? 200 : next;
        } else {
            bias = bias > BIAS_STEP ? bias - BIAS_STEP : 0;
        }
        slots[SLOT_BIAS] = bias;

        uint256 baseFee;
        if (tradeRatio < SMALL_THRESH) baseFee = RETAIL_FEE;
        else if (tradeRatio > LARGE_THRESH) baseFee = ARB_FEE;
        else baseFee = MEDIUM_FEE;

        bool hardArb = tradeRatio > LARGE_THRESH;
        bool relArb = tradeRatio > ewma * UP_MULT;
        bool toxic = hardArb || relArb;

        if (toxic) spikeLeft = EXTRACT_LEN;
        else if (spikeLeft > 0) spikeLeft -= 1;
        slots[SLOT_SPIKE_LEFT] = spikeLeft;

        uint256 fee = baseFee;
        if (spikeLeft > 0) {
            if (fee < EXTRACT_BASE) fee = EXTRACT_BASE;
            if (toxic && fee < EXTRACT_SPIKE) fee = EXTRACT_SPIKE;
        }

        uint256 bidFee = fee;
        uint256 askFee = fee;

        if (toxic || spikeLeft > 0) {
            if (trade.isBuy) bidFee = clampFee(bidFee + HIT_PREMIUM);
            else askFee = clampFee(askFee + HIT_PREMIUM);
        }

        if (bias > 100 + BIAS_THRESH) bidFee = clampFee(bidFee + FLOW_BUMP);
        else if (bias + BIAS_THRESH < 100) askFee = clampFee(askFee + FLOW_BUMP);

        return (clampFee(bidFee), clampFee(askFee));
    }

    function getName() external pure override returns (string memory) {
        return "ParetoSym3ToxicFlow";
    }
}
"""


@dataclass(frozen=True)
class Candidate:
    template: str
    params: tuple[tuple[str, int], ...]

    @property
    def params_dict(self) -> dict[str, int]:
        return dict(self.params)

    @property
    def key(self) -> str:
        parts = [self.template] + [f"{k}={v}" for k, v in self.params]
        return "|".join(parts)


@dataclass
class EvalResult:
    candidate_key: str
    template: str
    params: dict[str, int]
    n_sims: int
    edge: float
    norm_edge: float
    wins: int
    total: int
    stage: str
    eval_s: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


def _clamp_to_choices(value: int, choices: list[int]) -> int:
    return min(choices, key=lambda c: abs(c - value))


class CandidateFactory:
    sym_retail = [30, 35, 40, 45, 50, 55, 58, 60, 62, 65, 68, 70, 75, 80, 85, 90]
    sym_medium = [80, 100, 110, 120, 130, 140, 150, 160, 170, 180, 200, 220, 250, 300]
    sym_arb = [250, 300, 320, 350, 380, 400, 420, 450, 500, 600, 700, 800, 900, 1000]
    sym_small = [80, 100, 120, 130, 140, 150, 160, 170, 180, 200, 220, 250, 300]
    sym_large = [20, 25, 30, 35, 40, 45, 50, 60, 80]

    asym_retail = [30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
    asym_mid_passive = [50, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200]
    asym_mid_hit = [80, 100, 120, 140, 160, 180, 200, 220, 250, 280, 300]
    asym_arb_passive = [90, 100, 120, 140, 160, 180, 200, 250, 300, 350, 400]
    asym_arb_hit = [250, 300, 350, 400, 500, 600, 700, 800, 900, 1000]
    asym_small = [80, 100, 120, 130, 140, 150, 160, 180, 200, 220, 250]
    asym_large = [20, 25, 30, 35, 40, 45, 50, 60, 80]

    ew_base = [25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
    ew_discount = [15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
    ew_spike = [120, 150, 180, 220, 250, 300, 350, 400, 500, 600]
    ew_hit_premium = [0, 5, 10, 15, 20, 30, 40]
    ew_decay = [5, 8, 10, 12, 15, 20, 25]
    ew_hard_den = [20, 25, 30, 35, 40, 50, 60]
    ew_alpha_den = [6, 8, 10, 12]
    ew_arb_mult = [2, 3, 4, 5, 6]
    ew_spike_len = [2, 3, 4, 5]

    pa_base = [20, 25, 30, 35, 40, 45, 50, 60, 70, 80]
    pa_high = [120, 150, 200, 250, 300, 400, 500, 700, 900, 1000]
    pa_pressure = [5, 10, 15, 20, 25, 30, 35]
    pa_large_den = [20, 25, 30, 35, 40, 50, 60]
    pa_arb_bump = [10, 15, 20, 30, 40, 50, 70, 100]

    is_base = [20, 25, 30, 35, 40, 45, 50, 60, 70]
    is_squeeze = [120, 150, 200, 250, 300, 400, 500, 700, 900]
    is_enter = [300, 500, 700, 1000, 1200, 1500, 1800, 2200]
    is_exit = [100, 200, 300, 500, 700, 900, 1200]
    is_large_den = [20, 25, 30, 35, 40, 50, 60]
    is_arb_bump = [10, 15, 20, 30, 40, 50, 70, 100]

    rs_capture = [10, 15, 20, 24, 25, 28, 30, 35, 40]
    rs_extract = [80, 100, 120, 150, 180, 220, 260, 300]
    rs_spike = [150, 180, 220, 260, 300, 400, 500, 700, 900]
    rs_hit_premium = [0, 5, 10, 15, 20, 30, 40, 60]
    rs_hard_den = [20, 25, 30, 35, 40, 50, 60]
    rs_up_mult = [2, 3, 4, 5, 6]
    rs_down_div = [2, 3, 4, 5, 6]
    rs_extract_len = [1, 2, 3, 4, 5, 6, 8]
    rs_alpha_den = [6, 8, 10, 12]

    stf_retail = [45, 50, 55, 58, 60, 62, 65]
    stf_medium = [120, 130, 140, 150, 160, 170, 180]
    stf_arb = [300, 320, 350, 380, 400, 420, 450, 500, 600]
    stf_small = [120, 130, 140, 150, 160, 170, 180, 200]
    stf_large = [30, 35, 40, 45, 50]
    stf_extract_base = [140, 160, 180, 200, 220, 250, 300]
    stf_extract_spike = [260, 300, 350, 400, 450, 520, 600, 700]
    stf_hit_premium = [10, 15, 20, 30, 40, 60, 80]
    stf_flow_bump = [5, 10, 15, 20, 30]
    stf_bias_step = [3, 4, 5, 6, 8, 10]
    stf_bias_thresh = [8, 10, 12, 15, 20, 25]
    stf_up_mult = [2, 3, 4, 5]
    stf_alpha_den = [6, 8, 10, 12]
    stf_extract_len = [2, 3, 4, 5, 6, 8]

    templates = (
        "sym3",
        "asym_hit",
        "ewma_spike",
        "pressure_asym",
        "inventory_squeeze",
        "regime_switch",
        "sym3_toxic_flow",
    )

    def __init__(self, rng: random.Random):
        self.rng = rng

    @staticmethod
    def _to_candidate(template: str, params: dict[str, int]) -> Candidate:
        return Candidate(template=template, params=tuple(sorted(params.items())))

    def sample(self, template: str) -> Candidate:
        if template == "sym3":
            return self._sample_sym3()
        if template == "asym_hit":
            return self._sample_asym_hit()
        if template == "ewma_spike":
            return self._sample_ewma_spike()
        if template == "pressure_asym":
            return self._sample_pressure_asym()
        if template == "inventory_squeeze":
            return self._sample_inventory_squeeze()
        if template == "regime_switch":
            return self._sample_regime_switch()
        if template == "sym3_toxic_flow":
            return self._sample_sym3_toxic_flow()
        raise ValueError(f"unknown template: {template}")

    def mutate(self, base: Candidate) -> Candidate:
        if base.template == "sym3":
            return self._mutate_sym3(base.params_dict)
        if base.template == "asym_hit":
            return self._mutate_asym_hit(base.params_dict)
        if base.template == "ewma_spike":
            return self._mutate_ewma_spike(base.params_dict)
        if base.template == "pressure_asym":
            return self._mutate_pressure_asym(base.params_dict)
        if base.template == "inventory_squeeze":
            return self._mutate_inventory_squeeze(base.params_dict)
        if base.template == "regime_switch":
            return self._mutate_regime_switch(base.params_dict)
        if base.template == "sym3_toxic_flow":
            return self._mutate_sym3_toxic_flow(base.params_dict)
        raise ValueError(f"unknown template: {base.template}")

    def _sample_sym3(self) -> Candidate:
        while True:
            params = {
                "retail": self.rng.choice(self.sym_retail),
                "medium": self.rng.choice(self.sym_medium),
                "arb": self.rng.choice(self.sym_arb),
                "small": self.rng.choice(self.sym_small),
                "large": self.rng.choice(self.sym_large),
            }
            if params["retail"] <= params["medium"] <= params["arb"] and params["small"] > params["large"]:
                return self._to_candidate("sym3", params)

    def _mutate_sym3(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        for key, choices in (
            ("retail", self.sym_retail),
            ("medium", self.sym_medium),
            ("arb", self.sym_arb),
            ("small", self.sym_small),
            ("large", self.sym_large),
        ):
            if self.rng.random() < 0.5:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        if not (p["retail"] <= p["medium"] <= p["arb"] and p["small"] > p["large"]):
            return self._sample_sym3()
        return self._to_candidate("sym3", p)

    def _sample_asym_hit(self) -> Candidate:
        while True:
            params = {
                "retail": self.rng.choice(self.asym_retail),
                "mid_passive": self.rng.choice(self.asym_mid_passive),
                "mid_hit": self.rng.choice(self.asym_mid_hit),
                "arb_passive": self.rng.choice(self.asym_arb_passive),
                "arb_hit": self.rng.choice(self.asym_arb_hit),
                "small": self.rng.choice(self.asym_small),
                "large": self.rng.choice(self.asym_large),
            }
            valid = (
                params["retail"] <= params["mid_passive"] <= params["mid_hit"] <= params["arb_hit"]
                and params["retail"] <= params["arb_passive"] <= params["arb_hit"]
                and params["small"] > params["large"]
            )
            if valid:
                return self._to_candidate("asym_hit", params)

    def _mutate_asym_hit(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        fields = (
            ("retail", self.asym_retail),
            ("mid_passive", self.asym_mid_passive),
            ("mid_hit", self.asym_mid_hit),
            ("arb_passive", self.asym_arb_passive),
            ("arb_hit", self.asym_arb_hit),
            ("small", self.asym_small),
            ("large", self.asym_large),
        )
        for key, choices in fields:
            if self.rng.random() < 0.5:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        valid = (
            p["retail"] <= p["mid_passive"] <= p["mid_hit"] <= p["arb_hit"]
            and p["retail"] <= p["arb_passive"] <= p["arb_hit"]
            and p["small"] > p["large"]
        )
        if not valid:
            return self._sample_asym_hit()
        return self._to_candidate("asym_hit", p)

    def _sample_ewma_spike(self) -> Candidate:
        while True:
            params = {
                "base": self.rng.choice(self.ew_base),
                "discount": self.rng.choice(self.ew_discount),
                "spike": self.rng.choice(self.ew_spike),
                "hit_premium": self.rng.choice(self.ew_hit_premium),
                "decay": self.rng.choice(self.ew_decay),
                "hard_den": self.rng.choice(self.ew_hard_den),
                "alpha_den": self.rng.choice(self.ew_alpha_den),
                "arb_mult": self.rng.choice(self.ew_arb_mult),
                "spike_len": self.rng.choice(self.ew_spike_len),
            }
            if params["discount"] <= params["base"] <= params["spike"]:
                return self._to_candidate("ewma_spike", params)

    def _mutate_ewma_spike(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        fields = (
            ("base", self.ew_base),
            ("discount", self.ew_discount),
            ("spike", self.ew_spike),
            ("hit_premium", self.ew_hit_premium),
            ("decay", self.ew_decay),
            ("hard_den", self.ew_hard_den),
            ("alpha_den", self.ew_alpha_den),
            ("arb_mult", self.ew_arb_mult),
            ("spike_len", self.ew_spike_len),
        )
        for key, choices in fields:
            if self.rng.random() < 0.55:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        if not (p["discount"] <= p["base"] <= p["spike"]):
            return self._sample_ewma_spike()
        return self._to_candidate("ewma_spike", p)

    def _sample_pressure_asym(self) -> Candidate:
        while True:
            params = {
                "base": self.rng.choice(self.pa_base),
                "high": self.rng.choice(self.pa_high),
                "pressure": self.rng.choice(self.pa_pressure),
                "large_den": self.rng.choice(self.pa_large_den),
                "arb_bump": self.rng.choice(self.pa_arb_bump),
            }
            if params["base"] <= params["high"]:
                return self._to_candidate("pressure_asym", params)

    def _mutate_pressure_asym(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        fields = (
            ("base", self.pa_base),
            ("high", self.pa_high),
            ("pressure", self.pa_pressure),
            ("large_den", self.pa_large_den),
            ("arb_bump", self.pa_arb_bump),
        )
        for key, choices in fields:
            if self.rng.random() < 0.55:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        if p["base"] > p["high"]:
            return self._sample_pressure_asym()
        return self._to_candidate("pressure_asym", p)

    def _sample_inventory_squeeze(self) -> Candidate:
        while True:
            params = {
                "base": self.rng.choice(self.is_base),
                "squeeze": self.rng.choice(self.is_squeeze),
                "enter": self.rng.choice(self.is_enter),
                "exit": self.rng.choice(self.is_exit),
                "large_den": self.rng.choice(self.is_large_den),
                "arb_bump": self.rng.choice(self.is_arb_bump),
            }
            if params["base"] <= params["squeeze"] and params["exit"] < params["enter"]:
                return self._to_candidate("inventory_squeeze", params)

    def _mutate_inventory_squeeze(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        fields = (
            ("base", self.is_base),
            ("squeeze", self.is_squeeze),
            ("enter", self.is_enter),
            ("exit", self.is_exit),
            ("large_den", self.is_large_den),
            ("arb_bump", self.is_arb_bump),
        )
        for key, choices in fields:
            if self.rng.random() < 0.55:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        if p["base"] > p["squeeze"] or p["exit"] >= p["enter"]:
            return self._sample_inventory_squeeze()
        return self._to_candidate("inventory_squeeze", p)

    def _sample_regime_switch(self) -> Candidate:
        while True:
            params = {
                "capture": self.rng.choice(self.rs_capture),
                "extract": self.rng.choice(self.rs_extract),
                "spike": self.rng.choice(self.rs_spike),
                "hit_premium": self.rng.choice(self.rs_hit_premium),
                "hard_den": self.rng.choice(self.rs_hard_den),
                "up_mult": self.rng.choice(self.rs_up_mult),
                "down_div": self.rng.choice(self.rs_down_div),
                "extract_len": self.rng.choice(self.rs_extract_len),
                "alpha_den": self.rng.choice(self.rs_alpha_den),
            }
            if params["capture"] <= params["extract"] <= params["spike"]:
                return self._to_candidate("regime_switch", params)

    def _mutate_regime_switch(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        fields = (
            ("capture", self.rs_capture),
            ("extract", self.rs_extract),
            ("spike", self.rs_spike),
            ("hit_premium", self.rs_hit_premium),
            ("hard_den", self.rs_hard_den),
            ("up_mult", self.rs_up_mult),
            ("down_div", self.rs_down_div),
            ("extract_len", self.rs_extract_len),
            ("alpha_den", self.rs_alpha_den),
        )
        for key, choices in fields:
            if self.rng.random() < 0.55:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        if not (p["capture"] <= p["extract"] <= p["spike"]):
            return self._sample_regime_switch()
        return self._to_candidate("regime_switch", p)

    def _sample_sym3_toxic_flow(self) -> Candidate:
        while True:
            params = {
                "retail": self.rng.choice(self.stf_retail),
                "medium": self.rng.choice(self.stf_medium),
                "arb": self.rng.choice(self.stf_arb),
                "small": self.rng.choice(self.stf_small),
                "large": self.rng.choice(self.stf_large),
                "extract_base": self.rng.choice(self.stf_extract_base),
                "extract_spike": self.rng.choice(self.stf_extract_spike),
                "hit_premium": self.rng.choice(self.stf_hit_premium),
                "flow_bump": self.rng.choice(self.stf_flow_bump),
                "bias_step": self.rng.choice(self.stf_bias_step),
                "bias_thresh": self.rng.choice(self.stf_bias_thresh),
                "up_mult": self.rng.choice(self.stf_up_mult),
                "alpha_den": self.rng.choice(self.stf_alpha_den),
                "extract_len": self.rng.choice(self.stf_extract_len),
            }
            valid = (
                params["retail"] <= params["medium"] <= params["arb"]
                and params["small"] > params["large"]
                and params["extract_base"] <= params["extract_spike"]
            )
            if valid:
                return self._to_candidate("sym3_toxic_flow", params)

    def _mutate_sym3_toxic_flow(self, params: dict[str, int]) -> Candidate:
        p = dict(params)
        fields = (
            ("retail", self.stf_retail),
            ("medium", self.stf_medium),
            ("arb", self.stf_arb),
            ("small", self.stf_small),
            ("large", self.stf_large),
            ("extract_base", self.stf_extract_base),
            ("extract_spike", self.stf_extract_spike),
            ("hit_premium", self.stf_hit_premium),
            ("flow_bump", self.stf_flow_bump),
            ("bias_step", self.stf_bias_step),
            ("bias_thresh", self.stf_bias_thresh),
            ("up_mult", self.stf_up_mult),
            ("alpha_den", self.stf_alpha_den),
            ("extract_len", self.stf_extract_len),
        )
        for key, choices in fields:
            if self.rng.random() < 0.55:
                idx = choices.index(_clamp_to_choices(p[key], choices))
                step = self.rng.choice((-2, -1, 1, 2))
                p[key] = choices[max(0, min(len(choices) - 1, idx + step))]
        valid = (
            p["retail"] <= p["medium"] <= p["arb"]
            and p["small"] > p["large"]
            and p["extract_base"] <= p["extract_spike"]
        )
        if not valid:
            return self._sample_sym3_toxic_flow()
        return self._to_candidate("sym3_toxic_flow", p)


def render_source(candidate: Candidate) -> str:
    p = candidate.params_dict
    if candidate.template == "sym3":
        return (
            SYM3_TEMPLATE.replace("__RETAIL__", str(p["retail"]))
            .replace("__MEDIUM__", str(p["medium"]))
            .replace("__ARB__", str(p["arb"]))
            .replace("__SMALL__", str(p["small"]))
            .replace("__LARGE__", str(p["large"]))
        )
    if candidate.template == "asym_hit":
        return (
            ASYM_HIT_TEMPLATE.replace("__RETAIL__", str(p["retail"]))
            .replace("__MID_PASSIVE__", str(p["mid_passive"]))
            .replace("__MID_HIT__", str(p["mid_hit"]))
            .replace("__ARB_PASSIVE__", str(p["arb_passive"]))
            .replace("__ARB_HIT__", str(p["arb_hit"]))
            .replace("__SMALL__", str(p["small"]))
            .replace("__LARGE__", str(p["large"]))
        )
    if candidate.template == "ewma_spike":
        return (
            EWMA_SPIKE_TEMPLATE.replace("__BASE__", str(p["base"]))
            .replace("__DISCOUNT__", str(p["discount"]))
            .replace("__SPIKE__", str(p["spike"]))
            .replace("__HIT_PREMIUM__", str(p["hit_premium"]))
            .replace("__DECAY__", str(p["decay"]))
            .replace("__HARD_DEN__", str(p["hard_den"]))
            .replace("__ALPHA_DEN__", str(p["alpha_den"]))
            .replace("__ARB_MULT__", str(p["arb_mult"]))
            .replace("__SPIKE_LEN__", str(p["spike_len"]))
        )
    if candidate.template == "pressure_asym":
        return (
            PRESSURE_ASYM_TEMPLATE.replace("__BASE__", str(p["base"]))
            .replace("__HIGH__", str(p["high"]))
            .replace("__PRESSURE__", str(p["pressure"]))
            .replace("__LARGE_DEN__", str(p["large_den"]))
            .replace("__ARB_BUMP__", str(p["arb_bump"]))
        )
    if candidate.template == "inventory_squeeze":
        return (
            INVENTORY_SQUEEZE_TEMPLATE.replace("__BASE__", str(p["base"]))
            .replace("__SQUEEZE__", str(p["squeeze"]))
            .replace("__ENTER__", str(p["enter"]))
            .replace("__EXIT__", str(p["exit"]))
            .replace("__LARGE_DEN__", str(p["large_den"]))
            .replace("__ARB_BUMP__", str(p["arb_bump"]))
        )
    if candidate.template == "regime_switch":
        return (
            REGIME_SWITCH_TEMPLATE.replace("__CAPTURE__", str(p["capture"]))
            .replace("__EXTRACT__", str(p["extract"]))
            .replace("__SPIKE__", str(p["spike"]))
            .replace("__HIT_PREMIUM__", str(p["hit_premium"]))
            .replace("__HARD_DEN__", str(p["hard_den"]))
            .replace("__UP_MULT__", str(p["up_mult"]))
            .replace("__DOWN_DIV__", str(p["down_div"]))
            .replace("__EXTRACT_LEN__", str(p["extract_len"]))
            .replace("__ALPHA_DEN__", str(p["alpha_den"]))
        )
    if candidate.template == "sym3_toxic_flow":
        return (
            SYM3_TOXIC_FLOW_TEMPLATE.replace("__RETAIL__", str(p["retail"]))
            .replace("__MEDIUM__", str(p["medium"]))
            .replace("__ARB__", str(p["arb"]))
            .replace("__SMALL__", str(p["small"]))
            .replace("__LARGE__", str(p["large"]))
            .replace("__EXTRACT_BASE__", str(p["extract_base"]))
            .replace("__EXTRACT_SPIKE__", str(p["extract_spike"]))
            .replace("__HIT_PREMIUM__", str(p["hit_premium"]))
            .replace("__FLOW_BUMP__", str(p["flow_bump"]))
            .replace("__BIAS_STEP__", str(p["bias_step"]))
            .replace("__BIAS_THRESH__", str(p["bias_thresh"]))
            .replace("__UP_MULT__", str(p["up_mult"]))
            .replace("__ALPHA_DEN__", str(p["alpha_den"]))
            .replace("__EXTRACT_LEN__", str(p["extract_len"]))
        )
    raise ValueError(f"unknown template: {candidate.template}")


def dominates(a: EvalResult, b: EvalResult) -> bool:
    better_or_equal = a.edge >= b.edge and a.win_rate <= b.win_rate
    strictly_better = a.edge > b.edge or a.win_rate < b.win_rate
    return better_or_equal and strictly_better


def pareto_frontier(results: list[EvalResult]) -> list[EvalResult]:
    frontier: list[EvalResult] = []
    for r in results:
        dominated = False
        for other in results:
            if other is r:
                continue
            if dominates(other, r):
                dominated = True
                break
        if not dominated:
            frontier.append(r)
    frontier.sort(key=lambda x: (-x.edge, x.win_rate))
    return frontier


class Optimizer:
    def __init__(self, *, rust_workers: int, target_edge: float):
        self.validator = SolidityValidator()
        self.compiler = SolidityCompiler()
        self.baseline = load_vanilla_strategy()
        self.rust_workers = rust_workers
        self.target_edge = target_edge
        self._runner_cache: dict[int, MatchRunner] = {}
        self._compile_cache: dict[str, tuple[bytes, list[Any]]] = {}
        self._eval_cache: dict[tuple[str, int], EvalResult] = {}

    def _get_runner(self, n_sims: int) -> MatchRunner:
        if n_sims not in self._runner_cache:
            config = amm_sim_rs.SimulationConfig(
                n_steps=BASELINE_SETTINGS.n_steps,
                initial_price=BASELINE_SETTINGS.initial_price,
                initial_x=BASELINE_SETTINGS.initial_x,
                initial_y=BASELINE_SETTINGS.initial_y,
                gbm_mu=BASELINE_SETTINGS.gbm_mu,
                gbm_sigma=(BASELINE_VARIANCE.gbm_sigma_min + BASELINE_VARIANCE.gbm_sigma_max) / 2,
                gbm_dt=BASELINE_SETTINGS.gbm_dt,
                retail_arrival_rate=(BASELINE_VARIANCE.retail_arrival_rate_min + BASELINE_VARIANCE.retail_arrival_rate_max) / 2,
                retail_mean_size=(BASELINE_VARIANCE.retail_mean_size_min + BASELINE_VARIANCE.retail_mean_size_max) / 2,
                retail_size_sigma=BASELINE_SETTINGS.retail_size_sigma,
                retail_buy_prob=BASELINE_SETTINGS.retail_buy_prob,
                seed=None,
            )
            self._runner_cache[n_sims] = MatchRunner(
                n_simulations=n_sims,
                config=config,
                n_workers=self.rust_workers,
                variance=BASELINE_VARIANCE,
            )
        return self._runner_cache[n_sims]

    def _compile_candidate(self, candidate: Candidate) -> tuple[bytes, list[Any]]:
        cached = self._compile_cache.get(candidate.key)
        if cached is not None:
            return cached

        source = render_source(candidate)
        validation = self.validator.validate(source)
        if not validation.valid:
            raise RuntimeError(f"Validation failed for {candidate.key}: {validation.errors}")

        compiled = self.compiler.compile(source)
        if not compiled.success:
            raise RuntimeError(f"Compilation failed for {candidate.key}: {compiled.errors}")

        result = (bytes(compiled.bytecode), compiled.abi)
        self._compile_cache[candidate.key] = result
        return result

    def evaluate(self, candidate: Candidate, n_sims: int, stage: str) -> EvalResult:
        key = (candidate.key, n_sims)
        if key in self._eval_cache:
            cached = self._eval_cache[key]
            # Keep original numbers, only stage label differs in reports.
            return EvalResult(
                candidate_key=cached.candidate_key,
                template=cached.template,
                params=cached.params,
                n_sims=cached.n_sims,
                edge=cached.edge,
                norm_edge=cached.norm_edge,
                wins=cached.wins,
                total=cached.total,
                stage=stage,
                eval_s=0.0,
            )

        start = time.time()
        bytecode, abi = self._compile_candidate(candidate)
        strategy = EVMStrategyAdapter(bytecode=bytecode, abi=abi)
        runner = self._get_runner(n_sims)
        match = runner.run_match(strategy, self.baseline, store_results=False)
        elapsed = time.time() - start

        total = match.wins_a + match.wins_b + match.draws
        result = EvalResult(
            candidate_key=candidate.key,
            template=candidate.template,
            params=candidate.params_dict,
            n_sims=n_sims,
            edge=float(match.total_edge_a / n_sims),
            norm_edge=float(match.total_edge_b / n_sims),
            wins=match.wins_a,
            total=total,
            stage=stage,
            eval_s=elapsed,
        )
        self._eval_cache[key] = result
        return result

    def evaluate_batch(self, candidates: list[Candidate], *, n_sims: int, stage: str) -> list[EvalResult]:
        results: list[EvalResult] = []
        best_edge = float("-inf")
        for i, candidate in enumerate(candidates, start=1):
            r = self.evaluate(candidate, n_sims=n_sims, stage=stage)
            results.append(r)
            if r.edge > best_edge:
                best_edge = r.edge
            if i == 1 or i % 10 == 0 or i == len(candidates):
                print(
                    f"[{stage}] {i:4d}/{len(candidates):4d} "
                    f"best_edge={best_edge:8.2f} target_hit={best_edge >= self.target_edge}",
                    flush=True,
                )
        return results


def select_elites(results: list[EvalResult], limit: int, objective: str) -> list[EvalResult]:
    if not results:
        return []
    if objective == "edge":
        return sorted(results, key=lambda r: r.edge, reverse=True)[:limit]

    by_edge = sorted(results, key=lambda r: r.edge, reverse=True)[: max(10, limit // 2)]
    low_win = sorted([r for r in results if r.win_rate <= 0.05], key=lambda r: r.edge, reverse=True)[: max(10, limit // 3)]
    frontier = pareto_frontier(results)[: max(10, limit // 2)]

    chosen: list[EvalResult] = []
    seen: set[str] = set()
    for group in (by_edge, low_win, frontier):
        for r in group:
            if r.candidate_key not in seen:
                chosen.append(r)
                seen.add(r.candidate_key)
            if len(chosen) >= limit:
                return chosen
    return chosen


def make_unique(candidates: list[Candidate]) -> list[Candidate]:
    unique: list[Candidate] = []
    seen: set[str] = set()
    for c in candidates:
        if c.key in seen:
            continue
        seen.add(c.key)
        unique.append(c)
    return unique


def parse_templates_arg(raw: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if not raw.strip():
        return allowed
    selected = tuple(t.strip() for t in raw.split(",") if t.strip())
    if not selected:
        return allowed
    invalid = [t for t in selected if t not in allowed]
    if invalid:
        raise ValueError(f"unknown templates in --stage1-templates: {', '.join(invalid)}")
    return selected


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_from_row(row: dict[str, Any]) -> Candidate | None:
    template = row.get("template")
    params = row.get("params")
    if not isinstance(template, str) or not isinstance(params, dict):
        return None
    normalized: list[tuple[str, int]] = []
    for k, v in params.items():
        if not isinstance(k, str):
            return None
        try:
            normalized.append((k, int(v)))
        except (TypeError, ValueError):
            return None
    return Candidate(template=template, params=tuple(sorted(normalized)))


def load_stage1_seed_candidates(
    seed_json_path: str,
    *,
    allowed_templates: set[str],
    top_n: int,
    lowwin_n: int,
    lowwin_threshold: float,
) -> list[Candidate]:
    if not seed_json_path or (top_n <= 0 and lowwin_n <= 0):
        return []

    payload = json.loads(Path(seed_json_path).read_text())
    rows = payload.get("stage1", [])
    if not isinstance(rows, list):
        raise ValueError(f"seed JSON missing list field 'stage1': {seed_json_path}")

    filtered_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("template") in allowed_templates
    ]
    by_edge = sorted(filtered_rows, key=lambda r: _coerce_float(r.get("edge"), float("-inf")), reverse=True)
    lowwin = sorted(
        [r for r in filtered_rows if _coerce_float(r.get("win_rate"), 1.0) <= lowwin_threshold],
        key=lambda r: _coerce_float(r.get("edge"), float("-inf")),
        reverse=True,
    )

    chosen: list[Candidate] = []
    seen: set[str] = set()
    for group, limit in ((by_edge, top_n), (lowwin, lowwin_n)):
        if limit <= 0:
            continue
        added = 0
        for row in group:
            cand = _candidate_from_row(row)
            if cand is None or cand.key in seen:
                continue
            chosen.append(cand)
            seen.add(cand.key)
            added += 1
            if added >= limit:
                break
    return chosen


def print_top(results: list[EvalResult], *, title: str, limit: int) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    if not results:
        print("No results.")
        return
    for r in sorted(results, key=lambda x: x.edge, reverse=True)[:limit]:
        print(
            f"edge={r.edge:8.2f} norm={r.norm_edge:8.2f} "
            f"win={r.win_rate*100:6.2f}% wins={r.wins:3d}/{r.total:<3d} "
            f"{r.template} {r.params}"
        )


def print_best_by_win_bucket(results: list[EvalResult]) -> None:
    print("\nStage A Best By Win-Rate Bucket")
    print("===============================")
    if not results:
        print("No results.")
        return
    buckets = [(0, 1), (1, 5), (5, 10), (10, 25), (25, 50), (50, 75), (75, 100)]
    for low, high in buckets:
        in_bucket = [r for r in results if low <= r.win_rate * 100 < high]
        if not in_bucket:
            continue
        best = max(in_bucket, key=lambda r: r.edge)
        print(
            f"{low:>2d}-{high:>3d}%: edge={best.edge:8.2f} "
            f"win={best.win_rate*100:6.2f}% {best.template} {best.params}"
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sequential Pareto optimizer for AMM strategy params")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--objective", choices=("pareto", "edge"), default="pareto")
    p.add_argument("--target-edge", type=float, default=520.0)
    p.add_argument("--rust-workers", type=int, default=4)

    p.add_argument("--stage1-candidates", type=int, default=300)
    p.add_argument("--stage1-sims", type=int, default=40)
    p.add_argument("--stage1-only", action="store_true")
    p.add_argument("--stage1-templates", type=str, default="")
    p.add_argument("--stage1-seed-json", type=str, default="")
    p.add_argument("--stage1-seed-top", type=int, default=0)
    p.add_argument("--stage1-seed-lowwin", type=int, default=0)
    p.add_argument("--stage1-seed-lowwin-threshold", type=float, default=0.05)
    p.add_argument("--stage1-seed-mutants", type=int, default=0)

    p.add_argument("--elite-count", type=int, default=30)
    p.add_argument("--stage2-per-elite", type=int, default=8)
    p.add_argument("--stage2-fresh", type=int, default=120)
    p.add_argument("--stage2-sims", type=int, default=80)

    p.add_argument("--verify-top", type=int, default=12)
    p.add_argument("--carry-stage1-top", type=int, default=8)
    p.add_argument("--carry-stage1-lowwin", type=int, default=8)
    p.add_argument("--carry-stage1-lowwin-threshold", type=float, default=0.01)
    p.add_argument("--verify-sims", type=int, default=500)
    p.add_argument("--final-top", type=int, default=5)
    p.add_argument("--final-sims", type=int, default=1000)

    p.add_argument("--report-top", type=int, default=20)
    p.add_argument("--output-json", type=str, default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    factory = CandidateFactory(rng)
    optimizer = Optimizer(rust_workers=args.rust_workers, target_edge=args.target_edge)
    try:
        stage1_templates = parse_templates_arg(args.stage1_templates, factory.templates)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print("Pareto Optimization (edge up, win-rate down)")
    print(
        f"seed={args.seed} objective={args.objective} "
        f"target_edge={args.target_edge:.2f} rust_workers={args.rust_workers}"
    )
    print(f"stage1_templates={','.join(stage1_templates)}")

    # Stage A: broad random search.
    stage1_candidates: list[Candidate] = []
    if args.stage1_seed_json:
        seeded = load_stage1_seed_candidates(
            args.stage1_seed_json,
            allowed_templates=set(stage1_templates),
            top_n=args.stage1_seed_top,
            lowwin_n=args.stage1_seed_lowwin,
            lowwin_threshold=args.stage1_seed_lowwin_threshold,
        )
        stage1_candidates.extend(seeded)
        for c in seeded:
            for _ in range(args.stage1_seed_mutants):
                stage1_candidates.append(factory.mutate(c))
        print(
            "Stage A seeds "
            f"(json={args.stage1_seed_json}): base={len(seeded)} "
            f"mutants={len(seeded) * max(0, args.stage1_seed_mutants)}"
        )

    sample_i = 0
    while len(stage1_candidates) < args.stage1_candidates:
        template = stage1_templates[sample_i % len(stage1_templates)]
        stage1_candidates.append(factory.sample(template))
        sample_i += 1
    stage1_candidates = make_unique(stage1_candidates)
    stage1_seen = {c.key for c in stage1_candidates}
    while len(stage1_candidates) < args.stage1_candidates:
        template = stage1_templates[sample_i % len(stage1_templates)]
        c = factory.sample(template)
        sample_i += 1
        if c.key not in stage1_seen:
            stage1_candidates.append(c)
            stage1_seen.add(c.key)
    if len(stage1_candidates) > args.stage1_candidates:
        stage1_candidates = stage1_candidates[: args.stage1_candidates]

    print(f"\nStage A: random search ({len(stage1_candidates)} candidates @ {args.stage1_sims} sims)")
    stage1_results = optimizer.evaluate_batch(stage1_candidates, n_sims=args.stage1_sims, stage="stage1")
    print_top(stage1_results, title="Stage A Top Edge", limit=args.report_top)
    print_top(pareto_frontier(stage1_results), title="Stage A Pareto Frontier", limit=args.report_top)
    print_best_by_win_bucket(stage1_results)

    if args.stage1_only:
        best = max(stage1_results, key=lambda r: r.edge)
        print(
            f"\nStage A only best: edge={best.edge:.2f} norm={best.norm_edge:.2f} "
            f"win={best.win_rate*100:.2f}% {best.template} {best.params}"
        )
        if args.output_json:
            payload = {
                "args": vars(args),
                "stage1": [asdict(r) | {"win_rate": r.win_rate} for r in stage1_results],
                "stage1_frontier": [asdict(r) | {"win_rate": r.win_rate} for r in pareto_frontier(stage1_results)],
            }
            out_path = Path(args.output_json)
            out_path.write_text(json.dumps(payload, indent=2))
            print(f"Wrote JSON report: {out_path}")
        return

    # Stage B: local mutations around elites + fresh random.
    elites = select_elites(stage1_results, limit=args.elite_count, objective=args.objective)
    stage2_candidates: list[Candidate] = []
    for e in elites:
        base_c = Candidate(template=e.template, params=tuple(sorted(e.params.items())))
        stage2_candidates.append(base_c)
        for _ in range(args.stage2_per_elite):
            stage2_candidates.append(factory.mutate(base_c))
    while len(stage2_candidates) < (len(elites) * (args.stage2_per_elite + 1) + args.stage2_fresh):
        stage2_candidates.append(factory.sample(rng.choice(factory.templates)))
    stage2_candidates = make_unique(stage2_candidates)

    print(f"\nStage B: local + fresh ({len(stage2_candidates)} candidates @ {args.stage2_sims} sims)")
    stage2_results = optimizer.evaluate_batch(stage2_candidates, n_sims=args.stage2_sims, stage="stage2")
    print_top(stage2_results, title="Stage B Top Edge", limit=args.report_top)
    print_top(
        [r for r in stage2_results if r.win_rate <= 0.01],
        title="Stage B Top Edge (<=1% wins)",
        limit=args.report_top,
    )

    # Stage C: higher-confidence verification.
    # Important: always carry some Stage A leaders directly, so Stage B noise
    # cannot prune strong regions discovered during broad exploration.
    pool_for_verify = []
    pool_for_verify.extend(sorted(stage2_results, key=lambda r: r.edge, reverse=True)[: args.verify_top])
    pool_for_verify.extend(sorted(stage1_results, key=lambda r: r.edge, reverse=True)[: args.carry_stage1_top])
    if args.objective != "edge":
        stage1_low = [r for r in stage1_results if r.win_rate <= args.carry_stage1_lowwin_threshold]
        pool_for_verify.extend(sorted(stage1_low, key=lambda r: r.edge, reverse=True)[: args.carry_stage1_lowwin])

    verify_candidates = [
        Candidate(template=r.template, params=tuple(sorted(r.params.items())))
        for r in pool_for_verify
    ]
    verify_candidates = make_unique(verify_candidates)
    verify_meta = (
        f"[stage2_top={args.verify_top}, stage1_top={args.carry_stage1_top}]"
        if args.objective == "edge"
        else (
            f"[stage2_top={args.verify_top}, stage1_top={args.carry_stage1_top}, "
            f"stage1_lowwin={args.carry_stage1_lowwin}]"
        )
    )
    print(f"\nStage C: verify ({len(verify_candidates)} candidates @ {args.verify_sims} sims) {verify_meta}")
    verify_results = optimizer.evaluate_batch(verify_candidates, n_sims=args.verify_sims, stage="verify")
    print_top(verify_results, title="Stage C Top Edge", limit=args.report_top)

    # Stage D: final confirmation on top finalists.
    finalists_seed = sorted(verify_results, key=lambda r: r.edge, reverse=True)[: args.final_top]
    finalists = [Candidate(template=r.template, params=tuple(sorted(r.params.items()))) for r in finalists_seed]
    finalists = make_unique(finalists)
    print(f"\nStage D: final ({len(finalists)} candidates @ {args.final_sims} sims)")
    final_results = optimizer.evaluate_batch(finalists, n_sims=args.final_sims, stage="final")
    print_top(final_results, title="Final Top Edge", limit=args.report_top)

    final_frontier = pareto_frontier(final_results)
    print_top(final_frontier, title="Final Pareto Frontier", limit=args.report_top)

    best = max(final_results, key=lambda r: r.edge)
    print(
        f"\nBest final: edge={best.edge:.2f} norm={best.norm_edge:.2f} "
        f"win={best.win_rate*100:.2f}% {best.template} {best.params}"
    )
    print(f"Target hit (edge >= {args.target_edge:.2f}): {best.edge >= args.target_edge}")

    if args.output_json:
        payload = {
            "args": vars(args),
            "stage1": [asdict(r) | {"win_rate": r.win_rate} for r in stage1_results],
            "stage2": [asdict(r) | {"win_rate": r.win_rate} for r in stage2_results],
            "verify": [asdict(r) | {"win_rate": r.win_rate} for r in verify_results],
            "final": [asdict(r) | {"win_rate": r.win_rate} for r in final_results],
            "final_frontier": [asdict(r) | {"win_rate": r.win_rate} for r in final_frontier],
        }
        out_path = Path(args.output_json)
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"Wrote JSON report: {out_path}")


if __name__ == "__main__":
    main()
