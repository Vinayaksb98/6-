import concurrent.futures
import io
import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="True Breakout & Delivery Screener",
    page_icon="📈",
    layout="wide",
)

st.title("📈 True Breakout & Delivery Stock Screener")
st.markdown(
    """
This scanner checks daily price action for trend alignment, a 20-day breakout,
a volume surge, a strong candle close, and a minimum daily gain.

**Important:** This version preserves the supplied strategy's actual rules. It
does not calculate delivery percentage; the original code only checks traded volume.
"""
)

st.sidebar.header("Screener Parameters")
universe_choice = st.sidebar.selectbox("Select Universe", ["Nifty 500", "Custom List"])

@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def get_nifty500_tickers():
    """Fetch current Nifty 500 constituents from the official Nifty Indices CSV."""
    urls = [
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,text/plain,*/*",
        "Referer": "https://www.niftyindices.com/",
    }
    last_error = None
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            frame = pd.read_csv(io.BytesIO(response.content))
            symbol_col = next(
                (col for col in frame.columns if str(col).strip().lower() == "symbol"),
                None,
            )
            if symbol_col is None:
                raise ValueError("Constituent CSV has no Symbol column.")
            symbols = (
                frame[symbol_col]
                .dropna()
                .astype(str)
                .str.strip()
                .str.upper()
            )
            symbols = symbols[symbols.ne("")]
            tickers = sorted({f"{symbol}.NS" for symbol in symbols})
            if len(tickers) < 400:
                raise ValueError(f"Expected around 500 constituents, received {len(tickers)}.")
            return tickers
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not fetch the official Nifty 500 constituent list: {last_error}")

if universe_choice == "Nifty 500":
    try:
        tickers = get_nifty500_tickers()
        st.sidebar.success(f"Universe loaded: {len(tickers)} stocks")
    except Exception as exc:
        tickers = []
        st.sidebar.error("Could not load Nifty 500 constituents.")
        st.sidebar.caption(str(exc))
else:
    custom_input = st.sidebar.text_area(
        "Enter tickers (comma-separated, with or without .NS)",
        "TRENT.NS, POLYCAB.NS, DIXON.NS, PERSISTENT.NS",
    )
    tickers = []
    for item in custom_input.split(","):
        symbol = item.strip().upper()
        if symbol:
            tickers.append(symbol if symbol.endswith(".NS") else f"{symbol}.NS")
    tickers = sorted(set(tickers))

min_gain = st.sidebar.slider("Min Daily Gain (%)", 1.0, 8.0, 3.0, 0.5)
st.sidebar.caption("Data: Yahoo Finance daily candles. Results are cached for 1 hour.")

@st.cache_data(ttl=3600, show_spinner=False)
def analyze_stock(ticker, minimum_gain):
    """Apply the supplied breakout rules to one stock."""
    try:
        # Use 1 year so the 200-day simple moving average can be calculated.
        df = yf.download(
            ticker,
            period="1y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=20,
        )
        if df is None or df.empty:
            return {"status": "error", "ticker": ticker, "reason": "No price data returned"}

        if isinstance(df.columns, pd.MultiIndex):
            # yfinance can return either (Price, Ticker) or (Ticker, Price).
            if ticker in df.columns.get_level_values(-1):
                df = df.xs(ticker, axis=1, level=-1)
            else:
                df.columns = df.columns.get_level_values(0)

        required = {"Close", "High", "Low", "Volume"}
        if not required.issubset(set(df.columns)):
            return {"status": "error", "ticker": ticker, "reason": "Missing OHLCV columns"}

        df = df.dropna(subset=["Close", "High", "Low", "Volume"]).copy()
        if len(df) < 50:
            return {"status": "error", "ticker": ticker, "reason": "Fewer than 50 daily candles"}

        for col in ["Close", "High", "Low", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close", "High", "Low", "Volume"])

        df["SMA_50"] = df["Close"].rolling(window=50, min_periods=50).mean()
        df["SMA_200"] = df["Close"].rolling(window=200, min_periods=200).mean()
        df["Vol_SMA_20"] = df["Volume"].rolling(window=20, min_periods=20).mean()
        df["High_20"] = df["High"].shift(1).rolling(window=20, min_periods=20).max()

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest["Close"])
        high = float(latest["High"])
        low = float(latest["Low"])
        volume = float(latest["Volume"])
        vol_sma20 = float(latest["Vol_SMA_20"])
        sma50 = float(latest["SMA_50"])
        sma200 = float(latest["SMA_200"])
        high20 = float(latest["High_20"])
        prev_close = float(prev["Close"])

        if prev_close <= 0 or pd.isna(vol_sma20) or vol_sma20 <= 0 or pd.isna(sma50) or pd.isna(sma200) or pd.isna(high20):
            return {"status": "skipped", "ticker": ticker, "reason": "Insufficient history for indicators"}

        daily_gain = ((close - prev_close) / prev_close) * 100

        # Preserve supplied rules exactly, including SMA trend and high-touch breakout.
        cond_trend = (close > sma50) and (close > sma200)
        cond_breakout = (close >= high20) or (high >= high20)
        cond_volume = volume >= (vol_sma20 * 2.5)
        day_range = high - low
        close_position_ratio = (close - low) / day_range if day_range > 0 else 0
        cond_candle = close_position_ratio >= 0.75
        cond_gain = daily_gain >= minimum_gain

        checks = {
            "Above 50 & 200 SMA": cond_trend,
            "20-day breakout": cond_breakout,
            "Volume ≥ 2.5× average": cond_volume,
            "Close in top 25%": cond_candle,
            "Daily gain threshold": cond_gain,
        }
        if all(checks.values()):
            return {
                "status": "match",
                "Ticker": ticker.replace(".NS", ""),
                "Close Price (₹)": round(close, 2),
                "Daily Gain (%)": round(daily_gain, 2),
                "Volume Multiple": round(volume / vol_sma20, 2),
                "Stop-Loss (₹)": round(low, 2),
                "Target 1 (+6%)": round(close * 1.06, 2),
                "Target 2 (+12%)": round(close * 1.12, 2),
                "Signal Date": df.index[-1].strftime("%Y-%m-%d"),
            }

        return {"status": "not_match", "ticker": ticker, "reason": "One or more rules not met"}
    except Exception as exc:
        return {"status": "error", "ticker": ticker, "reason": str(exc)[:240]}

if st.button("Run True Breakout Scan", type="primary", disabled=not tickers):
    progress = st.progress(0, text="Preparing scan…")
    status_text = st.empty()
    results = []
    errors = []
    total = len(tickers)
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(analyze_stock, ticker, min_gain): ticker for ticker in tickers}
        for future in concurrent.futures.as_completed(futures):
            ticker = futures[future]
            completed += 1
            try:
                result = future.result()
                if result and result.get("status") == "match":
                    results.append(result)
                elif result and result.get("status") == "error":
                    errors.append({"Ticker": ticker, "Error": result.get("reason", "Unknown error")})
            except Exception as exc:
                errors.append({"Ticker": ticker, "Error": str(exc)[:240]})
            progress.progress(completed / total, text=f"Scanned {completed} of {total} stocks")
            status_text.caption(f"Completed {completed}/{total} · Candidates found: {len(results)}")

    st.session_state["breakout_results"] = results
    st.session_state["breakout_errors"] = errors
    st.session_state["breakout_scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    progress.empty()
    status_text.empty()

if "breakout_results" in st.session_state:
    results = st.session_state["breakout_results"]
    errors = st.session_state.get("breakout_errors", [])
    st.caption(f"Last scan completed: {st.session_state.get('breakout_scan_time', 'Unknown')}")
    if results:
        res_df = pd.DataFrame(results)
        res_df = res_df.sort_values("Daily Gain (%)", ascending=False).reset_index(drop=True)
        st.success(f"Found {len(res_df)} True Breakout candidate(s).")
        st.dataframe(res_df, use_container_width=True, hide_index=True)
        csv_data = res_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Results as CSV",
            data=csv_data,
            file_name="nifty500_true_breakout_scan.csv",
            mime="text/csv",
        )
    else:
        st.warning("No stocks passed all five rules in the last scan.")
    with st.expander(f"Scan diagnostics ({len(errors)} data errors)"):
        st.write("Stocks with missing/unavailable data are listed here; they are not treated as passing candidates.")
        if errors:
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)
        else:
            st.success("No data-fetch errors reported.")
