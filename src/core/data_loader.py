from __future__ import annotations

import shutil
import sqlite3
import tempfile
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


def _allow_csv_primary_source(root: Path) -> bool:
    return bool(load_backtest_config(root).get("allow_csv_primary_source", False))


def _allow_csv_fallback(root: Path) -> bool:
    return bool(load_backtest_config(root).get("allow_csv_fallback", False))


def _normalize_symbol_from_ticker(ticker: str) -> str:
    return ticker.split(".", 1)[0]


def _normalize_ticker_for_db(symbol: str) -> str:
    if "." in symbol or symbol.startswith("^"):
        return symbol
    return f"{symbol}.T"


def _resolve_database_source(root: Path) -> Path | None:
    config = load_backtest_config(root)
    database_path = config.get("database_path")
    if not database_path:
        return None
    return Path(str(database_path))


def _database_cache_path() -> Path:
    return Path(tempfile.gettempdir()) / "kabusoft004_prices.db"


def _ensure_database_copy(root: Path) -> Path | None:
    source = _resolve_database_source(root)
    if source is None:
        return None
    if not source.exists():
        raise FileNotFoundError(f"database_path does not exist: {source}")

    cache_path = _database_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    source_stat = source.stat()
    if (
        not cache_path.exists()
        or cache_path.stat().st_size != source_stat.st_size
        or cache_path.stat().st_mtime < source_stat.st_mtime
    ):
        shutil.copy2(source, cache_path)
    return cache_path


def _connect_database(root: Path) -> sqlite3.Connection:
    db_path = _ensure_database_copy(root)
    if db_path is None:
        raise FileNotFoundError("database_path is not configured")
    return sqlite3.connect(str(db_path))


def _select_universe_from_db(root: Path, universe_size: int) -> list[str]:
    query = """
    WITH ranked AS (
        SELECT
            ticker,
            close * volume AS traded_value,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
        FROM daily_prices
        WHERE ticker LIKE '%.T'
    )
    SELECT ticker
    FROM ranked
    WHERE rn <= 252
    GROUP BY ticker
    ORDER BY AVG(traded_value) DESC
    LIMIT ?
    """
    with _connect_database(root) as con:
        rows = con.execute(query, (int(universe_size),)).fetchall()
    return [_normalize_symbol_from_ticker(row[0]) for row in rows]


def _load_market_data_from_db(root: Path, universe_size: int) -> pd.DataFrame:
    symbols = select_universe(root, universe_size)
    tickers = [_normalize_ticker_for_db(symbol) for symbol in symbols]
    placeholders = ",".join("?" for _ in tickers)
    query = f"""
    SELECT ticker, date, open, high, low, close, volume
    FROM daily_prices
    WHERE ticker IN ({placeholders})
    ORDER BY ticker, date
    """
    with _connect_database(root) as con:
        market = pd.read_sql_query(query, con, params=tickers)
    market["date"] = pd.to_datetime(market["date"])
    market["symbol"] = market["ticker"].map(_normalize_symbol_from_ticker)
    return market[["date", "symbol", "open", "high", "low", "close", "volume"]].copy()


def _read_liquidity(path: Path) -> tuple[str, float]:
    df = pd.read_csv(path, usecols=["Close", "Volume"])
    traded_value = (df["Close"].astype(float) * df["Volume"].astype(float)).tail(252)
    return path.stem, float(traded_value.median())


def _select_universe_from_csv(root: Path, universe_size: int) -> list[str]:
    raw_dir = root / "data" / "raw"
    liquidities = [_read_liquidity(path) for path in sorted(raw_dir.glob("*.csv"))]
    liquidities.sort(key=lambda item: item[1], reverse=True)
    return [symbol for symbol, _ in liquidities[:universe_size]]


def select_universe(root: Path, universe_size: int) -> list[str]:
    if _resolve_database_source(root) is not None:
        return _select_universe_from_db(root, universe_size)
    if not _allow_csv_primary_source(root):
        raise FileNotFoundError("CSV primary source is disabled and database_path is not available")
    return _select_universe_from_csv(root, universe_size)


@lru_cache(maxsize=2)
def load_market_data(root_str: str, universe_size: int) -> pd.DataFrame:
    root = Path(root_str)
    if _resolve_database_source(root) is not None:
        market = _load_market_data_from_db(root, universe_size)
    else:
        if not _allow_csv_primary_source(root):
            raise FileNotFoundError("CSV primary source is disabled and database_path is not available")
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

    return market.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_symbol_data(root: Path, symbol: str) -> pd.DataFrame:
    if _resolve_database_source(root) is not None:
        ticker = _normalize_ticker_for_db(symbol)
        query = """
        SELECT ticker, date, open, high, low, close, volume
        FROM daily_prices
        WHERE ticker = ?
        ORDER BY date
        """
        with _connect_database(root) as con:
            df = pd.read_sql_query(query, con, params=[ticker])
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df["symbol"] = df["ticker"].map(_normalize_symbol_from_ticker)
            return df[["date", "symbol", "open", "high", "low", "close", "volume"]].copy()
        if not _allow_csv_fallback(root):
            return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])

    elif not _allow_csv_primary_source(root):
        raise FileNotFoundError("CSV primary source is disabled and database_path is not available")

    path = root / "data" / "raw" / f"{symbol}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    df = pd.read_csv(path)
    df.columns = [column.lower() for column in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = symbol
    return df[["date", "symbol", "open", "high", "low", "close", "volume"]].copy()


def apply_backtest_date_range(market: pd.DataFrame, config: dict) -> pd.DataFrame:
    filtered = market.copy()
    start_date = config.get("start_date")
    end_date = config.get("end_date")

    if start_date:
        filtered = filtered[filtered["date"] >= pd.to_datetime(start_date)]
    if end_date:
        filtered = filtered[filtered["date"] <= pd.to_datetime(end_date)]

    return filtered.sort_values(["symbol", "date"]).reset_index(drop=True)
