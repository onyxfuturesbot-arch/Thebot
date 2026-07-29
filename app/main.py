"""
Onyx Commodities — entrypoint.

FastAPI app for health checks + a background loop that scans all
instruments on an interval and pushes any confluence signals to Telegram.
Deploy pattern matches AURUM/TITAN on Railway: one process, one Procfile.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from app import config, signal_engine, telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("onyx.main")

_last_scan_at: datetime | None = None
_last_signals_count: int = 0
_last_trade_updates_count: int = 0
_scan_errors: int = 0


async def _scan_loop():
    global _last_scan_at, _last_signals_count, _last_trade_updates_count, _scan_errors
    while True:
        try:
            # Check open trades for SL/TP hits BEFORE looking for new signals,
            # so a closed trade frees its instrument up the same cycle.
            events = signal_engine.monitor_active_trades()
            _last_trade_updates_count = len(events)
            for event in events:
                sent = telegram_bot.send_trade_update(event)
                logger.info(
                    "%s %s @ %.4f -> telegram sent=%s",
                    event["instrument_key"], event["event"], event["price"], sent,
                )

            signals = signal_engine.scan_all()
            _last_scan_at = datetime.now(timezone.utc)
            _last_signals_count = len(signals)

            for sig in signals:
                sent = telegram_bot.send_signal(sig)
                logger.info(
                    "%s %s %s/%s -> telegram sent=%s",
                    sig.instrument_key, sig.direction, sig.score, sig.max_score, sent,
                )
        except Exception:
            _scan_errors += 1
            logger.exception("Scan loop error")

        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_scan_loop())
    logger.info("Onyx Commodities scan loop started (interval=%ss)", config.POLL_INTERVAL_SECONDS)
    yield
    task.cancel()


app = FastAPI(title="Onyx Commodities", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "Onyx Commodities", "status": "running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "last_scan_at": _last_scan_at.isoformat() if _last_scan_at else None,
        "last_signals_count": _last_signals_count,
        "last_trade_updates_count": _last_trade_updates_count,
        "scan_errors": _scan_errors,
        "instruments": list(config.INSTRUMENTS.keys()),
        "active_trades": list(signal_engine._active_trades.keys()),
    }


@app.post("/scan-now")
def scan_now():
    """Manual trigger — useful for testing without waiting on the poll interval."""
    events = signal_engine.monitor_active_trades()
    for event in events:
        telegram_bot.send_trade_update(event)

    signals = signal_engine.scan_all()
    for sig in signals:
        telegram_bot.send_signal(sig)

    return {
        "trade_updates": len(events),
        "signals_found": len(signals),
        "signals": [
            {
                "instrument": s.instrument_key,
                "tradovate_root": config.INSTRUMENTS[s.instrument_key].get("tradovate_root"),
                "direction": s.direction,
                "score": f"{s.score}/{s.max_score}",
                "price": s.price,
            }
            for s in signals
        ],
    }


@app.post("/trade-result/{instrument_key}")
def report_trade_result(instrument_key: str, was_loss: bool):
    """
    Feed live trade outcomes back in, same feedback-loop pattern as AURUM,
    so the consecutive-loss circuit breaker actually has data to work with.
    """
    if instrument_key not in config.INSTRUMENTS:
        return {"error": f"unknown instrument {instrument_key}"}
    signal_engine.record_trade_result(instrument_key, was_loss)
    return {"instrument": instrument_key, "recorded_loss": was_loss}
