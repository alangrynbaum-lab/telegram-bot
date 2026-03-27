import os
import logging
import finnhub
import requests
import numpy as np
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ── CONFIG ──
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
FINNHUB_KEY    = os.environ.get("FINNHUB_KEY")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

finnhub_client = finnhub.Client(api_key=FINNHUB_KEY)

# ── MI PORTFOLIO ──
MY_PORTFOLIO = {
    "SPY":  {"weight": "39.5%",  "dca": "$350/mes",  "target": "45%",   "verdict": "COMPRAR / Mantener DCA",           "score": 88, "gtc": None},
    "GLD":  {"weight": "16.35%", "dca": None,         "target": "~10%",  "verdict": "REDUCIR gradualmente",             "score": 62, "gtc": None},
    "ARKW": {"weight": "14.12%", "dca": None,         "target": "salir", "verdict": "VENDER en $148 (GTC activo)",      "score": 42, "gtc": "$148.00"},
    "VGT":  {"weight": "9.71%",  "dca": "$50/mes",   "target": "20%",   "verdict": "COMPRAR / Incrementar",            "score": 82, "gtc": None},
    "XLE":  {"weight": "9.04%",  "dca": None,         "target": "~5%",   "verdict": "REDUCIR gradualmente",             "score": 52, "gtc": None},
    "SCHD": {"weight": "6.21%",  "dca": "$100/mes",  "target": "15%",   "verdict": "COMPRAR / Incrementar",            "score": 80, "gtc": None},
    "MSTR": {"weight": "4.75%",  "dca": None,         "target": "hold",  "verdict": "MANTENER — no ampliar hasta $80K", "score": 55, "gtc": "$367.07"},
}

SUPPORT_RESIST = {
    "SPY":  {"s": 640,   "r": 680},
    "GLD":  {"s": 400,   "r": 450},
    "ARKW": {"s": 110,   "r": 148},
    "VGT":  {"s": 680,   "r": 807},
    "XLE":  {"s": 57,    "r": 65},
    "SCHD": {"s": 29.50, "r": 31.95},
    "MSTR": {"s": 126,   "r": 195},
}

# ── INDICADORES TÉCNICOS ──
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    closes = np.array(closes, dtype=float)
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 1)

def calc_ema(closes, period):
    if len(closes) < period:
        return None
    closes = np.array(closes, dtype=float)
    k = 2 / (period + 1)
    ema = np.mean(closes[:period])
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast   = calc_ema(closes, fast)
    ema_slow   = calc_ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    # Full MACD line series
    closes = np.array(closes, dtype=float)
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    ema_f  = np.mean(closes[:fast])
    ema_s  = np.mean(closes[:slow])
    macd_series = []
    for i in range(slow, len(closes)):
        ema_f = closes[i] * k_fast + ema_f * (1 - k_fast)
        ema_s = closes[i] * k_slow + ema_s * (1 - k_slow)
        macd_series.append(ema_f - ema_s)
    if len(macd_series) < signal:
        return None, None, None
    k_sig   = 2 / (signal + 1)
    sig_ema = np.mean(macd_series[:signal])
    for v in macd_series[signal:]:
        sig_ema = v * k_sig + sig_ema * (1 - k_sig)
    macd_val  = round(macd_series[-1], 3)
    signal_val= round(sig_ema, 3)
    hist_val  = round(macd_val - signal_val, 3)
    return macd_val, signal_val, hist_val

def get_candles(ticker, days=300):
    try:
        end   = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days)).timestamp())
        data  = finnhub_client.stock_candles(ticker, "D", start, end)
        if data and data.get("s") == "ok":
            return data.get("c", []), data.get("h", []), data.get("l", []), data.get("v", [])
        return [], [], [], []
    except Exception as e:
        logger.error(f"Candles error {ticker}: {e}")
        return [], [], [], []

# ── SEMÁFOROS ──
def sem_rsi(rsi):
    if rsi is None: return "⬜", "Sin datos"
    if rsi < 30:  return "🟢", f"Sobreventa ({rsi}) — posible rebote"
    if rsi < 45:  return "🟡", f"Bajista ({rsi})"
    if rsi < 55:  return "⬜", f"Neutro ({rsi})"
    if rsi < 70:  return "🟢", f"Alcista ({rsi})"
    return "🔴", f"Sobrecompra ({rsi}) — posible corrección"

