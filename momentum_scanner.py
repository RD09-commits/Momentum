#!/usr/bin/env python3
"""
Momentum-scanner v2 (VS + Europa/NL) -- Zacks-geinspireerd.

Toegangsfilter (recente explosieve beweging):
  - 1-weeks rendement >= MOVE_MIN
  - >= MIN_UP_DAYS stijgdagen in de laatste 5
  - relatief volume >= RELVOL_MIN
  - marktkap >= MIN_CAP

Context + rangschikking (zo onderscheid je echte winnaars van meelifters):
  - rendement over week / maand / kwartaal / jaar
  - relatieve sterkte (RS) t.o.v. de index (S&P 500 / STOXX 600), 3-maands
  - P/E met vlaggetje bij absurde/negatieve waardering
  - composite z-score over alle kandidaten -> sortering

VS    : Finviz vindt kandidaten in de hele markt; yfinance berekent de rest.
Europa: yfinance scant 'eu_universe.txt'.

ONTDEK-radar, GEEN koopsignaal.
Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Deps: pip install finvizfinance yfinance pandas requests
"""

import os
import sys
import statistics
import requests
import yfinance as yf
from finvizfinance.screener.overview import Overview

# --- Config ---
MIN_CAP = 1_000_000_000
MAX_CAP = None                 # None = mega-caps toegestaan
MOVE_MIN = 20.0                # min. 1-weeks rendement (%) -- de "explosieve" trigger
RELVOL_MIN = 2.0
MIN_UP_DAYS = 3
MAX_RESULTS = 10               # per regio
PE_FLAG = 100.0                # P/E hierboven (of negatief) krijgt een vlaggetje

US_FILTERS = {
    "Market Cap.": "+Small (over $300mln)",
    "Performance": "Week +20%",
    "Average Volume": "Over 500K",
    # relatief volume bewust NIET hier: dat checkt de code zelf met een
    # robuuste (mediaan-)basislijn, anders valt een verse uitbarsting eruit.
}
DEBUG = bool(os.environ.get("DEBUG"))
EU_UNIVERSE_FILE = "eu_universe.txt"
BENCH = {"US": "^GSPC", "EU": "^STOXX"}   # S&P 500 / STOXX Europe 600

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
ROCKET, WARN = "\U0001F680", "\u26A0\uFE0F"


def fmt_cap(c):
    if not c:
        return "?"
    return f"${c/1e9:.1f}B" if c >= 1e9 else f"${c/1e6:.0f}M"


def in_cap_range(cap):
    if cap is None:
        return True
    if cap < MIN_CAP or (MAX_CAP and cap > MAX_CAP):
        return False
    return True


def horizon_returns(close):
    close = close.dropna()
    n = len(close)
    def r(k):
        return (close.iloc[-1] / close.iloc[-1 - k] - 1) * 100 if n > k else None
    y = (close.iloc[-1] / close.iloc[0] - 1) * 100 if n > 200 else None
    return {"1w": r(5), "1m": r(21), "3m": r(63), "1y": y}


def bench_returns(symbol):
    try:
        h = yf.download(symbol, period="1y", interval="1d",
                        progress=False, auto_adjust=False)
        return horizon_returns(h["Close"].squeeze())
    except Exception:
        return {"1w": None, "1m": None, "3m": None, "1y": None}


def discover_us():
    fov = Overview()
    fov.set_filter(filters_dict=US_FILTERS)
    df = fov.screener_view()
    if df is None or df.empty:
        return []
    return [str(t).upper() for t in df["Ticker"].tolist()]


def load_universe():
    if not os.path.exists(EU_UNIVERSE_FILE):
        return []
    with open(EU_UNIVERSE_FILE) as f:
        return [ln.strip() for ln in f
                if ln.strip() and not ln.strip().startswith("#")]


