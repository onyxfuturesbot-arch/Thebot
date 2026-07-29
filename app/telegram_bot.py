"""
Onyx Commodities — Telegram delivery.

Same channel-push pattern as AURUM/TITAN/CIPHER: format a Signal object into
a clean message and post it to the configured channel.
"""

import logging
import requests

from app import config
from app.signal_engine import Signal

logger = logging.getLogger("onyx.telegram_bot")

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _format_message(signal: Signal) -> str:
    instrument = config.INSTRUMENTS[signal.instrument_key]
    display_name = instrument["display_name"]
    pip_size = instrument["pip_size"]
    tradovate_root = instrument.get("tradovate_root", "")
    tradovate_exchange = instrument.get("tradovate_exchange", "")
    is_etf_proxy = instrument.get("instrument_type") == "etf_proxy"
    decimals = max(0, len(str(pip_size).split(".")[-1])) if "." in str(pip_size) else 2

    direction_emoji = "🟢" if signal.direction == "BUY" else "🔴"
    reasons = "\n".join(f"  • {r}" for r in signal.reasons)

    if is_etf_proxy:
        # Absolute ETF price levels don't map to the futures contract price on
        # Tradovate, so express SL/TP as % moves from entry — apply the same
        # % to whatever the live futures price is when you place the order.
        sl_pct = ((signal.stop_loss - signal.price) / signal.price) * 100
        tp_pcts = [((tp - signal.price) / signal.price) * 100 for tp in signal.take_profits]
        tp_lines = "\n".join(
            f"   TP{i+1}: {pct:+.2f}%" for i, pct in enumerate(tp_pcts)
        )
        return (
            f"{direction_emoji} *{signal.direction} — {display_name} ({tradovate_root})*\n"
            f"_{tradovate_exchange} — signal derived from ETF proxy ({instrument['symbol']}), "
            f"not live futures price_\n\n"
            f"Confluence: {signal.score}/{signal.max_score}\n"
            f"SL: {sl_pct:+.2f}%\n"
            f"{tp_lines}\n\n"
            f"⚠️ *Apply these % moves to the current {tradovate_root} futures price on "
            f"Tradovate at entry* — the ETF's dollar price doesn't correspond to the "
            f"futures contract price.\n\n"
            f"*Confluence factors:*\n{reasons}\n\n"
            f"_Onyx Commodities — signal, not financial advice_"
        )

    tp_lines = "\n".join(
        f"   TP{i+1}: {tp:.{decimals}f}" for i, tp in enumerate(signal.take_profits)
    )
    return (
        f"{direction_emoji} *{signal.direction} — {display_name} ({tradovate_root})*\n"
        f"_{tradovate_exchange} — confirm current front-month contract in Tradovate before entry_\n\n"
        f"Confluence: {signal.score}/{signal.max_score}\n"
        f"Entry: {signal.price:.{decimals}f}\n"
        f"SL: {signal.stop_loss:.{decimals}f}\n"
        f"{tp_lines}\n\n"
        f"*Confluence factors:*\n{reasons}\n\n"
        f"_Onyx Commodities — signal, not financial advice_"
    )


def send_signal(signal: Signal) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHANNEL_ID:
        logger.error("Telegram bot token / channel ID not configured — skipping send")
        return False

    url = _API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": config.TELEGRAM_CHANNEL_ID,
        "text": _format_message(signal),
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Failed to send Telegram message for %s", signal.instrument_key)
        return False


def _format_trade_update(event: dict) -> str:
    instrument = config.INSTRUMENTS[event["instrument_key"]]
    display_name = instrument["display_name"]
    tradovate_root = instrument.get("tradovate_root", "")
    is_etf_proxy = instrument.get("instrument_type") == "etf_proxy"
    pip_size = instrument["pip_size"]
    decimals = max(0, len(str(pip_size).split(".")[-1])) if "." in str(pip_size) else 2

    trade = event["trade"]
    kind = event["event"]
    price = event["price"]
    direction = trade["direction"]

    if kind == "SL_HIT":
        emoji, label = "🛑", "STOP LOSS HIT"
    else:
        emoji, label = "✅", f"{kind.replace('_HIT', '')} HIT"

    # Gain/loss in % terms, positive = favorable move regardless of direction
    if direction == "BUY":
        gain_pct = ((price - trade["entry"]) / trade["entry"]) * 100
    else:
        gain_pct = ((trade["entry"] - price) / trade["entry"]) * 100

    if is_etf_proxy:
        detail = f"Move: {gain_pct:+.2f}%"
    else:
        detail = f"Price: {price:.{decimals}f} ({gain_pct:+.2f}%)"

    return (
        f"{emoji} *{label} — {display_name} ({tradovate_root})*\n"
        f"{detail}\n"
        f"Original signal: {direction} @ {trade['entry']:.{decimals}f}\n\n"
        f"_Onyx Commodities — trade update_"
    )


def send_trade_update(event: dict) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHANNEL_ID:
        logger.error("Telegram bot token / channel ID not configured — skipping send")
        return False

    url = _API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": config.TELEGRAM_CHANNEL_ID,
        "text": _format_trade_update(event),
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Failed to send trade update for %s", event["instrument_key"])
        return False