def sem_macd(macd, signal, hist):
    if macd is None: return "⬜", "Sin datos"
    if macd > signal and hist > 0:
        return "🟢", f"Alcista (MACD {macd:+.2f} > señal {signal:.2f})"
    if macd < signal and hist < 0:
        return "🔴", f"Bajista (MACD {macd:+.2f} < señal {signal:.2f})"
    return "🟡", f"Cruce neutro (MACD {macd:+.2f} / señal {signal:.2f})"

def sem_ema200(price, ema200):
    if ema200 is None: return "⬜", "Sin datos"
    diff_pct = ((price - ema200) / ema200) * 100
    if price > ema200:
        return "🟢", f"Por encima EMA200 (${ema200:,.2f}) +{diff_pct:.1f}%"
    return "🔴", f"Por debajo EMA200 (${ema200:,.2f}) {diff_pct:.1f}%"

def tendencia(price, ema200, rsi, macd, signal):
    scores = {"corto": 0, "medio": 0, "largo": 0}
    # Corto plazo — RSI + MACD
    if rsi is not None:
        if rsi < 35:   scores["corto"] += 1
        elif rsi > 65: scores["corto"] -= 1
    if macd is not None and signal is not None:
        if macd > signal: scores["corto"] += 1
        else:             scores["corto"] -= 1
    # Mediano plazo — EMA200
    if ema200 is not None:
        if price > ema200: scores["medio"] += 1
        else:              scores["medio"] -= 1
        if macd is not None and signal is not None:
            if macd > signal: scores["medio"] += 1
            else:             scores["medio"] -= 1
    # Largo plazo — EMA200 principalmente
    if ema200 is not None:
        diff = ((price - ema200) / ema200) * 100
        if diff > 5:    scores["largo"] += 2
        elif diff > 0:  scores["largo"] += 1
        elif diff > -5: scores["largo"] -= 1
        else:           scores["largo"] -= 2

    def label(s):
        if s >= 2:  return "🟢 Alcista"
        if s == 1:  return "🟡 Levemente alcista"
        if s == 0:  return "⬜ Neutral"
        if s == -1: return "🟡 Levemente bajista"
        return "🔴 Bajista"

    return label(scores["corto"]), label(scores["medio"]), label(scores["largo"])

# ── HELPERS ──
def fmt(n, d=2):
    if n is None: return "N/D"
    try:    return f"{float(n):,.{d}f}"
    except: return "N/D"

def fmt_pct(n):
    if n is None: return "N/D"
    try:    return f"{float(n)*100:.1f}%"
    except: return "N/D"

def fmt_large(n):
    if n is None: return "N/D"
    try:
        n = float(n)
        if abs(n) >= 1e12: return f"${n/1e12:.2f}T"
        if abs(n) >= 1e9:  return f"${n/1e9:.2f}B"
        if abs(n) >= 1e6:  return f"${n/1e6:.1f}M"
        return f"${n:,.2f}"
    except: return "N/D"

def score_emoji(score):
    if score >= 75: return "🟢"
    if score >= 55: return "🟡"
    return "🔴"

def rate_pe(v):
    try:
        v = float(v)
        if v <= 0:  return "🟡"
        if v < 20:  return "🟢"
        if v < 40:  return "🟡"
        return "🔴"
    except: return "⬜"

def rate_roe(v):
    try:
        v = float(v)
        if v > 0.20:  return "🟢"
        if v > 0.10:  return "🟡"
        if v < 0:     return "🔴"
        return "🟡"
    except: return "⬜"

def rate_margin(v):
    try:
        v = float(v)
        if v > 0.20:  return "🟢"
        if v > 0.05:  return "🟡"
        return "🔴"
    except: return "⬜"

def rate_debt(v):
    try:
        v = float(v)
        if v < 0.5:  return "🟢"
        if v < 1.5:  return "🟡"
        return "🔴"
    except: return "⬜"

def rate_beta(v):
    try:
        v = float(v)
        if v < 0.8:  return "🟢"
        if v < 1.3:  return "🟡"
        return "🔴"
    except: return "⬜"

def rate_yield(v):
    try:
        v = float(v)
        if v > 0.03: return "🟢"
        if v > 0.01: return "🟡"
        return "⬜"
    except: return "⬜"

def check_alerts(ticker, price):
    lvl = SUPPORT_RESIST.get(ticker.upper())
    if not lvl: return ""
    alerts = []
    if price <= lvl["s"] * 1.02:
        alerts.append(f"⚠️ Cerca del soporte ${lvl['s']}")
    if price >= lvl["r"] * 0.98:
        alerts.append(f"🔔 Cerca de resistencia ${lvl['r']}")
    return "\n".join(alerts)

