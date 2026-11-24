"""Read-only market scan: top movers with liquidity and spread filters.

Uses public endpoints only. No credentials are read and no orders are sent.

    python -m trader.scan --top 10 --min-turnover 1000000
"""

from __future__ import annotations

import argparse
import time
from decimal import Decimal

from .market_data import MarketDataClient, top_movers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--min-turnover", type=Decimal, default=Decimal("1000000"),
                    help="minimum 24h quote turnover in USDT")
    ap.add_argument("--max-spread", type=Decimal, default=Decimal("0.001"),
                    help="maximum (ask-bid)/mid, as a fraction")
    ap.add_argument("--max-age-ms", type=int, default=5000)
    args = ap.parse_args(argv)

    client = MarketDataClient()
    now_ms = int(time.time() * 1000)
    movers = top_movers(
        client.tickers(),
        now_ms=now_ms,
        n=args.top,
        min_turnover_usdt=args.min_turnover,
        max_spread_pct=args.max_spread,
        max_age_ms=args.max_age_ms,
    )
    print(f"{'symbol':<16}{'24h %':>9}{'turnover USDT':>16}{'spread %':>10}{'funding %':>11}{'last':>14}")
    for m in movers:
        print(
            f"{m.symbol:<16}{m.change_pct * 100:>9.2f}{m.turnover_usdt:>16.0f}"
            f"{m.spread_pct * 100:>10.4f}{m.funding_rate * 100:>11.4f}{m.last_price:>14}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
