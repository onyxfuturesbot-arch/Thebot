"""
Onyx Commodities — confluence signal engine.

Scores each instrument against a stack of independent indicator checks.
A signal fires only when enough of the stack agrees AND the instrument
isn't in a session-filtered or loss-paused state — same guardrail pattern
as AURUM (session filtering, consecutive-loss pause).
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

from app import config, data_fetcher, indicators

logger = logging.getLogger("onyx.signal_engine")


@dataclass
class Signal:
    instrument_key: str
    direction: str          # "BUY" or "SELL"
    score: int
    max_score: int
    price: float
    stop_loss: float
    take_profits: list[float]
    reasons: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Per-instrument state (in-memory; swap for persistent storage if you want
# this to survive restarts — see README for the Railway/DB note)
# ---------------------------------------------------------------------------
_consecutive_losses: dict[str, int] = {}
_paused_until: dict[str, datetime] = {}


def record_trade_result(instrument_key: str, was_loss: bool) -> None:
    """Call this from your feedback loop once a signalled trade closes."""
    if was_loss:
        _consecutive_losses[instrument_key] = _consecutive_losses.get(instrument_key, 0) + 1
        if _consecutive_losses[instrument_key] >= config.MAX_CONSECUTIVE_LOSSES:
            pause_until = datetime.now(timezone.utc).timestamp() + (
                config.PAUSE_HOURS_AFTER_MAX_LOSSES * 3600
            )
            _paused_until[instrument_key] = datetime.fromtimestamp(pause_until, tz=timezone.utc)
            logger.warning(
                "%s hit %s consecutive losses — pausing until %s",
                instrument_key, config.MAX_CONSECUTIVE_LOSSES, _paused_until[instrument_key],
            )
    else:
        _consecutive_losses[instrument_key] = 0


def _is_paused(instrument_key: str) -> bool:
    until = _paused_until.get(instrument_key)
    if until is None:
        return False
    if datetime.now(timezone.utc) >= until:
        del _paused_until[instrument_key]
        return False
    return True


def _in_session(instrument_key: str) -> bool:
    category = config.INSTRUMENTS[instrument_key]["category"]
    windows = config.SESSION_FILTERS_UTC.get(category, [])
    if not windows:
        return True
    hour = datetime.now(timezone.utc).hour
    return any(start <= hour < end for start, end in windows)


def _score_bullish(vals: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    if vals["ema_fast"] > vals["ema_slow"]:
        score += 1
        reasons.append("EMA20 > EMA50 (uptrend)")
    if vals["trend_ema_fast"] > vals["trend_ema_slow"]:
        score += 1
        reasons.append("HTF trend bullish")
    if vals["rsi"] > 50 and vals["rsi"] < config.RSI_OVERBOUGHT:
        score += 1
        reasons.append(f"RSI {vals['rsi']:.1f} bullish, not overbought")
    if vals["macd_line"] > vals["macd_signal"]:
        score += 1
        reasons.append("MACD above signal")
    if vals["macd_hist"] > vals["macd_hist_prev"]:
        score += 1
        reasons.append("MACD histogram rising")
    if vals["price"] > vals["bb_mid"]:
        score += 1
        reasons.append("Price above BB midline")
    if vals["ema_fast"] > vals["ema_fast_prev"]:
        score += 1
        reasons.append("EMA20 sloping up")

    return score, reasons


def _score_bearish(vals: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    if vals["ema_fast"] < vals["ema_slow"]:
        score += 1
        reasons.append("EMA20 < EMA50 (downtrend)")
    if vals["trend_ema_fast"] < vals["trend_ema_slow"]:
        score += 1
        reasons.append("HTF trend bearish")
    if vals["rsi"] < 50 and vals["rsi"] > config.RSI_OVERSOLD:
        score += 1
        reasons.append(f"RSI {vals['rsi']:.1f} bearish, not oversold")
    if vals["macd_line"] < vals["macd_signal"]:
        score += 1
        reasons.append("MACD below signal")
    if vals["macd_hist"] < vals["macd_hist_prev"]:
        score += 1
        reasons.append("MACD histogram falling")
    if vals["price"] < vals["bb_mid"]:
        score += 1
        reasons.append("Price below BB midline")
    if vals["ema_fast"] < vals["ema_fast_prev"]:
        score += 1
        reasons.append("EMA20 sloping down")

    return score, reasons


def _build_sl_tp(direction: str, price: float, atr_val: float) -> tuple[float, list[float]]:
    if direction == "BUY":
        sl = price - (atr_val * config.SL_ATR_MULTIPLIER)
        tps = [price + (atr_val * m) for m in config.TP_ATR_MULTIPLIERS]
    else:
        sl = price + (atr_val * config.SL_ATR_MULTIPLIER)
        tps = [price - (atr_val * m) for m in config.TP_ATR_MULTIPLIERS]
    return sl, tps


def evaluate_instrument(instrument_key: str) -> Signal | None:
    if _is_paused(instrument_key):
        logger.debug("%s is loss-paused, skipping", instrument_key)
        return None
    if not _in_session(instrument_key):
        logger.debug("%s outside session window, skipping", instrument_key)
        return None

    signal_df = data_fetcher.get_signal_candles(instrument_key)
    trend_df = data_fetcher.get_trend_candles(instrument_key)
    atr_df = data_fetcher.get_atr_candles(instrument_key)

    vals = indicators.compute_all(signal_df, trend_df, atr_df)

    bull_score, bull_reasons = _score_bullish(vals)
    bear_score, bear_reasons = _score_bearish(vals)

    if bull_score >= config.CONFLUENCE_THRESHOLD and bull_score > bear_score:
        sl, tps = _build_sl_tp("BUY", vals["price"], vals["atr"])
        return Signal(
            instrument_key=instrument_key,
            direction="BUY",
            score=bull_score,
            max_score=config.CONFLUENCE_MAX,
            price=vals["price"],
            stop_loss=sl,
            take_profits=tps,
            reasons=bull_reasons,
        )

    if bear_score >= config.CONFLUENCE_THRESHOLD and bear_score > bull_score:
        sl, tps = _build_sl_tp("SELL", vals["price"], vals["atr"])
        return Signal(
            instrument_key=instrument_key,
            direction="SELL",
            score=bear_score,
            max_score=config.CONFLUENCE_MAX,
            price=vals["price"],
            stop_loss=sl,
            take_profits=tps,
            reasons=bear_reasons,
        )

    return None


def scan_all() -> list[Signal]:
    signals = []
    for instrument_key in config.INSTRUMENTS:
        try:
            sig = evaluate_instrument(instrument_key)
            if sig:
                signals.append(sig)
        except Exception:
            logger.exception("Error evaluating %s", instrument_key)
    return signals
