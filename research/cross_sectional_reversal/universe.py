"""Load equity universes (S&P 500, optional FTSE 100) from Wikipedia."""

from __future__ import annotations

import urllib.request

import pandas as pd

USER_AGENT = "Mozilla/5.0 (compatible; cross-sectional-reversal-research/1.0)"


def _read_wiki_table(url: str) -> pd.DataFrame:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as r:
        html = r.read()
    tables = pd.read_html(html)
    return tables[0]


def sp500_yahoo_symbols() -> list[str]:
    """Current S&P 500 constituents; Yahoo uses '-' instead of '.' in symbols."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = _read_wiki_table(url)
    return df["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()


def ftse100_yahoo_symbols() -> list[str]:
    """FTSE 100 tickers as Yahoo symbols (suffix .L)."""
    url = "https://en.wikipedia.org/wiki/FTSE_100_Index"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as r:
        html = r.read()
    tables = pd.read_html(html)
    df = None
    for t in tables:
        if "Ticker" in t.columns:
            df = t
            break
    if df is None:
        raise ValueError("Could not find FTSE 100 constituents table with Ticker column")
    raw = df["Ticker"].astype(str).str.strip().tolist()
    return [("%s.L" % t.replace(".", "-")) for t in raw if t and t.lower() != "nan"]
