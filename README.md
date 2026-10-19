# True Breakout & Delivery Stock Screener

## Deploy on Streamlit Community Cloud
1. Create a new GitHub repository.
2. Upload `app.py`, `requirements.txt`, and `README.md`.
3. In Streamlit Community Cloud, deploy the repository and choose `app.py` as the entry point.

## What it does
- Fetches the current Nifty 500 constituent CSV from Nifty Indices, with an NSE archives fallback.
- Scans daily Yahoo Finance data in parallel and displays progress/count.
- Applies the supplied conditions: close above 50-day and 200-day SMA, price/high touching the previous 20-day high, volume at least 2.5x the 20-day average, close in the top 25% of the daily range, and minimum daily gain.
- Shows stop-loss at signal-day low and +6% / +12% reference targets.
- Provides CSV export and a diagnostics panel for data errors.

## Important notes
- The original rules use SMA, not EMA. This package keeps SMA to avoid changing the strategy.
- The original breakout rule accepts a high touching the previous 20-day high even if the close is below that level; this is preserved as requested.
- Despite the title, delivery percentage is not checked because it was not part of the supplied code. Volume surge is checked.
- Yahoo Finance data may be delayed, missing, rate-limited, or unavailable for some symbols. The app lists errors rather than silently hiding them.
- The scanner uses 1 year of daily history so the 200-day SMA can be calculated. The conditions still evaluate the latest available daily candle, which may be the in-progress candle during market hours.
- The +6% and +12% levels are reference targets, not predictions or guaranteed outcomes. This scanner is informational and not financial advice.
