"""Fetch daily OHLC from Yahoo Finance chart API (v8) using stdlib + pandas.

Prices are made consistent with adjusted close: open is rescaled by adjclose/close
per bar so intraday and overnight legs align with split- and dividend-adjusted
close (avoids bogus legs on split days).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import pandas as pd

USER_AGENT = "Mozilla/5.0 (compatible; cross-sectional-reversal-research/1.0)"


def _fetch_chart_json(symbol: str, period1: int, period2: int) -> Optional[dict]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/%s"
        "?period1=%d&period2=%d&interval=1d&events=div,splits"
        % (urllib.parse.quote(symbol, safe="."), period1, period2)
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5 * (attempt + 1))
    return None


def chart_to_ohlc_frame(symbol: str, data: dict) -> pd.DataFrame:
    """Return DataFrame date, open, close, volume for one symbol."""
    try:
        res = data["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return pd.DataFrame(columns=["date", "ticker", "open", "close", "volume"])

    ts = res.get("timestamp") or []
    if not ts:
        return pd.DataFrame(columns=["date", "ticker", "open", "close", "volume"])

    q = (res.get("indicators") or {}).get("quote") or [{}]
    q = q[0] if q else {}
    adj_block = (res.get("indicators") or {}).get("adjclose") or [{}]
    adj = (adj_block[0] or {}).get("adjclose") if adj_block else None
    if not adj or len(adj) != len(ts):
        return pd.DataFrame(columns=["date", "ticker", "open", "close", "volume"])

    opens = q.get("open") or []
    closes = q.get("close") or []
    vols = q.get("volume") or []

    rows = []
    for i, t in enumerate(ts):
        o = opens[i] if i < len(opens) else None
        c = closes[i] if i < len(closes) else None
        ac = adj[i] if i < len(adj) else None
        v = vols[i] if i < len(vols) else 0
        if o is None or c is None or ac is None:
            continue
        try:
            o, c, ac = float(o), float(c), float(ac)
        except (TypeError, ValueError):
            continue
        if c <= 0 or ac <= 0:
            continue
        o_adj = o * (ac / c)
        rows.append(
            {
                "date": pd.Timestamp(t, unit="s", tz="UTC").tz_convert(None).normalize(),
                "ticker": symbol,
                "open": o_adj,
                "close": ac,
                "volume": int(v) if v is not None else 0,
            }
        )
    return pd.DataFrame(rows)


def download_symbol(
    symbol: str, period1: int, period2: int, sleep_s: float = 0.12
) -> pd.DataFrame:
    time.sleep(sleep_s)
    raw = _fetch_chart_json(symbol, period1, period2)
    if not raw:
        return pd.DataFrame(columns=["date", "ticker", "open", "close", "volume"])
    err = raw.get("chart", {}).get("error")
    if err:
        return pd.DataFrame(columns=["date", "ticker", "open", "close", "volume"])
    return chart_to_ohlc_frame(symbol, raw)
