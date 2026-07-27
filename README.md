# Onyx Commodities

Telegram signal bot for commodity futures (gold, WTI, copper, corn, coffee to start),
built on the same architecture as AURUM / TITAN / CIPHER: FastAPI on Railway,
Twelve Data for market data, local indicator calculation, Telegram for delivery.

Signals only — no auto-execution. Confluence-score based, same family of
logic as AURUM's stack but starting looser (5/7) since this edge is unvalidated.

## How it works

1. Every `POLL_INTERVAL_SECONDS` (default 300s), the scan loop pulls raw OHLC
   for each instrument from Twelve Data — **one call per timeframe per
   instrument**, nothing more. All indicators (EMA, RSI, MACD, Bollinger,
   ATR) are computed locally in `indicators.py`. This is the same fix TITAN
   needed after burning through API credits on per-indicator calls.
2. `signal_engine.py` scores each instrument against 7 independent bullish
   and bearish checks (trend, HTF trend, RSI, MACD cross, MACD momentum,
   BB position, EMA slope). A signal fires at 5/7 or better.
3. Session filters skip ags outside CBOT liquidity hours, and skip
   metals/energy outside the London/US window.
4. A per-instrument consecutive-loss circuit breaker pauses trading for 12h
   after 3 losses in a row — feed results in via `POST /trade-result/{key}`.
5. Signals that pass get formatted and pushed to your Telegram channel.

## Instruments (config.py)

| Key | Twelve Data symbol | Tradovate root | Exchange | Category |
|---|---|---|---|---|
| GOLD | XAU/USD | GC | COMEX | metals |
| WTI | WTI/USD | CL | NYMEX | energy |
| COPPER | XCU/USD | HG | COMEX | metals |
| CORN | C_1 | ZC | CBOT | ags |
| COFFEE | KC1 | KC | ICE | ags |

**Signals are built for Tradovate execution.** Each Telegram message shows the
root symbol (e.g. `GC`) and exchange, not a specific contract month. Tradovate
requires the exact contract ticker (root + month code + year digit, e.g.
`GCZ5` for December 2025 Gold) to place an order, and each product has its
own listed contract months and its own volume-based rollover timing — this
isn't reliably computable from OHLC data alone, so the bot deliberately
doesn't guess it. **Always confirm the current front-month contract in
Tradovate before entering** — this is standard practice regardless of where
a signal comes from.

**Before going live, verify each symbol against your Twelve Data plan** —
run `GET https://api.twelvedata.com/commodities?apikey=YOUR_KEY` and confirm
the exact symbol strings your plan tier returns; continuous futures symbols
(`C_1`, `KC1`) sometimes differ by plan/exchange mapping. Swap any that don't
match in `app/config.py::INSTRUMENTS`.

## Local setup

```bash
cp .env.example .env
# fill in TWELVE_DATA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then hit `POST http://localhost:8000/scan-now` to trigger an immediate scan
without waiting on the poll interval — good for checking your Telegram
formatting and confluence output before deploying.

## Deploy to Railway

1. Push this repo to GitHub.
2. New Railway project → deploy from repo.
3. Set environment variables in Railway's dashboard (same three as `.env.example`).
4. Railway auto-detects the `Procfile` and runs `uvicorn app.main:app`.
5. Check `GET /health` on your Railway URL to confirm the scan loop is alive.

## Tuning before you trust this with real money

This is a scaffold with sensible defaults, not a validated edge — same
starting point AURUM was at before you iterated on live data. Before
treating signals as tradeable:

- **Backtest first.** Pull historical Twelve Data candles and run
  `signal_engine`'s scoring logic offline against them to see hit rate
  per instrument before it ever touches Telegram live.
- **Watch the rollover gap.** Continuous futures symbols (`C_1`, `KC1`)
  jump on contract roll. Consider skipping signals within ~2 days of
  known roll dates, or switch those two instruments to % returns instead
  of raw price for the EMA/BB math if gaps cause false signals.
- **Confluence threshold (5/7) is a starting guess.** Move it in
  `config.CONFLUENCE_THRESHOLD` once you have live/backtest win-rate data —
  exactly how AURUM went from a looser filter to a strict 9/9 stack.
- **Session windows are rough defaults** — tighten based on which hours
  actually produce clean signals for each instrument.

## Feedback loop

`POST /trade-result/{instrument_key}?was_loss=true|false` after each signalled
trade closes. This feeds the consecutive-loss pause and is also the natural
hook point if you later want to log outcomes for weekly retraining, same as
the AURUM EA's feedback loop.
