from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_backtest_config(root: Path) -> dict:
    return load_yaml(root / "config" / "backtest.yaml")


def load_feature_config(root: Path) -> dict:
    return load_yaml(root / "config" / "features.yaml")


def load_walkforward_config(root: Path) -> dict:
    return load_yaml(root / "config" / "walkforward.yaml")


def _read_liquidity(path: Path) -> tuple[str, float]:
    df = pd.read_csv(path, usecols=["Close", "Volume"])
    traded_value = (df["Close"].astype(float) * df["Volume"].astype(float)).tail(252)
    return path.stem, float(traded_value.median())


def select_universe(root: Path, universe_size: int) -> list[str]:
    raw_dir = root / "data" / "raw"
    liquidities = [_read_liquidity(path) for path in sorted(raw_dir.glob("*.csv"))]
    liquidities.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in liquidities[:universe_size]]


@lru_cache(maxsize=2)
def load_market_data(root_str: str, universe_size: int) -> pd.DataFrame:
    root = Path(root_str)
    symbols = select_universe(root, universe_size)
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        path = root / "data" / "raw" / f"{symbol}.csv"
        df = pd.read_csv(path)
        df.columns = [column.lower() for column in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        frames.append(
            df[["date", "symbol", "open", "high", "low", "close", "volume"]].copy()
        )

    market = pd.concat(frames, ignore_index=True)
    market = market.sort_values(["symbol", "date"]).reset_index(drop=True)
    return market
