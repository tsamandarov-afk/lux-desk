#!/usr/bin/env python3
"""Lux Desk: бэктест 2022→сегодня и виртуальный счёт $10 000 по связке LuxAlgo (4 стратегии × 2ч+4ч × 7 монет).
Движок и индикаторы — из ~/Documents/strategies/luxalgo (RULES.md). Запускать python из .venv той папки.
Пишет backtest.json (все сделки для расчёта на сайте под любой депозит) и feed.json (живой демо-счёт)."""
import json, subprocess, sys, urllib.request, warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
warnings.filterwarnings("ignore")
HOME = Path.home() / "Documents/strategies"
sys.path[:0] = [str(HOME / "luxalgo"), str(HOME / "lab")]
import numpy as np, pandas as pd
import sim, portfolio, inds, inds2, inds3, inds4, inds5, inds6  # noqa: F401

HERE = Path(__file__).parent
COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "NEAR"]
SYMS = [c + "USDT" for c in COINS]
KEYS = portfolio.KEYS                      # cusum, fvg_pos_avg_ema200, sr_breaks, stat_trailing
TFS = ["4h", "2h"]
RISK, DEPOSIT = 0.0025, 10000.0
LIVE_START = pd.Timestamp("2026-10-01 19:00")   # старт виртуального счёта (UTC)
sim.START = "2021-06-01"
sim.END = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")


def topup(sym):
    """Дозагрузка закрытых часовых свечей через API (дампы отстают до суток) — в кэш симулятора."""
    df = sim.load(sym, "1h")
    last = df.time.iloc[-1]
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    t = int(last.timestamp() * 1000) + 3600_000
    rows = []
    while True:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1h&startTime={t}&limit=1000"
        raw = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lux"}), timeout=30))
        rows += [x for x in raw if x[6] < now_ms]
        if len(raw) < 1000:
            break
        t = raw[-1][0] + 3600_000
    if rows:
        add = pd.DataFrame(dict(time=pd.to_datetime([x[0] for x in rows], unit="ms", utc=True), open=[float(x[1]) for x in rows],
                                high=[float(x[2]) for x in rows], low=[float(x[3]) for x in rows],
                                close=[float(x[4]) for x in rows], volume=[float(x[5]) for x in rows]))
        add["time"] = add.time.astype(df.time.dtype)
        new = pd.concat([df, add], ignore_index=True)
        new.attrs.update(df.attrs)
        sim._cache[(sym, "1h")] = new
    return sim._cache[(sym, "1h")]


def ts(x):
    return int(pd.Timestamp(x).tz_localize("UTC").timestamp()) if pd.Timestamp(x).tzinfo is None else int(pd.Timestamp(x).timestamp())


