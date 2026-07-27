"""
GAIA Commodities — local indicator calculations.

All computed from raw OHLC in pandas, no external indicator API calls
(same fix TITAN applied after burning through Twelve Data credits).
"""

import pandas as pd
from app import config


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period: int, stddev: float):
    mid = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = mid + stddev * std
    lower = mid - stddev * std
    return upper, mid, lower


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def compute_all(signal_df: pd.DataFrame, trend_df: pd.DataFrame, atr_df: pd.DataFrame) -> dict:
    """
    Runs every indicator needed for the confluence engine and returns the
    latest values in a flat dict. Keeping this in one place means
    signal_engine.py never touches raw OHLC directly.
    """
    close = signal_df["close"]

    ema_fast = ema(close, config.EMA_FAST)
    ema_slow = ema(close, config.EMA_SLOW)
    rsi_val = rsi(close, config.RSI_PERIOD)
    macd_line, macd_signal, macd_hist = macd(
        close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )
    bb_upper, bb_mid, bb_lower = bollinger_bands(close, config.BB_PERIOD, config.BB_STDDEV)

    trend_close = trend_df["close"]
    trend_ema_fast = ema(trend_close, config.EMA_FAST)
    trend_ema_slow = ema(trend_close, config.EMA_SLOW)

    atr_val = atr(atr_df, config.ATR_PERIOD)

    return {
        "price": close.iloc[-1],
        "ema_fast": ema_fast.iloc[-1],
        "ema_slow": ema_slow.iloc[-1],
        "ema_fast_prev": ema_fast.iloc[-2],
        "ema_slow_prev": ema_slow.iloc[-2],
        "rsi": rsi_val.iloc[-1],
        "macd_line": macd_line.iloc[-1],
        "macd_signal": macd_signal.iloc[-1],
        "macd_hist": macd_hist.iloc[-1],
        "macd_hist_prev": macd_hist.iloc[-2],
        "bb_upper": bb_upper.iloc[-1],
        "bb_mid": bb_mid.iloc[-1],
        "bb_lower": bb_lower.iloc[-1],
        "trend_ema_fast": trend_ema_fast.iloc[-1],
        "trend_ema_slow": trend_ema_slow.iloc[-1],
        "atr": atr_val.iloc[-1],
    }
