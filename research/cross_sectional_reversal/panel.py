"""Build long panel with aligned return legs (same conventions as the research note)."""

from __future__ import annotations

import pandas as pd


def enrich_return_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (ticker, date) row (sorted by ticker, date):
    - r_oc: intraday C/O - 1
    - r_co: overnight into today's open O/C_{t-1} - 1
    - overnight_fwd: O_{t+1}/C_t - 1 (from this close to next open)
    - r_cc_5: 5d close-to-close signal C_t/C_{t-5} - 1
    - r_cc_fwd5: next 5d holding return C_{t+5}/C_t - 1
    """
    x = df.sort_values(["ticker", "date"]).copy()
    g = x.groupby("ticker", sort=False)
    prev_c = g["close"].shift(1)
    x["r_co"] = x["open"] / prev_c - 1.0
    x["r_oc"] = x["close"] / x["open"] - 1.0
    x["overnight_fwd"] = g["open"].shift(-1) / x["close"] - 1.0
    x["r_cc_5"] = x["close"] / g["close"].shift(5) - 1.0
    x["r_cc_fwd5"] = g["close"].shift(-5) / x["close"] - 1.0
    # Previous session's intraday return (for H1-style momentum / reversal tests)
    x["r_oc_lag1"] = g["r_oc"].shift(1)
    return x
