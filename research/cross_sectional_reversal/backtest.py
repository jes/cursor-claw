"""Equal-weight decile portfolios, costs, train/test split, summary stats."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def daily_decile_returns(
    df: pd.DataFrame,
    date_col: str,
    signal_col: str,
    ret_col: str,
    *,
    bottom_decile: bool = True,
    winsorized_signal_col: str | None = None,
    frac: float = 0.1,
    min_bucket: int = 5,
) -> pd.DataFrame:
    """
    Each calendar date: rank stocks by signal (ascending = losers first if bottom_decile),
    take bottom or top fraction of names (at least min_bucket, capped at n).
    """
    sig = winsorized_signal_col or signal_col
    rows = []
    for dt, g in df.groupby(date_col, sort=True):
        sub = g[[sig, ret_col]].dropna()
        n = len(sub)
        if n < 10:
            continue
        k = max(min_bucket, int(math.floor(n * frac)))
        k = min(k, n)
        if bottom_decile:
            thr = sub[sig].nsmallest(k).max()
            sel = sub[sub[sig] <= thr]
        else:
            thr = sub[sig].nlargest(k).min()
            sel = sub[sub[sig] >= thr]
        if sel.empty:
            continue
        ret = float(sel[ret_col].mean())
        rows.append({"date": dt, "portfolio_return": ret, "n_names": int(len(sel))})
    return pd.DataFrame(rows)


def non_overlapping_period_decile_returns(
    df: pd.DataFrame,
    date_col: str,
    signal_col: str,
    ret_col: str,
    *,
    period: int = 5,
    bottom_decile: bool = True,
    winsorized_signal_col: str | None = None,
    frac: float = 0.1,
    min_bucket: int = 5,
) -> pd.DataFrame:
    """
    Rebalance every `period` **trading** days (anchor: first calendar date in sample).
    On each rebalance day t, rank by signal (known at t), hold until t+period;
    portfolio return is the cross-sectional mean of ret_col (must be the period
    return aligned to t, e.g. close t→close t+period).
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    sig = winsorized_signal_col or signal_col
    dates = sorted(df[date_col].unique())
    rows = []
    for j in range(0, len(dates), period):
        t = dates[j]
        g = df[df[date_col] == t]
        sub = g[[sig, ret_col]].dropna()
        n = len(sub)
        if n < 10:
            continue
        k = max(min_bucket, int(math.floor(n * frac)))
        k = min(k, n)
        if bottom_decile:
            thr = sub[sig].nsmallest(k).max()
            sel = sub[sub[sig] <= thr]
        else:
            thr = sub[sig].nlargest(k).min()
            sel = sub[sub[sig] >= thr]
        if sel.empty:
            continue
        ret = float(sel[ret_col].mean())
        rows.append({"date": t, "portfolio_return": ret, "n_names": int(len(sel))})
    return pd.DataFrame(rows)


def apply_costs(daily: pd.DataFrame, roundtrip_bps: float) -> pd.DataFrame:
    out = daily.copy()
    adj = roundtrip_bps / 10000.0
    out["portfolio_return_net"] = out["portfolio_return"] - adj
    return out


def summarize_returns(
    daily: pd.Series,
    *,
    observations_per_year: float = 252.0,
) -> dict:
    """
    `observations_per_year`: 252 for one row per trading day; 252/5 for
    non-overlapping 5-trading-day periods, etc.
    """
    x = daily.dropna().values
    n = len(x)
    if n == 0:
        return {"n_days": 0}
    mean_d = float(np.mean(x))
    std_d = float(np.std(x, ddof=1)) if n > 1 else float("nan")
    sharpe = (
        (mean_d / std_d * math.sqrt(observations_per_year)) if std_d and std_d > 0 else float("nan")
    )
    cum = float(np.prod(1.0 + x) - 1.0)
    years = n / observations_per_year
    cagr = ((1.0 + cum) ** (1.0 / years) - 1.0) if years > 0 and (1.0 + cum) > 0 else float("nan")
    t_stat = (mean_d / (std_d / math.sqrt(n))) if std_d and std_d > 0 else float("nan")
    return {
        "n_days": n,
        "mean_daily": mean_d,
        "std_daily": std_d,
        "sharpe_like": sharpe,
        "total_return": cum,
        "cagr": cagr,
        "t_mean_daily": t_stat,
        "observations_per_year": observations_per_year,
    }


def train_test_split_by_date(
    daily: pd.DataFrame, train_frac: float = 0.6
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = daily.sort_values("date")
    cut = int(len(daily) * train_frac)
    train = daily.iloc[:cut]
    test = daily.iloc[cut:]
    return train, test


def spearman_by_date(
    df: pd.DataFrame,
    date_col: str,
    a: str,
    b: str,
    dates_filter: set | None = None,
) -> float:
    """Mean cross-sectional Spearman correlation by day (simple average of daily rhos)."""
    rhos = []
    for dt, g in df.groupby(date_col, sort=False):
        if dates_filter is not None and dt not in dates_filter:
            continue
        sub = g[[a, b]].dropna()
        if len(sub) < 10:
            continue
        rho = sub[a].corr(sub[b], method="spearman")
        if rho == rho:  # not NaN
            rhos.append(float(rho))
    return float(np.mean(rhos)) if rhos else float("nan")


def audit_extreme_days(
    daily: pd.DataFrame, top_k: int = 5
) -> pd.DataFrame:
    """Largest gross daily portfolio returns (for manual sanity check)."""
    if daily.empty:
        return daily
    return daily.nlargest(top_k, "portfolio_return")[
        ["date", "portfolio_return", "n_names"]
    ].reset_index(drop=True)
