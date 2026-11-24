# MEXC futures trading engine

Paper trading is the default. Live order submission exists in code but is gated, and this repository has never placed a live order.

## Setup

```bash
python3 -m venv /opt/mexc-trader/venv
/opt/mexc-trader/venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in locally; .env is git-ignored
```

## Commands

```bash
# Tests (no network, no credentials needed)
/opt/mexc-trader/venv/bin/python -m pytest -q

# Read-only market scan of the top movers (public endpoints only)
/opt/mexc-trader/venv/bin/python -m trader.scan --top 10 --min-turnover 1000000

# Engage the emergency kill switch (blocks all new entries; remove the file to re-arm)
mkdir -p /opt/mexc-trader/state && date -u > /opt/mexc-trader/state/KILL_SWITCH
```

## Configuration

| Variable | Meaning |
|---|---|
| `MEXC_API_KEY`, `MEXC_API_SECRET` | Required for private endpoints only. Loaded at runtime; never logged. |
| `TRADING_MODE` | `paper` (default) or `live`. |
| `LIVE_TRADING` | Must be `true` together with `TRADING_MODE=live`. |
| `LIVE_AUTHORIZED_UNTIL` | Operator authorization, ISO-8601 with timezone. Must be in the future. |
| `KEY_CREATED_AT` | When the API key was created, ISO-8601 with timezone. Keys last 90 days unless bound to an IP. |

Risk limits have no defaults. The operator must set `max_leverage`, `max_risk_per_trade_pct`, `max_daily_loss_pct`, `max_notional_per_position`, `max_open_positions`, `max_data_age_ms`, and `max_spread_pct` when constructing `RiskLimits`.

## Architecture

| Module | Responsibility |
|---|---|
| `trader/signing.py` | HMAC-SHA256 request signing for futures private endpoints |
| `trader/contracts.py` | Contract specs, quantity/price/leverage validation, Decimal math |
| `trader/market_data.py` | Public contract/ticker fetch with retry and backoff; top-mover ranking; staleness |
| `trader/indicators.py` | EMA, RSI, ATR, MACD, ADX on closed candles |
| `trader/signals.py` | Long/short evaluation: ADX trend gate plus 2-of-3 votes |
| `trader/risk.py` | Explicit limits, position sizing, entry checks, file-backed kill switch |
| `trader/execution.py` | `PaperBroker` (simulated fills, stops, liquidation) and `LiveOrderClient` (signed POST, duplicate guard) |
| `trader/live_gate.py` | Lists every failed live-trading precondition; empty list means enabled |
| `trader/scan.py` | Read-only CLI scanner |

## Tests

91 tests cover signing (including the RFC 4231 HMAC vector), contract validation, indicators, risk and sizing, the paper broker, the live client against a mock transport (headers, signed body, duplicate and timeout protection), connection recovery with backoff, and top-mover filtering.

## Not implemented or not verified

- **Candlestick endpoint**: the path has not been verified, so the engine cannot yet fetch closed candles.
- **Leverage setting endpoint**: not found in the docs read so far.
- **WebSocket streaming**: the URL is `wss://contract.mexc.com/edge`, but the ping/subscription format is unverified. Market data is polled over REST.
- **Account balance sync and position reconciliation after restart**: these need private read endpoints that have not been verified or implemented. Paper positions are in-memory only.
- **Trailing stops**: not implemented.
- **Live signing against the exchange**: signing follows the documented scheme. It has been tested locally, but not against a real private endpoint, because no credentials were used.
- **Live order submission**: the code path exists and is tested with mocks. Nothing here runs it automatically, and no entry point connects it to the gate.
- **Signal validity**: the rules are a starting point with no backtest or profitability evidence.

## Known sizing constraint

The smallest BTC_USDT order is 1 contract = 0.0001 BTC, about $6 of notional at ~$60,000. With $2 equity and a 1% per-trade risk limit, the sizer returns 0 contracts for any normal stop. Trades only become possible with very tight stops (roughly under 0.3% of price), which fees and spreads often consume. Small accounts need a different instrument, a larger account, or a relaxed risk limit, and relaxing the risk limit is the operator's decision.