def scan(tickers, region):
    if not tickers:
        return []
    bench = bench_returns(BENCH[region])
    data = yf.download(tickers, period="1y", interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)
    out = []
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            close = df["Close"].dropna()
            vol = df["Volume"].dropna()
            if len(close) < 6 or len(vol) < 21:
                continue
            hr = horizon_returns(close)
            base = vol.iloc[-21:-1].median()        # mediaan: ongevoelig voor 1 piekdag
            relvol = vol.iloc[-1] / base if base else 0
            up_days = int((close.pct_change().dropna().iloc[-5:] > 0).sum())
            if DEBUG:
                print(f"  {t}: 1w={hr['1w']} relvol={relvol:.2f} up={up_days}/5")
            # Toegangsfilter
            if hr["1w"] is None or hr["1w"] < MOVE_MIN:
                continue
            if relvol < RELVOL_MIN or up_days < MIN_UP_DAYS:
                continue
            # P/E + cap + naam
            cap, name, pe = None, "", None
            try:
                info = yf.Ticker(t).info
                cap = info.get("marketCap")
                name = (info.get("shortName") or "")[:20]
                pe = info.get("trailingPE")
            except Exception:
                pass
            if not in_cap_range(cap):
                continue
            rs3 = (hr["3m"] - bench["3m"]) if (hr["3m"] is not None and bench["3m"] is not None) else None
            out.append({"ticker": t, "region": region,
                        "r_1w": hr["1w"], "r_1m": hr["1m"], "r_3m": hr["3m"], "r_1y": hr["1y"],
                        "rs_3m": rs3, "up_days": up_days, "pe": pe,
                        "cap": cap, "company": name})
        except Exception:
            continue
    return out


def zscores(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return [0.0] * len(values)
    m, s = statistics.mean(vals), statistics.pstdev(vals)
    if s == 0:
        return [0.0] * len(values)
    return [((v - m) / s if v is not None else 0.0) for v in values]


def add_scores(pool):
    z1 = zscores([c["r_1m"] for c in pool])
    z2 = zscores([c["r_3m"] for c in pool])
    z3 = zscores([c["rs_3m"] for c in pool])
    for c, a, b, d in zip(pool, z1, z2, z3):
        c["score"] = round((a + b + d) / 3, 2)


def num(v):
    return f"{v:+.0f}" if v is not None else "?"


def pe_txt(pe):
    if pe is None:
        return "PE?"
    return f"PE{pe:.0f}" + ("!" if (pe < 0 or pe > PE_FLAG) else "")


def rows_block(title, rows):
    lines = [title]
    for c in rows:
        lines.append(
            f"[{c['score']:+.1f}] {c['ticker']}  "
            f"w{num(c['r_1w'])} m{num(c['r_1m'])} q{num(c['r_3m'])} y{num(c['r_1y'])}  "
            f"RS{num(c['rs_3m'])}  {pe_txt(c['pe'])}  {fmt_cap(c['cap'])}  {c['company']}"
        )
    return "\n".join(lines)


def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": msg}, timeout=15,
    )


def main():
    errors = []
    try:
        us = scan(discover_us(), "US")
    except Exception as e:
        us = []
        errors.append(f"VS: {e}")
    try:
        eu = scan(load_universe(), "EU")
    except Exception as e:
        eu = []
        errors.append(f"EU: {e}")

    if not us and not eu:
        if errors:
            send(f"{WARN} Momentum-scanner: {' | '.join(errors)}")
        print("Geen kandidaten." + (" | " + "; ".join(errors) if errors else ""))
        return

    add_scores(us + eu)
    us.sort(key=lambda x: x["score"], reverse=True)
    eu.sort(key=lambda x: x["score"], reverse=True)
    us, eu = us[:MAX_RESULTS], eu[:MAX_RESULTS]

    blocks = [f"{ROCKET} MOMENTUM-KANDIDATEN  (w/m/q/y = week/maand/kwartaal/jaar %, "
              "RS = vs index 3m, score = composite z)"]
    if us:
        blocks.append(rows_block("\n== Verenigde Staten ==", us))
    if eu:
        blocks.append(rows_block("\n== Europa & Nederland ==", eu))
    blocks.append("\nOnderzoeksradar, geen koopsignaal. ! = extreme/negatieve P/E.")
    if errors:
        blocks.append(f"({WARN} {'; '.join(errors)})")
    send("\n".join(blocks))
    print(f"VS: {len(us)}, EU: {len(eu)} verstuurd.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fout: {e}", file=sys.stderr)
        try:
            send(f"{WARN} Momentum-scanner crashte: {e}")
        except Exception:
            pass
        sys.exit(1)
