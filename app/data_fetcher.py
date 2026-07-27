"""
GAIA Commodities — market data fetcher.

Lesson carried over from TITAN: Twelve Data credits burn fast if you fetch
every indicator separately. This module pulls ONE raw OHLC time series per
instrument per timeframe, caches it in memory for the poll interval, and
every indicator is computed locally in indicators.py. No indicator-specific
API calls, ever.
"""

import time
import logging
import requests
import pandas as pd

from app import config

logger = logging.getLogger("gaia.data_fetcher")

_BASE_URL = "https://api.twelvedata.com/time_series"

# simple in-memory cache: {(symbol, interval): (timestamp_fetched, dataframe)}
_cache: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 60  # avoid re-fetching same symbol/timeframe within a burst of calls


def _fetch_raw(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    cache_key = (symbol, interval)
    now = time.time()

    cached = _cache.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": config.TWELVE_DATA_API_KEY,
        "order": "ASC",
    }

    resp = requests.get(_BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") == "error":
        raise RuntimeError(f"Twelve Data error for {symbol} ({interval}): {payload.get('message')}")

    values = payload.get("values", [])
    if not values:
        raise RuntimeError(f"Twelve Data returned no candles for {symbol} ({interval})")

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

    df = df.sort_values("datetime").reset_index(drop=True)

    _cache[cache_key] = (now, df)
    return df


def get_signal_candles(instrument_key: str) -> pd.DataFrame:
    """OHLC candles on the timeframe the confluence engine scores on."""
    symbol = config.INSTRUMENTS[instrument_key]["symbol"]
    return _fetch_raw(symbol, config.SIGNAL_TIMEFRAME, config.CANDLE_LOOKBACK)


def get_trend_candles(instrument_key: str) -> pd.DataFrame:
    """Higher-timeframe candles used for the trend filter."""
    symbol = config.INSTRUMENTS[instrument_key]["symbol"]
    return _fetch_raw(symbol, config.TREND_TIMEFRAME, config.CANDLE_LOOKBACK)


def get_atr_candles(instrument_key: str) -> pd.DataFrame:
    """Candles used for ATR-based SL/TP sizing."""
    symbol = config.INSTRUMENTS[instrument_key]["symbol"]
    if config.ATR_TIMEFRAME == config.TREND_TIMEFRAME:
        return get_trend_candles(instrument_key)
    return _fetch_raw(symbol, config.ATR_TIMEFRAME, config.CANDLE_LOOKBACK)
