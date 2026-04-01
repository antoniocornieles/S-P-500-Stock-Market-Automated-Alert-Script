import asyncio
import aiohttp
import time
import subprocess
import pandas as pd
from datetime import datetime

API_KEY = "YOURKEYHERE"
PHONE = "YOURNUMBERHERE"

ALERT_THRESHOLD = 5  # % move
BATCH_SIZE = 25      # control API load
SLEEP_BETWEEN_BATCHES = 1

alerted = set()
summary_sent_date = None

# -----------------------
# SEND SMS (iMessage)
# -----------------------
def send_text(message):
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{PHONE}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    subprocess.run(["osascript", "-e", script])

# -----------------------
# LOAD TICKERS
# -----------------------
def load_tickers():
    df = pd.read_csv("sp500.csv")
    return df["Symbol"].tolist()

# -----------------------
# FETCH QUOTE
# -----------------------
async def fetch_quote(session, ticker):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={API_KEY}"

    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        try:
            return ticker, await resp.json()
        except:
            return None

# -----------------------
# FETCH VOLUME
# -----------------------
async def fetch_volume(session, ticker):
    now = int(time.time())
    earlier = now - 3600

    url = f"https://finnhub.io/api/v1/stock/candle?symbol={ticker}&resolution=1&from={earlier}&to={now}&token={API_KEY}"

    async with session.get(url) as resp:
        if resp.status != 200:
            return 0
        data = await resp.json()

    if data.get("s") != "ok":
        return 0

    vols = data.get("v", [])
    return vols[-1] if vols else 0

# -----------------------
# DAILY SUMMARY
# -----------------------
async def send_daily_summary(session, tickers):
    print("Running market close summary...")

    data = []

    # batch processing
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i+BATCH_SIZE]

        tasks = [fetch_quote(session, t) for t in batch]
        results = await asyncio.gather(*tasks)

        for result in results:
            if not result:
                continue

            ticker, quote = result
            price = quote.get("c", 0)
            prev = quote.get("pc", 0)

            if prev == 0:
                continue

            change = ((price - prev) / prev) * 100
            data.append((ticker, price, change))

        await asyncio.sleep(SLEEP_BETWEEN_BATCHES)

    if not data:
        return

    top_gainer = max(data, key=lambda x: x[2])
    top_loser = min(data, key=lambda x: x[2])
    most_expensive = max(data, key=lambda x: x[1])

    message = f"""
📊 Market Close Summary

💰 Most Expensive:
{most_expensive[0]} (${most_expensive[1]:.2f})

📈 Top Gainer:
{top_gainer[0]} (+{top_gainer[2]:.2f}%)

📉 Top Loser:
{top_loser[0]} ({top_loser[2]:.2f}%)
"""

    send_text(message)

# -----------------------
# MAIN LOOP
# -----------------------
async def run_bot():
    global summary_sent_date

    tickers = load_tickers()

    async with aiohttp.ClientSession() as session:

        while True:
            print("Scanning S&P 500...")

            movers = []

            # batch scan
            for i in range(0, len(tickers), BATCH_SIZE):
                batch = tickers[i:i+BATCH_SIZE]

                tasks = [fetch_quote(session, t) for t in batch]
                results = await asyncio.gather(*tasks)

                for result in results:
                    if not result:
                        continue

                    ticker, quote = result

                    price = quote.get("c", 0)
                    prev = quote.get("pc", 0)

                    if prev == 0:
                        continue

                    change = ((price - prev) / prev) * 100

                    if abs(change) >= ALERT_THRESHOLD:
                        movers.append((ticker, price, change))

                await asyncio.sleep(SLEEP_BETWEEN_BATCHES)

            # 🔥 fetch volume only for movers
            for ticker, price, change in movers:

                if ticker in alerted:
                    continue

                volume = await fetch_volume(session, ticker)

                message = f"""
🚨 Market Alert

{ticker}
Move: {change:.2f}%
Price: ${price:.2f}
Volume: {volume}
"""

                send_text(message)
                print(f"ALERT: {ticker} {change:.2f}%")

                alerted.add(ticker)

            # 📊 MARKET CLOSE SUMMARY
            now = datetime.now()

            if now.hour >= 17 and summary_sent_date != now.date():
                await send_daily_summary(session, tickers)
                summary_sent_date = now.date()

            await asyncio.sleep(60)

# -----------------------
# RUN
# -----------------------
asyncio.run(run_bot())

