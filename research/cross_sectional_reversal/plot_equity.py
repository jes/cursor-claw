"""Plot cumulative equity curves from long-format backtest output."""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

# Short labels for crowded legends
_STRATEGY_LABELS = {
    "H1_prev_intraday_winners_next_intraday": "H1 prev win → next intraday",
    "H1_prev_intraday_losers_next_intraday": "H1 prev lose → next intraday",
    "H2_intraday_losers_next_overnight": "H2 intra lose → overnight",
    "H3_overnight_losers_next_intraday": "H3 ov lose → intraday",
    "H3_overnight_winners_next_intraday": "H3 ov win → intraday",
    "H4_five_day_losers_next_five_days": "H4 5d lose → next 5d (non-overlap)",
}


def plot_strategy_equity(
    daily_long: pd.DataFrame,
    out_path: str,
    *,
    train_frac: float = 0.6,
    title: str = "",
    dpi: int = 120,
) -> str:
    """
    daily_long: columns date, portfolio_return_net, strategy.
    Sparse strategies (e.g. H4 every 5th day) are forward-filled on the union
    of all dates so curves share a time axis (flat between rebalances).
    """
    if daily_long.empty:
        raise ValueError("daily_long is empty; nothing to plot")

    daily_long = daily_long.copy()
    daily_long["date"] = pd.to_datetime(daily_long["date"])
    all_dates = sorted(daily_long["date"].unique())
    aidx = pd.DatetimeIndex(all_dates)

    fig, ax = plt.subplots(figsize=(12, 7), dpi=dpi)
    if len(all_dates):
        cut_i = int(len(all_dates) * train_frac)
        cut_i = max(0, min(cut_i, len(all_dates) - 1))
        cut_date = all_dates[cut_i]
        ax.axvline(
            cut_date,
            color="0.35",
            linestyle="--",
            linewidth=1,
            alpha=0.85,
            label="train / test split",
        )

    cmap = plt.cm.tab10
    for i, (strat, g) in enumerate(daily_long.groupby("strategy", sort=False)):
        g = g.sort_values("date")
        if g.empty:
            continue
        col = "portfolio_return_net" if "portfolio_return_net" in g.columns else "portfolio_return"
        idx = pd.DatetimeIndex(g["date"])
        ser = pd.Series((1.0 + g[col].astype(float)).cumprod().values, index=idx)
        fv = ser.first_valid_index()
        if fv is None:
            continue
        full = ser.reindex(aidx)
        full.loc[full.index < fv] = 1.0
        full = full.ffill()
        label = _STRATEGY_LABELS.get(strat, strat[:28])
        ax.plot(full.index, full.values, label=label, color=cmap(i % 10), linewidth=1.4)

    ax.set_ylabel("Growth of $1 (net of cost haircut)")
    ax.set_xlabel("Date")
    sub = (
        "H4: non-overlapping 5d rebalances (flat between); others daily rebalance."
    )
    ax.set_title((title + "\n" + sub) if title else "Cross-sectional strategies\n" + sub)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    try:
        ax.set_yscale("log")
    except Exception:
        ax.set_yscale("linear")

    fig.tight_layout()
    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
    fig.savefig(out_abs, bbox_inches="tight")
    plt.close(fig)
    return out_abs
