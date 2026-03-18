import os
import yfinance as yf
import ta
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT_ID")

TICKERS = [
"SOFI","RKLB","IONQ","OPEN","UPST","RIOT","MARA","FUBO","NIO","LCID",
"CLOV","BB","GME","AMC","BBAI","SOUN","ASTS","LUNR","NVVE","HOLO",
"ANY","QNRX","NXTT","FFIE","SINT","WKHS","MVIS","PLUG","RUN","CHPT",
"BLNK","SPCE","QS","RIVN","NKLA","GPRO","SNAP","AFRM","COIN","MSTR",
"DNA","JOBY","EVGO","LAZR","VLDR","XPEV","LI","KNDI","FSR","MULN"
]

MIN_PRICE = 1
MAX_PRICE = 40
MIN_GAP = 2
MIN_VOLUME = 100000

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT, "text": msg})
    except:
        print(msg)

def get_signal(price, buy, target1, target2, stop):
    if price < buy:
        return "⏳ חכה"
    elif buy <= price < target1:
        return "🟢 קנה"
    elif target1 <= price < target2:
        return "🟡 החזק / מכור חצי"
    elif price >= target2:
        return "🔴 מכור (יעד הושג)"
    elif price <= stop:
        return "⛔ עצור הפסד"
    return "❓"

def scan_stock(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="1h", progress=False)
        if len(df) < 20:
            return None

        price = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        gap = (price - prev) / prev * 100
        volume = float(df["Volume"].iloc[-1])

        rsi = ta.momentum.RSIIndicator(df["Close"]).rsi().iloc[-1]

        if price < MIN_PRICE or price > MAX_PRICE:
            return None
        if gap < MIN_GAP:
            return None
        if volume < MIN_VOLUME:
            return None

        buy = round(price * 1.01, 2)
        target1 = round(price * 1.10, 2)
        target2 = round(price * 1.25, 2)
        stop = round(price * 0.95, 2)

        signal = get_signal(price, buy, target1, target2, stop)

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "gap": round(gap, 2),
            "volume": int(volume),
            "rsi": round(rsi, 1),
            "buy": buy,
            "target1": target1,
            "target2": target2,
            "stop": stop,
            "signal": signal
        }

    except:
        return None

def main():
    results = []

    for t in TICKERS:
        s = scan_stock(t)
        if s:
            results.append(s)

    results = sorted(results, key=lambda x: x["gap"], reverse=True)

    if not results:
        send_telegram("⚠️ אין מניות חמות כרגע – חכה לפתיחת תנועה")
        return

    msg = "🚀 החלטות למסחר יומי\n\n"

    for r in results[:5]:
        msg += f"{r['signal']} {r['ticker']}\n"
        msg += f"מחיר: ${r['price']} | שינוי: {r['gap']}%\n"
        msg += f"📍 קנייה: ${r['buy']}\n"
        msg += f"🎯 יעד1: ${r['target1']} | יעד2: ${r['target2']}\n"
        msg += f"🛑 סטופ: ${r['stop']}\n\n"

    send_telegram(msg)

if __name__ == "__main__":
    main()