# ── BUILD MESSAGE ──
def build_message(ticker):
    ticker = ticker.upper().strip()

    # Quote
    try:
        q = finnhub_client.quote(ticker)
    except:
        q = None

    if not q or q.get("c", 0) == 0:
        return (
            f"❌ No encontré datos para `{ticker}`\n\n"
            f"Verificá que el ticker sea correcto.\n"
            f"Ejemplos: `SPY` `AAPL` `MELI` `BTC-USD` `GGAL.BA`"
        )

    price  = q.get("c", 0)
    change = q.get("d", 0)
    pct    = q.get("dp", 0)
    high_d = q.get("h", 0)
    low_d  = q.get("l", 0)
    prev   = q.get("pc", 0)
    sign   = "+" if change >= 0 else ""
    p_emoji= "📈" if change >= 0 else "📉"

    # Profile
    try:
        profile  = finnhub_client.company_profile2(symbol=ticker)
        name     = profile.get("name", ticker)
        industry = profile.get("finnhubIndustry", "")
        mktcap   = fmt_large((profile.get("marketCapitalization") or 0) * 1e6)
    except:
        name, industry, mktcap = ticker, "", "N/D"

    # Candles for technicals
    closes, highs, lows, vols = get_candles(ticker, days=300)

    rsi    = calc_rsi(closes) if len(closes) > 15 else None
    macd_v, macd_s, macd_h = calc_macd(closes) if len(closes) > 35 else (None, None, None)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else None
    ema50  = calc_ema(closes, 50)  if len(closes) >= 50  else None

    # Semáforos técnicos
    rsi_sem,   rsi_desc   = sem_rsi(rsi)
    macd_sem,  macd_desc  = sem_macd(macd_v, macd_s, macd_h)
    ema_sem,   ema_desc   = sem_ema200(price, ema200)

    # Tendencias
    t_corto, t_medio, t_largo = tendencia(price, ema200, rsi, macd_v, macd_s)

    # Fundamentals
    try:
        fund    = finnhub_client.company_basic_financials(ticker, "all")
        metrics = fund.get("metric", {})
    except:
        metrics = {}

    pe        = metrics.get("peNormalizedAnnual") or metrics.get("peTTM")
    roe       = metrics.get("roeTTM")
    margin    = metrics.get("netProfitMarginTTM")
    beta      = metrics.get("beta")
    div_yield = metrics.get("dividendYieldIndicatedAnnual")
    debt_eq   = metrics.get("totalDebt/totalEquityAnnual")
    eps       = metrics.get("epsTTM") or metrics.get("epsNormalizedAnnual")
    rev_gr    = metrics.get("revenueGrowthTTMYoy")
    h52       = metrics.get("52WeekHigh")
    l52       = metrics.get("52WeekLow")

    # Analyst
    try:
        pt  = finnhub_client.price_target(ticker)
    except:
        pt = None
    try:
        rec = finnhub_client.recommendation_trends(ticker)
        rec = rec[0] if rec else None
    except:
        rec = None

    # News
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        news     = finnhub_client.company_news(ticker, _from=week_ago, to=today)
        news     = news[:3] if news else []
    except:
        news = []

    # Portfolio
    portfolio = MY_PORTFOLIO.get(ticker)
    alerts    = check_alerts(ticker, price)

    # ── COMPOSE ──
    msg = f"{p_emoji} *{ticker}*"
    if name != ticker:
        msg += f" — {name}"
    msg += "\n"
    if industry:
        msg += f"_{industry}_\n"
    msg += "\n"

    # Precio
    msg += f"*Precio:* ${fmt(price)} ({sign}{fmt(pct)}%)\n"
    msg += f"*Hoy:* Máx ${fmt(high_d)} / Mín ${fmt(low_d)}\n"
    msg += f"*Cierre anterior:* ${fmt(prev)}\n"
    if h52 and l52:
        msg += f"*52 semanas:* ${fmt(l52)} — ${fmt(h52)}\n"
    if mktcap != "N/D":
        msg += f"*Market cap:* {mktcap}\n"

    # Alertas soporte/resistencia
    if alerts:
        msg += f"\n{alerts}\n"

    # Técnico
    msg += f"\n📊 *Análisis técnico*\n"
    msg += f"{rsi_sem} *RSI (14):* {rsi_desc}\n"
    msg += f"{macd_sem} *MACD:* {macd_desc}\n"
    msg += f"{ema_sem} *EMA 200:* {ema_desc}\n"
    if ema50:
        ema50_sem = "🟢" if price > ema50 else "🔴"
        msg += f"{ema50_sem} *EMA 50:* ${fmt(ema50)} — precio {'encima ✓' if price > ema50 else 'debajo ✗'}\n"

    # Tendencias
    msg += f"\n📅 *Tendencia*\n"
    msg += f"Corto plazo: {t_corto}\n"
    msg += f"Mediano plazo: {t_medio}\n"
    msg += f"Largo plazo: {t_largo}\n"

    # Fundamentales
    msg += f"\n📈 *Fundamentales*\n"
    if pe:
        msg += f"{rate_pe(pe)} P/E: {fmt(pe)}x\n"
    if eps:
        msg += f"💹 EPS: ${fmt(eps)}\n"
    if roe:
        msg += f"{rate_roe(roe)} ROE: {fmt_pct(roe)}\n"
    if margin:
        msg += f"{rate_margin(margin)} Margen neto: {fmt_pct(margin)}\n"
    if beta:
        msg += f"{rate_beta(beta)} Beta: {fmt(beta)}\n"
    if div_yield and float(div_yield or 0) > 0:
        msg += f"{rate_yield(div_yield)} Yield: {fmt_pct(div_yield)}\n"
    if debt_eq:
        msg += f"{rate_debt(debt_eq)} Deuda/Equity: {fmt(debt_eq)}x\n"
    if rev_gr:
        g_e = "🟢" if float(rev_gr) > 0 else "🔴"
        msg += f"{g_e} Revenue growth: {fmt_pct(rev_gr)}\n"

    # Analistas
    if pt and pt.get("targetMean"):
        upside   = ((pt["targetMean"] - price) / price) * 100
        up_sign  = "+" if upside >= 0 else ""
        msg += f"\n🎯 *Analistas*\n"
        msg += f"PT promedio: ${fmt(pt['targetMean'])} ({up_sign}{upside:.1f}%)\n"
        if pt.get("targetHigh") and pt.get("targetLow"):
            msg += f"Rango: ${fmt(pt['targetLow'])} — ${fmt(pt['targetHigh'])}\n"
    if rec:
        total   = (rec.get("strongBuy",0)+rec.get("buy",0)+rec.get("hold",0)+rec.get("sell",0)+rec.get("strongSell",0)) or 1
        buy_pct = ((rec.get("strongBuy",0)+rec.get("buy",0))/total)*100
        msg += f"📊 Recomendación: {buy_pct:.0f}% compra · {rec.get('hold',0)} hold · {rec.get('sell',0)+rec.get('strongSell',0)} venta\n"

    # Portfolio
    if portfolio:
        msg += f"\n💼 *Mi posición*\n"
        msg += f"Peso: {portfolio['weight']} del portfolio\n"
        if portfolio["dca"]:
            msg += f"DCA: {portfolio['dca']}\n"
        msg += f"Target: {portfolio['target']}\n"
        if portfolio["gtc"]:
            msg += f"⬆️ GTC SELL activo: {portfolio['gtc']}\n"
        msg += f"\n{score_emoji(portfolio['score'])} *Veredicto:* {portfolio['verdict']}\n"
        msg += f"Score: {portfolio['score']}/100\n"

    # Noticias
    if news:
        msg += f"\n📰 *Noticias recientes*\n"
        for n in news:
            headline = (n.get("headline") or "")[:75]
            source   = n.get("source", "")
            msg += f"• {headline} — _{source}_\n"

    msg += f"\n_Datos vía Finnhub · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    return msg

