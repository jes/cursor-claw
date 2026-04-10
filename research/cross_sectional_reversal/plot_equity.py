"""Plot cumulative equity curves from long-format daily backtest output."""

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
    "H4_five_day_losers_next_five_days": "H4 5d lose → next 5d",
}


# H4 uses same-day assignment of a 5-day-forward return; compounding those daily
# implies overlapping holds and is not a tradable equity curve — omit from chart.
_EXCLUDE_FROM_CHART = frozenset({"H4_five_day_losers_next_five_days"})


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
    Saves PNG to out_path. Returns absolute path.
    """
    if daily_long.empty:
        raise ValueError("daily_long is empty; nothing to plot")

    daily_long = daily_long.copy()
    daily_long["date"] = pd.to_datetime(daily_long["date"])
    daily_long = daily_long[~daily_long["strategy"].isin(_EXCLUDE_FROM_CHART)]
    if daily_long.empty:
        raise ValueError("No strategies left to plot after exclusions")

    fig, ax = plt.subplots(figsize=(12, 7), dpi=dpi)
    uniq_dates = sorted(daily_long["date"].unique())
    if uniq_dates:
        cut_i = int(len(uniq_dates) * train_frac)
        cut_i = max(0, min(cut_i, len(uniq_dates) - 1))
        cut_date = uniq_dates[cut_i]
        ax.axvline(
            cut_date,
            color="0.35",
            linestyle="--",
            linewidth=1,
            alpha=0.85,
            label="train / test split",
        )

    cmap = plt.cm.tab10
    for i, (strat, g) in enumerate(
        daily_long.groupby("strategy", sort=False)
    ):
        g = g.sort_values("date")
        if g.empty:
            continue
        col = "portfolio_return_net" if "portfolio_return_net" in g.columns else "portfolio_return"
        eq = (1.0 + g[col].astype(float)).cumprod()
        label = _STRATEGY_LABELS.get(strat, strat[:28])
        ax.plot(g["date"], eq, label=label, color=cmap(i % 10), linewidth=1.4)

    ax.set_ylabel("Growth of $1 (net of cost haircut)")
    ax.set_xlabel("Date")
    sub = "H4 (5d→5d) omitted — overlapping horizon, not daily-compoundable."
    ax.set_title(
        (title + "\n" + sub) if title else "Cross-sectional strategies\n" + sub
    )
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    # Log scale when curves stay positive (usual case)
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
