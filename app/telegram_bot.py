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
    display_name = config.INSTRUMENTS[signal.instrument_key]["display_name"]
    pip_size = config.INSTRUMENTS[signal.instrument_key]["pip_size"]
    decimals = max(0, len(str(pip_size).split(".")[-1])) if "." in str(pip_size) else 2

    direction_emoji = "🟢" if signal.direction == "BUY" else "🔴"
    tp_lines = "\n".join(
        f"   TP{i+1}: {tp:.{decimals}f}" for i, tp in enumerate(signal.take_profits)
    )
    reasons = "\n".join(f"  • {r}" for r in signal.reasons)

    return (
        f"{direction_emoji} *{signal.direction} — {display_name}*\n\n"
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
