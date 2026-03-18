"""
=============================================================
  📈 DAY TRADING BOT PRO v4.0 — Small Caps Edition
  מטרה: +10–30% ביום | תקציב קטן | הודעה ברורה ומסודרת
  כולל: קנה / מכור / המתן + כמות מניות לפי תקציב
=============================================================
"""

import os, time, logging, math, pytz
from datetime import datetime, time as dtime

import yfinance as yf
import ta
import requests

# ─────────────────────────────────────────────
#  הגדרות – שנה כאן לפי הצורך
# ─────────────────────────────────────────────
TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT           = os.getenv("TELEGRAM_CHAT_ID")

BUDGET         = 250    # $ – התקציב שלך לעסקה אחת
MAX_POSITIONS  = 3      # מקסימום עסקאות פתוחות במקביל
PROFIT_TARGET  = 0.18   # יעד רווח 18%
STOP_LOSS      = 0.05   # סטופ לוס 5%
ENTRY_ABOVE    = 0.01   # כניסה 1% מעל מחיר שוק (breakout)

MIN_PRICE      = 1.5
MAX_PRICE      = 40.0
MIN_GAP_PCT    = 3.0
MIN_VOLUME     = 500_000
VOL_SPIKE_MIN  = 1.5
RSI_MIN        = 45
RSI_MAX        = 82
MIN_SCORE      = 55