def build_portfolio_summary():
    msg  = "💼 *Grynbaum Capital — Portfolio IBKR*\n"
    msg += f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    msg += f"Total invertido: ~$7,650 | P&G: \\-3.0%\n"
    msg += f"DCA mensual: $500\n\n"
    for ticker, ctx in MY_PORTFOLIO.items():
        try:
            q = finnhub_client.quote(ticker)
            if q and q.get("c", 0) > 0:
                price = q.get("c", 0)
                pct   = q.get("dp", 0)
                sign  = "+" if pct >= 0 else ""
                arrow = "📈" if pct >= 0 else "📉"
                sem   = score_emoji(ctx["score"])
                msg  += f"{sem} *{ticker}* ${fmt(price)} ({sign}{fmt(pct)}%) — {ctx['weight']}\n"
            else:
                msg += f"⬜ *{ticker}* — Sin datos\n"
        except:
            msg += f"⬜ *{ticker}* — Error\n"
    msg += "\n_Mandá /TICKER para análisis completo_"
    return msg

def build_btc_message():
    msg = "₿ *Bitcoin — BTC/USD*\n\n"
    try:
        q = finnhub_client.quote("BINANCE:BTCUSDT")
        if not q or q.get("c", 0) == 0:
            q = finnhub_client.quote("BTC-USD")
    except:
        q = None

    if q and q.get("c", 0) > 0:
        price  = q.get("c", 0)
        change = q.get("d", 0)
        pct    = q.get("dp", 0)
        high_d = q.get("h", 0)
        low_d  = q.get("l", 0)
        sign   = "+" if change >= 0 else ""
        arrow  = "📈" if change >= 0 else "📉"
        msg += f"{arrow} *Precio:* ${fmt(price, 0)}\n"
        msg += f"Cambio: {sign}${fmt(abs(change), 0)} ({sign}{fmt(pct)}%)\n"
        msg += f"Hoy: Máx ${fmt(high_d, 0)} / Mín ${fmt(low_d, 0)}\n\n"
        if price > 80000:
            msg += "🟢 Por encima del costo promedio de MSTR ($75,696)\n"
            msg += "✅ Zona favorable para no ampliar MSTR\n"
        elif price > 60000:
            msg += "🟡 Por debajo del costo promedio de MSTR ($75,696)\n"
            msg += "⚠️ MSTR en pérdida no realizada\n"
        else:
            msg += "🔴 Zona de riesgo para MSTR\n"
            msg += "❌ BTC muy por debajo del costo promedio\n"
    else:
        msg += "No se pudo obtener el precio de BTC.\n"

    msg += f"\n💼 *Mi posición BTC*\n"
    msg += f"DCA: $100/mes en Binance\n"
    msg += f"Emergency fund: $3,400 (banco + Binance Earn)\n"
    msg += f"Exposición indirecta vía MSTR: 4.75% del portfolio\n"
    msg += f"Costo promedio MSTR: $75,696/BTC\n"
    msg += f"\n_Datos vía Finnhub · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    return msg