def main():
    base = {s: topup(s) for s in SYMS}
    last_px = {s: float(base[s].close.iloc[-1]) for s in SYMS}
    last_t = base[SYMS[0]].time.iloc[-1]
    gen = datetime.now(timezone.utc).isoformat()

    # ---------- бэктест с 2022-01-01 ----------
    a = portfolio.trades(TFS, "2022-01-01", syms=SYMS)
    a["coin"] = a.sym.str.replace("USDT", "").map({c: i for i, c in enumerate(COINS)})
    a["strat"] = a.key.map({k: i for i, k in enumerate(KEYS)}); a["tfi"] = a.tf.map({"2h": 0, "4h": 1})
    ropen = np.array([((last_px[s] - e) * d / r) if o else 0.0 for s, e, d, r, o in zip(a.sym, a.entry, a.dir, a.risk, a.open_end)])
    tr = [[ts(r.t_in), ts(r.t_out), int(r.coin), int(r.strat), int(r.tfi), int(r.dir), round(float(r.Rnet), 3), int(r.open_end), round(float(ro), 3)]
          for r, ro in zip(a.itertuples(), ropen)]
    bt = dict(generated=gen, coins=COINS, strategies=KEYS, tfs=["2h", "4h"], t0=ts("2022-01-01"), t_last=int(last_t.timestamp()), trades=tr)
    (HERE / "backtest.json").write_text(json.dumps(bt, separators=(",", ":")))
    r = portfolio.account(a, RISK, DEPOSIT)
    rr = a.Rnet[~a.open_end]
    print(f"backtest: {len(a)} trades, closed {len(rr)}, PF {rr[rr>0].sum()/-rr[rr<0].sum():.2f}, closed bal {r['closed']:,.0f}, with open {r['with_open']:,.0f}, dd {r['dd']*100:.1f}%")

    # ---------- спектрограмма: чистое направление по монете на последних 4ч свечах ----------
    bars4 = pd.date_range(end=last_t.tz_localize(None).floor("4h"), periods=60, freq="4h")
    tin, tout, dr, cs = a.t_in.values, a.t_out.values, a.dir.values, a.coin.values
    spec = {c: [int(dr[(cs == i) & (tin <= np.datetime64(b)) & (tout > np.datetime64(b))].sum()) for b in bars4] for i, c in enumerate(COINS)}

    # ---------- живой виртуальный счёт ----------
    live = portfolio.trades(TFS, LIVE_START, syms=SYMS)
    live = live[live.t_in >= LIVE_START].reset_index(drop=True)
    grid = pd.date_range(LIVE_START, last_t.tz_localize(None), freq="1h")
    P = {s: pd.Series(base[s].close.values, index=base[s].time.dt.tz_localize(None).values).reindex(grid).ffill() for s in SYMS}
    ev = sorted([(t, 0 if not (ti == t) else 2, i) for i, (t, ti) in enumerate(zip(live.t_out, live.t_in)) if not live.open_end[i]]
                + [(t, 1, i) for i, t in enumerate(live.t_in)])
    bal, size, closed = DEPOSIT, {}, []
    for t, typ, i in ev:
        if typ == 1:
            size[i] = RISK * bal
        else:
            pnl = size.pop(i) * live.Rnet[i]; bal += pnl
            x = live.loc[i]; closed.append(dict(t=ts(x.t_out), coin=x.sym[:-4], strat=x.key, tf=x.tf, dir=int(x.dir), R=round(float(x.Rnet), 2), pnl=round(float(pnl), 2)))
    curve, opens = [], []
    for h in grid:
        b = DEPOSIT
        # баланс на момент h по закрытым + плавающая прибыль открытых
        b = DEPOSIT + sum(c["pnl"] for c in closed if c["t"] <= ts(h))
        fl = sum(size[i] * ((P[live.sym[i]][h] - live.entry[i]) * live.dir[i] / live.risk[i]) for i in size if live.t_in[i] <= h)
        curve.append([ts(h), round(b + fl, 2)])
    for i, s in size.items():
        x = live.loc[i]; px = last_px[x.sym]; R = (px - x.entry) * x.dir / x.risk
        opens.append(dict(coin=x.sym[:-4], strat=x.key, tf=x.tf, dir=int(x.dir), entry=float(x.entry), risk=float(x.risk), t=ts(x.t_in), size=round(float(s), 2), R=round(float(R), 2), pnl=round(float(s * R), 2)))
    # текущие позиции по всем 56 парам (для живого состояния монет) — из полного бэктеста
    cur = a[a.open_end]
    state = [dict(coin=COINS[int(x.coin)], strat=int(x.strat), tf=x.tf, dir=int(x.dir), entry=float(x.entry), risk=float(x.risk), t=ts(x.t_in)) for x in cur.itertuples()]
    unreal = sum(o["pnl"] for o in opens)
    feed = dict(generated=gen, start=ts(LIVE_START), deposit=DEPOSIT, risk=RISK, balance=round(bal, 2), equity=round(bal + unreal, 2),
                closed=len(closed), wins=sum(c["pnl"] > 0 for c in closed), open=len(opens), curve=curve[-800:], opens=opens, log=closed[-40:][::-1],
                state=state, spec=spec, spec_t=int(bars4[-1].tz_localize("UTC").timestamp()), last_t=int(last_t.timestamp()), prices={s[:-4]: last_px[s] for s in SYMS})
    (HERE / "feed.json").write_text(json.dumps(feed, separators=(",", ":")))
    print(f"live: balance {bal:,.2f} equity {bal+unreal:,.2f} closed {len(closed)} open {len(opens)} state {len(state)}")
    if "--push" in sys.argv:
        g = lambda *x: subprocess.run(["git", "-C", str(HERE), *x], capture_output=True, text=True)
        g("add", "feed.json", "backtest.json")
        if "nothing to commit" not in g("commit", "-m", f"data {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC").stdout:
            g("push", "-q", "origin", "HEAD")


main()
