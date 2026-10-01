# Lux Desk

Demo dashboard: four open LuxAlgo-style strategies (CUSUM, FVG positioning + EMA 200, S/R with breaks, statistical trailing stop)
on 2h + 4h candles, seven Binance coins (BTC ETH SOL AVAX LINK DOGE NEAR).

- Virtual account: $10,000 from 2026-10-01 19:00 UTC, risk 0.25 % of realised balance per entry, paper only.
- Backtest 2022-01-01 → today with a deposit/risk calculator (compounding computed in the browser).
- `build.py` rebuilds `feed.json` and `backtest.json` (needs the local research engine), `index.html` is the site.

Not financial advice. Results come from rare big trends; drawdowns of 40-55 % occur every year.
