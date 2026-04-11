#!/usr/bin/env python3
"""
Reproduce cross-sectional reversal methodology with cleaner data handling:

- Yahoo chart v8 OHLC; open rescaled to match adj. close (split/dividend consistent).
- Blacklist tickers with any overnight or intraday leg outside [leg_low, leg_high].
- Minimum history (trading days) and optional minimum average close (penny filter).
- Optional per-day cross-sectional winsorization of the signal.
- Round-trip cost haircut in bps; train/test split by calendar time.

Does NOT remove S&P 500 survivorship bias (current constituents) — that limitation
is printed explicitly. Use --symbols-file for a frozen list if you have one.

Examples:
  python3 run_study.py --universe sp500 --start 2013-02-08 --end 2018-02-07 --max-tickers 80
  python3 run_study.py --universe ftse100 --start 2018-01-01 --end 2024-12-01
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, ".cache")

from backtest import (  # noqa: E402
    apply_costs,
    audit_extreme_days,
    daily_decile_returns,
    non_overlapping_period_decile_returns,
    spearman_by_date,
    summarize_returns,
    train_test_split_by_date,
)
from panel import enrich_return_columns  # noqa: E402
from quality import filter_panel, winsorize_cross_section  # noqa: E402
from universe import ftse100_yahoo_symbols, sp500_yahoo_symbols  # noqa: E402
from yahoo_v8 import download_symbol  # noqa: E402

STRATEGIES = [
    ("H1_prev_intraday_winners_next_intraday", "r_oc_lag1", "r_oc", False),
    ("H1_prev_intraday_losers_next_intraday", "r_oc_lag1", "r_oc", True),
    ("H2_intraday_losers_next_overnight", "r_oc", "overnight_fwd", True),
    ("H3_overnight_losers_next_intraday", "r_co", "r_oc", True),
    ("H3_overnight_winners_next_intraday", "r_co", "r_oc", False),
    ("H4_five_day_losers_next_five_days", "r_cc_5", "r_cc_fwd5", True),
]


def _parse_date(s: str) -> pd.Timestamp:
    return pd.Timestamp(s).normalize()


def _period_unix(d: pd.Timestamp) -> int:
    return int(d.timestamp())


def _cache_path(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> str:
    h = hashlib.sha256()
    h.update(("%s|%s|" % (start.date(), end.date())).encode())
    for s in sorted(symbols):
        h.update(s.encode())
        h.update(b"\n")
    return os.path.join(CACHE_DIR, "panel_%s.parquet" % h.hexdigest()[:24])


def load_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols_file:
        with open(args.symbols_file) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if args.universe == "sp500":
        syms = sp500_yahoo_symbols()
    elif args.universe == "ftse100":
        syms = ftse100_yahoo_symbols()
    else:
        raise ValueError(args.universe)
    if args.max_tickers:
        syms = syms[: args.max_tickers]
    return syms


def download_panel(
    symbols: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    sleep_s: float,
    use_cache: bool,
) -> pd.DataFrame:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = _cache_path(symbols, start, end)
    if use_cache and os.path.isfile(cache_path):
        try:
            return pd.read_parquet(cache_path)
        except Exception:
            pass

    p1, p2 = _period_unix(start), _period_unix(end + pd.Timedelta(days=1))
    frames = []
    t0 = time.time()
    for i, sym in enumerate(symbols):
        df = download_symbol(sym, p1, p2, sleep_s=sleep_s)
        if df.empty:
            continue
        frames.append(df)
        if (i + 1) % 50 == 0:
            print(
                "  ... %d/%d symbols (%.0fs)"
                % (i + 1, len(symbols), time.time() - t0),
                file=sys.stderr,
            )
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "open", "close", "volume"])
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["date"] >= start) & (out["date"] <= end)]
    try:
        out.to_parquet(cache_path, index=False)
    except Exception:
        pass
    return out


def fetch_raw_panel(args: argparse.Namespace) -> pd.DataFrame:
    symbols = load_symbols(args)
    start, end = _parse_date(args.start), _parse_date(args.end)
    print(
        "Universe: %d symbols, %s .. %s"
        % (len(symbols), start.date(), end.date()),
        file=sys.stderr,
    )
    df = download_panel(symbols, start, end, args.sleep, use_cache=not args.no_cache)
    print(
        "Raw rows: %d (tickers with data: %d)"
        % (len(df), df["ticker"].nunique()),
        file=sys.stderr,
    )
    return df


def run_strategy(
    panel: pd.DataFrame,
    name: str,
    signal_col: str,
    ret_col: str,
    bottom_decile: bool,
    winsor_q: float,
    args: argparse.Namespace,
) -> dict:
    work = panel.copy()
    sig_for_spearman = signal_col
    if winsor_q > 0 and winsor_q < 0.5:
        wcol = signal_col + "_w"
        work[wcol] = winsorize_cross_section(
            work, "date", signal_col, winsor_q, 1.0 - winsor_q
        )
        wsig = wcol
        sig_for_spearman = wcol
    else:
        wsig = None

    h4 = name.startswith("H4_")
    if h4:
        p = int(args.h4_period)
        daily = non_overlapping_period_decile_returns(
            work,
            "date",
            signal_col,
            ret_col,
            period=p,
            bottom_decile=bottom_decile,
            winsorized_signal_col=wsig,
            frac=args.decile_frac,
            min_bucket=args.min_bucket,
        )
    else:
        daily = daily_decile_returns(
            work,
            "date",
            signal_col,
            ret_col,
            bottom_decile=bottom_decile,
            winsorized_signal_col=wsig,
            frac=args.decile_frac,
            min_bucket=args.min_bucket,
        )
    if daily.empty:
        return {"strategy": name, "error": "no daily returns"}

    daily_net = apply_costs(daily, args.roundtrip_bps)
    obs_per_year = 252.0 / float(args.h4_period) if h4 else 252.0
    gross = summarize_returns(
        daily["portfolio_return"], observations_per_year=obs_per_year
    )
    net = summarize_returns(
        daily_net["portfolio_return_net"], observations_per_year=obs_per_year
    )
    tr, te = train_test_split_by_date(daily_net, args.train_frac)
    train_s = summarize_returns(
        tr["portfolio_return_net"], observations_per_year=obs_per_year
    )
    test_s = summarize_returns(
        te["portfolio_return_net"], observations_per_year=obs_per_year
    )

    sub = work.dropna(subset=[sig_for_spearman, ret_col])
    rebalance_dates = set(daily["date"].tolist()) if h4 else None
    rho = spearman_by_date(
        sub, "date", sig_for_spearman, ret_col, dates_filter=rebalance_dates
    )

    extremes = audit_extreme_days(daily, top_k=5)

    out = {
        "strategy": name,
        "signal": signal_col,
        "forward_return": ret_col,
        "bottom_decile": bottom_decile,
        "spearman_signal_fwd_mean": rho,
        "gross": gross,
        "net_full": net,
        "net_train": train_s,
        "net_test": test_s,
        "extreme_days_gross": extremes.to_dict(orient="records"),
        "daily": daily_net,
    }
    if h4:
        out["holding_trading_days"] = int(args.h4_period)
        out["rebalance"] = "every_%d_trading_days_non_overlap" % int(args.h4_period)
    return out


def execute_backtest(args: argparse.Namespace) -> tuple[list[dict], pd.DataFrame]:
    """
    Run download, filters, all STRATEGIES. Returns (summaries, daily_long DataFrame).
    """
    winsor_q = args.winsorize if 0 < args.winsorize < 0.5 else 0.0

    raw = fetch_raw_panel(args)
    if raw.empty:
        return [], pd.DataFrame()

    clean = filter_panel(
        raw,
        leg_low=args.leg_low,
        leg_high=args.leg_high,
        min_trading_days=args.min_days,
        min_avg_close=args.min_avg_close,
    )
    print(
        "After quality filters: %d tickers, %d rows"
        % (clean["ticker"].nunique(), len(clean)),
        file=sys.stderr,
    )
    if clean.empty:
        return [], pd.DataFrame()

    panel = enrich_return_columns(clean)

    summaries = []
    daily_frames = []
    for name, sig, ret, bottom in STRATEGIES:
        r = run_strategy(panel, name, sig, ret, bottom, winsor_q, args)
        summaries.append({k: v for k, v in r.items() if k != "daily"})
        if "daily" in r and not r["daily"].empty:
            d = r["daily"].copy()
            d["strategy"] = name
            daily_frames.append(d)

    daily_combined = (
        pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    )
    return summaries, daily_combined


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cross-sectional reversal backtests (cleaned Yahoo data)")
    p.add_argument("--universe", choices=["sp500", "ftse100"], default="sp500")
    p.add_argument("--symbols-file", help="One ticker per line (overrides --universe)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--max-tickers", type=int, default=0, help="0 = all")
    p.add_argument("--sleep", type=float, default=0.12, help="Delay between Yahoo requests")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--leg-low", type=float, default=-0.5)
    p.add_argument("--leg-high", type=float, default=2.0)
    p.add_argument("--min-days", type=int, default=252)
    p.add_argument("--min-avg-close", type=float, default=5.0)
    p.add_argument("--no-min-price", action="store_true", help="Disable min avg close filter")
    p.add_argument(
        "--winsorize",
        type=float,
        default=0.01,
        help="Cross-sectional clip quantiles, e.g. 0.01; use 0 to disable",
    )
    p.add_argument("--roundtrip-bps", type=float, default=20.0)
    p.add_argument("--train-frac", type=float, default=0.6)
    p.add_argument("--decile-frac", type=float, default=0.1)
    p.add_argument(
        "--min-bucket",
        type=int,
        default=5,
        help="Minimum names per leg (avoids n=1 buckets on small universes)",
    )
    p.add_argument(
        "--h4-period",
        type=int,
        default=5,
        help="H4 only: rebalance every N trading days (non-overlapping holds)",
    )
    p.add_argument("--out-json", help="Write summary JSON (no daily series)")
    p.add_argument("--out-daily", help="Write combined daily CSV for all strategies")
    p.add_argument("--plot", help="Write equity curve PNG to this path")
    return p


def main() -> None:
    p = build_arg_parser()
    args = p.parse_args()
    if args.no_min_price:
        args.min_avg_close = None

    summaries, daily_combined = execute_backtest(args)
    if not summaries and daily_combined.empty:
        print("No price data or no tickers passed filters.", file=sys.stderr)
        sys.exit(1)

    print("\n=== Caveats ===", file=sys.stderr)
    print(
        "- Universe is current index members from Wikipedia, not point-in-time membership (survivorship).",
        file=sys.stderr,
    )
    print(
        "- Yahoo adjusted series; open scaled per bar. Auction/microstructure not modeled.",
        file=sys.stderr,
    )
    print(
        "- Costs: -%.1f bps per portfolio row (daily strategies: each trading day; H4: each %dd rebalance)."
        % (args.roundtrip_bps, args.h4_period),
        file=sys.stderr,
    )

    print("\n=== Strategy summaries (net of costs, full / train / test) ===")
    for s in summaries:
        print("\n%s" % s["strategy"])
        if "error" in s:
            print("  %s" % s["error"])
            continue
        if s.get("holding_trading_days"):
            htd = int(s["holding_trading_days"])
            print(
                "  H4: non-overlapping %dd holds; n = completed periods; Sharpe/CAGR annualized on ~%.1f periods/year."
                % (htd, 252.0 / htd),
                file=sys.stderr,
            )
        print("  Spearman(signal, fwd) mean: %.4f" % s["spearman_signal_fwd_mean"])
        mean_label = (
            "mean_per_%dd_pct" % int(s["holding_trading_days"])
            if s.get("holding_trading_days")
            else "mean_daily_pct"
        )
        for label, block in [
            ("net_full", s["net_full"]),
            ("net_train", s["net_train"]),
            ("net_test", s["net_test"]),
        ]:
            mean_val = block.get("mean_daily", float("nan")) * 100
            print(
                "  %s: n=%d %s=%.4f Sharpe~=%.2f CAGR=%.2f%% tot=%.1f%% t=%.2f"
                % (
                    label,
                    block.get("n_days", 0),
                    mean_label,
                    mean_val,
                    block.get("sharpe_like", float("nan")),
                    block.get("cagr", float("nan")) * 100,
                    block.get("total_return", float("nan")) * 100,
                    block.get("t_mean_daily", float("nan")),
                )
            )
        ex = s.get("extreme_days_gross") or []
        if ex:
            print(
                "  Top 5 gross daily returns (sanity check): %s"
                % json.dumps(ex, default=str)
            )

    if args.out_json:
        out_j = []
        for s in summaries:
            x = {k: v for k, v in s.items() if k != "daily"}
            out_j.append(x)
        with open(args.out_json, "w") as f:
            json.dump(out_j, f, indent=2, default=str)

    if args.out_daily and not daily_combined.empty:
        daily_combined.to_csv(args.out_daily, index=False)

    if args.plot:
        if daily_combined.empty:
            print("Cannot --plot: no daily strategy returns.", file=sys.stderr)
            sys.exit(1)
        from plot_equity import plot_strategy_equity

        title = "%s %s..%s (roundtrip %sbps)" % (
            args.universe,
            args.start,
            args.end,
            args.roundtrip_bps,
        )
        plot_strategy_equity(
            daily_combined,
            args.plot,
            train_frac=args.train_frac,
            title=title,
        )
        print("Wrote plot %s" % os.path.abspath(args.plot), file=sys.stderr)


if __name__ == "__main__":
    main()