# ── HANDLERS ──
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Grynbaum Capital Bot*\n\n"
        "📊 `/portfolio` — Resumen de tu portfolio\n"
        "₿ `/btc` — Bitcoin + tu posición\n"
        "🔍 `/TICKER` — Análisis completo de cualquier ticker\n\n"
        "*Tu portfolio:*\n"
        "`/SPY` `/GLD` `/ARKW` `/VGT` `/XLE` `/SCHD` `/MSTR`\n\n"
        "*Otros tickers:*\n"
        "`/AAPL` `/NVDA` `/MELI` `/TSLA` `/COIN`\n"
        "`/BTC-USD` `/ETH-USD`\n"
        "`/GGAL.BA` `/PAMP.BA` `/YPF`\n\n"
        "*Cada análisis incluye:*\n"
        "• Precio, máx/mín del día, variación\n"
        "• RSI, MACD, EMA50, EMA200 con semáforos\n"
        "• Tendencia corto / mediano / largo plazo\n"
        "• Fundamentales con semáforos\n"
        "• Recomendación de analistas\n"
        "• Noticias recientes\n"
        "• Tu posición y veredicto (si es del portfolio)\n\n"
        "🟢 positivo  🟡 neutro  🔴 negativo  ⬜ sin datos"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando portfolio…")
    msg = build_portfolio_summary()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def btc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando BTC…")
    msg = build_btc_message()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.split()[0].lstrip("/").upper()
    if command in ["START", "HELP", "PORTFOLIO", "BTC"]:
        return
    await update.message.reply_text(f"⏳ Analizando {command}…")
    msg = build_message(command)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text and len(text) <= 12 and text.replace("-","").replace(".","").replace("^","").replace(":","").isalnum():
        await update.message.reply_text(f"⏳ Analizando {text}…")
        msg = build_message(text)
        await update.message.reply_text(msg, parse_mode="Markdown")

# ── MAIN ──
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",     start_cmd))
    app.add_handler(CommandHandler("help",      start_cmd))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("btc",       btc_cmd))
    app.add_handler(MessageHandler(filters.COMMAND, ticker_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    logger.info("Bot iniciado ✓")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
