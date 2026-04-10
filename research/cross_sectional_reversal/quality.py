"""Per-ticker data quality: continuity bounds, minimum history, optional price floor."""

from __future__ import annotations

import pandas as pd


def compute_legs(df: pd.DataFrame) -> pd.DataFrame:
    """Single ticker, sorted by date. Adds r_co and r_oc."""
    x = df.sort_values("date").copy()
    prev_c = x["close"].shift(1)
    x["r_co"] = x["open"] / prev_c - 1.0
    x["r_oc"] = x["close"] / x["open"] - 1.0
    return x


def ticker_passes_filters(
    df: pd.DataFrame,
    leg_low: float,
    leg_high: float,
    min_trading_days: int,
    min_avg_close: float | None = None,
) -> bool:
    """
    Reject ticker if any overnight or intraday leg is outside [leg_low, leg_high],
    or history too short, or average close too low.
    """
    if df is None or len(df) < min_trading_days:
        return False
    x = compute_legs(df)
    legs = pd.concat([x["r_co"].dropna(), x["r_oc"].dropna()])
    if legs.empty:
        return False
    if ((x["r_co"] < leg_low) | (x["r_co"] > leg_high)).any():
        return False
    if ((x["r_oc"] < leg_low) | (x["r_oc"] > leg_high)).any():
        return False
    if min_avg_close is not None and min_avg_close > 0:
        if x["close"].mean() < min_avg_close:
            return False
    return True


def filter_panel(
    long_df: pd.DataFrame,
    leg_low: float = -0.5,
    leg_high: float = 2.0,
    min_trading_days: int = 252,
    min_avg_close: float | None = 5.0,
) -> pd.DataFrame:
    """Drop tickers that fail continuity / coverage tests."""
    good = []
    for t, g in long_df.groupby("ticker", sort=False):
        if ticker_passes_filters(
            g, leg_low, leg_high, min_trading_days, min_avg_close
        ):
            good.append(t)
    if not good:
        return long_df.iloc[0:0].copy()
    return long_df[long_df["ticker"].isin(good)].copy()


def winsorize_cross_section(
    df: pd.DataFrame, date_col: str, signal_col: str, lower_q: float, upper_q: float
) -> pd.Series:
    """Per-date winsorize signal to reduce influence of bad prints."""

    def _clip(s: pd.Series) -> pd.Series:
        lo, hi = s.quantile(lower_q), s.quantile(upper_q)
        return s.clip(lo, hi)

    return df.groupby(date_col, sort=False)[signal_col].transform(_clip)
