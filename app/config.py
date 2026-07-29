"""
Onyx Commodities — configuration.

Mirrors the pattern used in AURUM / TITAN: one place to tune instruments,
indicator parameters, and confluence thresholds without touching logic code.
"""

import os

# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
# symbol        -> the Twelve Data symbol to query
# display_name  -> used in Telegram messages
# pip_size      -> minimum price increment, used for SL/TP display rounding
# category      -> metals / energy / ags (used for session filtering)
INSTRUMENTS = {
    "GOLD": {
        "symbol": "XAU/USD",
        "display_name": "Gold",
        "pip_size": 0.01,
        "category": "metals",
        "tradovate_root": "GC",
        "tradovate_exchange": "COMEX",
        "instrument_type": "spot",       # real spot price, matches futures closely
    },
    "CORN": {
        "symbol": "CORN",
        "display_name": "Corn Futures",
        "pip_size": 0.25,
        "category": "ags",
        "tradovate_root": "ZC",
        "tradovate_exchange": "CBOT",
        "instrument_type": "etf_proxy",  # CORN (Teucrium Corn Fund) — confirmed working
    },

    # Commented out until check_symbols.py confirms these ETF tickers actually
    # return data on your Twelve Data plan (never verified — WTI/Copper/Coffee
    # 404'd under their real futures symbols, so we picked these as proxies
    # but didn't test them before this trim). Uncomment and re-test before
    # re-enabling.
    #
    # "WTI": {
    #     "symbol": "USO",
    #     "display_name": "WTI Crude Oil",
    #     "pip_size": 0.01,
    #     "category": "energy",
    #     "tradovate_root": "CL",
    #     "tradovate_exchange": "NYMEX",
    #     "instrument_type": "etf_proxy",
    # },
    # "COPPER": {
    #     "symbol": "CPER",
    #     "display_name": "Copper",
    #     "pip_size": 0.0001,
    #     "category": "metals",
    #     "tradovate_root": "HG",
    #     "tradovate_exchange": "COMEX",
    #     "instrument_type": "etf_proxy",
    # },
    # "COFFEE": {
    #     "symbol": "JO",
    #     "display_name": "Coffee Futures",
    #     "pip_size": 0.05,
    #     "category": "ags",
    #     "tradovate_root": "KC",
    #     "tradovate_exchange": "ICE",
    #     "instrument_type": "etf_proxy",
    # },
}

# ---------------------------------------------------------------------------
# Timeframes
# ---------------------------------------------------------------------------
SIGNAL_TIMEFRAME = "15min"      # timeframe the confluence engine scores on
TREND_TIMEFRAME = "1h"          # higher-timeframe trend filter
ATR_TIMEFRAME = "1h"            # ATR used for SL/TP sizing (matches AURUM's H1 ATR approach)
CANDLE_LOOKBACK = 200           # bars pulled per request — enough for EMA50/RSI/MACD warmup

# ---------------------------------------------------------------------------
# Indicator parameters
# ---------------------------------------------------------------------------
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STDDEV = 2.0
ATR_PERIOD = 14

# ---------------------------------------------------------------------------
# Confluence scoring
# ---------------------------------------------------------------------------
# Each aligned indicator contributes 1 point. Max possible = 7.
# Start looser than AURUM's 9/9 (this is a new, unvalidated edge) — tighten
# once you have live/backtest data telling you which threshold performs.
CONFLUENCE_MAX = 7
CONFLUENCE_THRESHOLD = 5  # signal fires at 5/7 or better

# ---------------------------------------------------------------------------
# Risk / trade management
# ---------------------------------------------------------------------------
SL_ATR_MULTIPLIER = 1.5
TP_ATR_MULTIPLIERS = [1.5, 2.5, 4.0]  # three-tier TP, same pattern as AURUM

# Consecutive-loss circuit breaker (per instrument)
MAX_CONSECUTIVE_LOSSES = 3
PAUSE_HOURS_AFTER_MAX_LOSSES = 12

# ---------------------------------------------------------------------------
# Session filtering
# ---------------------------------------------------------------------------
# Ags are thin outside US floor hours; energy/metals trade cleaner in
# London + US overlap. Hours are UTC. Empty list = no restriction.
SESSION_FILTERS_UTC = {
    "metals": [(7, 20)],   # London open -> US close (applies to true spot/futures, e.g. Gold)
    "energy": [(7, 20)],
    "ags": [(13, 19)],     # CBOT floor-driven liquidity window
}

# ETF-proxied instruments (WTI/Copper/Corn/Coffee via USO/CPER/CORN/JO) only
# trade during US stock market hours, unlike the near-24h futures they track.
# This OVERRIDES the category-based window above whenever
# INSTRUMENTS[key]["instrument_type"] == "etf_proxy".
ETF_MARKET_HOURS_UTC = [(14, 21)]  # ~9:30am-4pm ET, UTC (adjust for DST manually if needed)

# ---------------------------------------------------------------------------
# External services (populate via environment variables on Railway)
# ---------------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# Polling interval for the signal loop, seconds. 15m candles -> no need to
# poll faster than every few minutes; keeps API credit usage sane.
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
