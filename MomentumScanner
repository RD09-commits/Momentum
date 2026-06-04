#!/usr/bin/env python3
"""
Momentum-scanner (VS + Europa/NL): minder bekende aandelen die al een paar
dagen fors stijgen, met volumebevestiging en marktkap >= $1 mrd.

VS    : Finviz scant de hele markt (NYSE/Nasdaq).
Europa: yfinance scant een vast universum uit 'eu_universe.txt'
        (er is geen gratis markt-brede Europese screener).

Verhandelbaarheid: gericht op NL/EU/VS-genoteerde namen >$1 mrd; die zijn bij
ABN AMRO (Zelf Beleggen Plus, 22 beurslanden) vrijwel altijd te koop.

Dit is een ONTDEK-radar, GEEN koopsignaal.

Secrets (GitHub Actions): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Deps: pip install finvizfinance yfinance pandas requests
"""

import os
import sys
import requests
import yfinance as yf
from finvizfinance.screener.overview import Overview

# --- Config ---
MIN_CAP = 1_000_000_000        # ondergrens marktkap ($)
MAX_CAP = None                 # bovengrens of None (bv. 20e9 om "minder bekend" te houden)
MAX_RESULTS = 12               # max namen per regio

US_FILTERS = {
    "Market Cap.": "+Small (over $300mln)",  # >=1B wordt in code gefilterd
    "Performance": "Week +20%",               # paar dagen forse groei
    "Relative Volume": "Over 2",              # volumepiek
    "Average Volume": "Over 500K",            # liquiditeit
}
EU_UNIVERSE_FILE = "eu_universe.txt"
EU_MOVE = 20.0                 # min. 5-daags rendement (%)
EU_RELVOL = 2.0                # min. relatief volume t.o.v. 20-daags gemiddelde

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
ROCKET, EU_FLAG, US_FLAG, WARN = "\U0001F680", "\U0001F1EA\U0001F1FA", "\U0001F1FA\U0001F1F8", "\u26A0\uFE0F"


def parse_cap(s):
    s = str(s).strip()
    if not s or s in ("-", "nan", "None"):
        return None
    mult = {"B": 1e9, "M": 1e6, "K": 1e3, "T": 1e12}
    try:
        return float(s[:-1]) * mult[s[-1]] if s[-1] in mult else float(s)
    except (ValueError, IndexError):
        return None


def fmt_cap(c):
    if not c:
        return "?"
    return f"${c/1e9:.1f}B" if c >= 1e9 else f"${c/1e6:.0f}M"


def screen_us():
    fov = Overview()
    fov.set_filter(filters_dict=US_FILTERS)
    df = fov.screener_view()
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        cap = parse_cap(r.get("Market Cap"))
        if cap is None or cap < MIN_CAP or (MAX_CAP and cap > MAX_CAP):
            continue
        rows.append({
            "ticker": str(r.get("Ticker", "")).upper(),
            "company": str(r.get("Company", ""))[:26],
            "move": str(r.get("Change", "")),   # vandaag (week zit al in de filter)
            "cap": cap,
        })

    def chg(x):
        try:
            return float(str(x["move"]).replace("%", ""))
        except Exception:
            return -999
    rows.sort(key=chg, reverse=True)
    return rows[:MAX_RESULTS]


def load_universe():
    if not os.path.exists(EU_UNIVERSE_FILE):
        return []
    with open(EU_UNIVERSE_FILE) as f:
        return [ln.strip() for ln in f
                if ln.strip() and not ln.strip().startswith("#")]


def screen_eu():
    tickers = load_universe()
    if not tickers:
        return []
    data = yf.download(tickers, period="1mo", interval="1d", group_by="ticker",
                       auto_adjust=False, progress=False, threads=True)
    hits = []
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            close = df["Close"].dropna()
            vol = df["Volume"].dropna()
            if len(close) < 6 or len(vol) < 21:
                continue
            move5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100
            relvol = vol.iloc[-1] / vol.iloc[-21:-1].mean()
            if move5 >= EU_MOVE and relvol >= EU_RELVOL:
                hits.append({"ticker": t, "move5": round(move5, 1),
                             "price": round(float(close.iloc[-1]), 2)})
        except Exception:
            continue

    # marktkap alleen checken voor de paar die door de filter komen
    out = []
    for h in hits:
        cap, name = None, ""
        try:
            info = yf.Ticker(h["ticker"]).info
            cap = info.get("marketCap")
            name = (info.get("shortName") or "")[:26]
        except Exception:
            pass
        if cap is not None and (cap < MIN_CAP or (MAX_CAP and cap > MAX_CAP)):
            continue
        h["cap"], h["company"] = cap, name
        out.append(h)
    out.sort(key=lambda x: x["move5"], reverse=True)
    return out[:MAX_RESULTS]


def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": msg}, timeout=15,
    )


def main():
    errors = []
    try:
        us = screen_us()
    except Exception as e:
        us, _ = [], errors.append(f"VS-screen: {e}")
    try:
        eu = screen_eu()
    except Exception as e:
        eu, _ = [], errors.append(f"EU-screen: {e}")

    if not us and not eu:
        if errors:
            send(f"{WARN} Momentum-scanner: {' | '.join(errors)}")
        print("Geen kandidaten." + (" Fouten: " + "; ".join(errors) if errors else ""))
        return

    parts = [f"{ROCKET} MOMENTUM-KANDIDATEN (paar dagen >+20%, hoog volume, >$1B)"]
    if us:
        parts.append(f"\n{US_FLAG} VS")
        parts += [f"{r['ticker']}  {r['move']}  ({fmt_cap(r['cap'])})  {r['company']}" for r in us]
    if eu:
        parts.append(f"\n{EU_FLAG} Europa/NL  (5-daags)")
        parts += [f"{r['ticker']}  +{r['move5']}%  ({fmt_cap(r['cap'])})  {r['company']}" for r in eu]
    parts.append("\nOnderzoeksradar, geen koopsignaal.")
    if errors:
        parts.append(f"({WARN} {'; '.join(errors)})")
    send("\n".join(parts))
    print(f"VS: {len(us)}, EU: {len(eu)} kandidaten verstuurd.")


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
