from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class StrategySpec:
    strategy_id: str
    strategy_name: str
    strategy_type: str
    signal_fn: Callable[[pd.DataFrame, dict, int], pd.DataFrame]