TICKERS = [
    "SOFI","UPST","AFRM","OPEN","HOOD",
    "RIOT","MARA","COIN","HUT","CLSK",
    "RKLB","ASTS","LUNR","SPCE","ASTR",
    "IONQ","BBAI","SOUN","ARQQ","QUBT",
    "NIO","LCID","FFIE","WKHS","CHPT",
    "PLUG","RUN","BLNK","NVVE","EVGO",
    "GME","AMC","CLOV","BB","MVIS",
    "FUBO","HOLO","ANY","SINT","MNTS",
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  שעות מסחר
# ─────────────────────────────────────────────
def market_phase() -> str:
    ny  = pytz.timezone("America/New_York")
    now = datetime.now(ny)
    t   = now.time()
    if now.weekday() >= 5:               return "closed"
    if dtime(4,0)  <= t < dtime(9,30):  return "pre-market"
    if dtime(9,30) <= t < dtime(12,0):  return "morning"
    if dtime(12,0) <= t < dtime(14,0):  return "midday"
    if dtime(14,0) <= t <= dtime(16,0): return "afternoon"
    return "closed"

def is_market_open() -> bool:
    return market_phase() not in ("closed", "pre-market")


# ─────────────────────────────────────────────
#  ניקוד משוקלל 0–100
# ─────────────────────────────────────────────
def compute_score(gap, rsi, vol_spike, mom_5m, macd_bull) -> float:
    gap_score  = min(gap * 5, 35)
    vol_score  = min(math.log(max(vol_spike, 1)) * 14, 30)
    rsi_score  = 20 if 55<=rsi<=75 else 12 if (50<=rsi<55 or 75<rsi<=80) else 3 if rsi>80 else 5
    mom_score  = min(max(mom_5m, 0) * 6, 15)
    macd_bonus = 5 if macd_bull else 0
    return round(min(gap_score + vol_score + rsi_score + mom_score + macd_bonus, 100), 1)


# ─────────────────────────────────────────────
#  המלצה ברורה + כמות מניות
# ─────────────────────────────────────────────
def get_action(score, rsi, gap, vol_spike, price, budget) -> dict:
    usable       = budget * 0.95
    entry        = round(price * (1 + ENTRY_ABOVE), 2)
    shares       = int(usable // entry)
    invested     = round(shares * entry, 2)
    target_price = round(entry * (1 + PROFIT_TARGET), 2)
    stop_price   = round(entry * (1 - STOP_LOSS), 2)
    potential    = round(shares * (target_price - entry), 2)
    risk_usd     = round(shares * (entry - stop_price), 2)
    rr           = round(potential / risk_usd, 1) if risk_usd > 0 else 0

    if rsi > 82:
        return dict(action="SELL_AVOID", emoji="🔴",
                    hebrew="אל תיכנס / צא אם יש לך",
                    reason="RSI גבוה מדי – סיכון גבוה לירידה",
                    shares=0, invested=0, entry=entry,
                    target_price=target_price, stop_price=stop_price,
                    potential=0, risk_usd=0, rr=0)

    if score >= 80 and gap >= 8:
        action, emoji, hebrew = "STRONG_BUY", "🚀", "קנה עכשיו – סיגנל חזק מאוד"
        reason = f"גאפ {gap:.1f}% + Volume ×{vol_spike:.1f} + RSI אידיאלי"
    elif score >= 70:
        action, emoji, hebrew = "BUY", "🟢", "קנה – סיגנל טוב"
        reason = f"גאפ {gap:.1f}% + ציון {score}/100 – כניסה טובה"
    elif score >= 55:
        action, emoji, hebrew = "WATCH", "🟡", "עקוב – המתן לנר ירוק נוסף"
        reason = f"ציון {score}/100 – חכה לאישור נוסף לפני כניסה"
    else:
        action, emoji, hebrew = "WAIT", "⏳", "המתן – עדיין לא הזמן"
        reason = f"ציון {score}/100 – אין מספיק אישורים"

    return dict(action=action, emoji=emoji, hebrew=hebrew, reason=reason,
                shares=shares, invested=invested, entry=entry,
                target_price=target_price, stop_price=stop_price,
                potential=potential, risk_usd=risk_usd, rr=rr)


# ─────────────────────────────────────────────
#  סריקת מנייה
# ─────────────────────────────────────────────
def scan_stock(ticker: str) -> dict | None:
    try:
        df_d = yf.download(ticker, period="10d", interval="1d",
                           progress=False, auto_adjust=True)
        if len(df_d) < 3: return None

        price      = float(df_d["Close"].iloc[-1])
        prev_close = float(df_d["Close"].iloc[-2])
        today_open = float(df_d["Open"].iloc[-1])
        volume     = float(df_d["Volume"].iloc[-1])
        avg_vol    = float(df_d["Volume"].iloc[-6:-1].mean())

        gap       = (today_open - prev_close) / prev_close * 100
        vol_spike = volume / avg_vol if avg_vol > 0 else 0

        if not (MIN_PRICE <= price <= MAX_PRICE): return None
        if gap < MIN_GAP_PCT:                     return None
        if volume < MIN_VOLUME:                   return None
        if vol_spike < VOL_SPIKE_MIN:             return None

        df_h  = yf.download(ticker, period="2d", interval="30m",
                            progress=False, auto_adjust=True)
        df_5m = yf.download(ticker, period="1d", interval="5m",
                            progress=False, auto_adjust=True)
        if len(df_h) < 14: return None

        rsi_30m   = float(ta.momentum.RSIIndicator(df_h["Close"], 14).rsi().iloc[-1])
        rsi_daily = float(ta.momentum.RSIIndicator(df_d["Close"], 14).rsi().iloc[-1])
        rsi       = round(rsi_30m * 0.65 + rsi_daily * 0.35, 1)
        if not (RSI_MIN <= rsi <= RSI_MAX): return None

        mom_5m = 0.0
        if len(df_5m) >= 3:
            mom_5m = float((df_5m["Close"].iloc[-1] - df_5m["Close"].iloc[-3])
                           / df_5m["Close"].iloc[-3] * 100)

        macd_obj  = ta.trend.MACD(df_h["Close"])
        macd_bull = float(macd_obj.macd().iloc[-1]) > float(macd_obj.macd_signal().iloc[-1])

        bb     = ta.volatility.BollingerBands(df_h["Close"])
        bb_pct = round((price / float(bb.bollinger_hband().iloc[-1]) - 1) * 100, 1)

        score = compute_score(gap, rsi, vol_spike, mom_5m, macd_bull)
        if score < MIN_SCORE: return None

        action_data = get_action(score, rsi, gap, vol_spike, price, BUDGET)

        return dict(ticker=ticker, price=round(price,2), gap=round(gap,2),
                    rsi=rsi, volume=int(volume), vol_spike=round(vol_spike,1),
                    mom_5m=round(mom_5m,2), macd_bull=macd_bull,
                    bb_pct=bb_pct, score=score, **action_data)

    except Exception as e:
        log.warning(f"[{ticker}] {e}")
        return None


# ─────────────────────────────────────────────
#  בניית הודעה מסודרת
# ─────────────────────────────────────────────
def build_message(results: list, phase: str) -> str:
    phase_labels = {
        "morning":   "🌅 פתיחת שוק",
        "midday":    "☀️ צהריים",
        "afternoon": "🌆 אחה\"צ",
    }
    now_il = datetime.now(pytz.timezone("Asia/Jerusalem")).strftime("%H:%M")
    now_et = datetime.now(pytz.timezone("America/New_York")).strftime("%H:%M ET")

    strong = sum(1 for r in results if r["action"] == "STRONG_BUY")
    buys   = sum(1 for r in results if r["action"] == "BUY")
    watch  = sum(1 for r in results if r["action"] == "WATCH")

    msg = (
        f"<b>📊 דוח מסחר – Small Caps</b>\n"
        f"<i>{phase_labels.get(phase, phase)} | {now_il} 🇮🇱 | {now_et}</i>\n"
        f"<i>תקציב לעסקה: ${BUDGET} | מקס׳ {MAX_POSITIONS} פוזיציות</i>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"<b>סיכום:</b> 🚀{strong} חזקות  🟢{buys} קנייה  🟡{watch} מעקב\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, r in enumerate(results[:5], 1):
        stars = "⭐" * (1 + (r["score"] >= 70) + (r["score"] >= 80))
        msg += (
            f"<b>{r['emoji']} #{i}  {r['ticker']}</b>  {stars}  {r['score']}/100\n"
            f"<b>➤ {r['hebrew']}</b>\n"
            f"<i>💡 {r['reason']}</i>\n\n"

            f"  💰 מחיר:      <b>${r['price']}</b>\n"
            f"  📈 Gap:       <b>+{r['gap']}%</b>\n"
            f"  ⚡ RSI:       <b>{r['rsi']}</b>\n"
            f"  🔊 Vol:       <b>×{r['vol_spike']}</b>\n"
            f"  ⏱ Mom 5m:    <b>{r['mom_5m']:+.2f}%</b>\n"
            f"  {'📈' if r['macd_bull'] else '📉'} MACD: "
            f"{'Bullish ✓' if r['macd_bull'] else 'Bearish ✗'}\n\n"
        )

        if r["action"] in ("STRONG_BUY", "BUY", "WATCH") and r["shares"] > 0:
            tip = {
                "morning":   "⚠️ וודא נר ירוק ראשון לפני כניסה",
                "midday":    "⚠️ צהריים – חכה לנפח, היזהר מ-fakeout",
                "afternoon": "⚠️ קרוב לסגירה – צמצם יעד ל-10%",
            }.get(phase, "")

            msg += (
                f"  <b>🎯 תוכנית עסקה:</b>\n"
                f"  📍 כניסה מעל:  <b>${r['entry']}</b>\n"
                f"  🛒 כמות:       <b>{r['shares']} מניות</b>\n"
                f"  💵 השקעה:      <b>${r['invested']}</b>\n"
                f"  🎯 יעד:        <b>${r['target_price']}</b>"
                f"  → <b>+${r['potential']}</b>\n"
                f"  🛑 סטופ:       <b>${r['stop_price']}</b>"
                f"  → <b>-${r['risk_usd']}</b>\n"
                f"  ⚖️ R:R:        <b>1:{r['rr']}</b>"
                f"{'  ✅ מצוין' if r['rr'] >= 3 else ''}\n"
            )
            if tip:
                msg += f"  {tip}\n"

        elif r["action"] == "SELL_AVOID":
            msg += (
                "  <b>🔴 פעולה:</b>\n"
                "  • יש לך? → <b>מכור עכשיו</b>\n"
                "  • אין לך? → <b>אל תיכנס</b>\n"
            )
        else:
            msg += "  <b>⏳ פעולה: המתן, אין כניסה כרגע</b>\n"

        msg += "\n━━━━━━━━━━━━━━━━━━━\n\n"

    msg += (
        "<b>📌 כללי ברזל:</b>\n"
        f"  1️⃣ מקסימום {MAX_POSITIONS} פוזיציות בו-זמנית\n"
        "  2️⃣ סטופ לוס תמיד – ללא יוצא מן הכלל\n"
        "  3️⃣ הגעת ליעד? מכור חצי, הזז סטופ לכניסה\n"
        "  4️⃣ לא קנית תוך 10 דק' מהסיגנל? דלג\n\n"
        "<i>⚠️ מידע למחקר בלבד – לא ייעוץ השקעות</i>"
    )
    return msg


# ─────────────────────────────────────────────
#  שליחת טלגרם
# ─────────────────────────────────────────────
def send_telegram(msg: str) -> bool:
    if not TOKEN or not CHAT:
        log.error("חסרים TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=15,
        )
        time.sleep(0.4)
        return r.ok
    except Exception as e:
        log.error(f"טלגרם: {e}")
        return False


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    log.info("🤖 הבוט הופעל")
    phase = market_phase()
    log.info(f"שלב: {phase}")

    if not is_market_open():
        now_et = datetime.now(pytz.timezone("America/New_York")).strftime("%H:%M")
        send_telegram(
            f"⚠️ <b>השוק סגור</b> ({phase})\n"
            f"שעה בNY: {now_et}\n"
            "שעות פעילות: 16:30–23:00 🇮🇱"
        )
        return

    log.info(f"סורק {len(TICKERS)} מניות...")
    results = sorted(
        filter(None, (scan_stock(t) for t in TICKERS)),
        key=lambda x: x["score"], reverse=True,
    )

    if not results:
        send_telegram(
            "⚠️ <b>אין סיגנלים כרגע</b>\n"
            f"<i>נסרקו {len(TICKERS)} מניות – אף אחת לא עמדה בקריטריונים.</i>\n"
            "💡 הזמן הטוב: 16:35–17:30 🇮🇱"
        )
        return

    log.info(f"נמצאו {len(results)} סיגנלים")
    send_telegram(build_message(results, phase))
    log.info("✅ נשלח")


if __name__ == "__main__":
    main()
