import os
import logging
import finnhub
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ── CONFIG ──
TELEGRAM_TOKEN = os.environ.get("8338839356:AAECjh5gK4onj89C24feVuAfmeFrb_z8Ry8")
FINNHUB_KEY    = os.environ.get("d72ndvpr01qlfd9nsq1gd72ndvpr01qlfd9nsq20")
ALLOWED_USER   = os.environ.get("ALLOWED_USER_ID")  # tu Telegram user ID (opcional, para privacidad)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

finnhub_client = finnhub.Client(api_key=d72ndvpr01qlfd9nsq1gd72ndvpr01qlfd9nsq20)

# ── MI PORTFOLIO ──
MY_PORTFOLIO = {
    "SPY":  {"weight": "39.5%", "dca": "$350/mes",  "target": "45%",   "verdict": "COMPRAR / Mantener DCA",            "score": 88, "gtc": None},
    "GLD":  {"weight": "16.35%","dca": None,         "target": "~10%",  "verdict": "REDUCIR gradualmente",              "score": 62, "gtc": None},
    "ARKW": {"weight": "14.12%","dca": None,         "target": "salir", "verdict": "VENDER en $148 (GTC activo)",       "score": 42, "gtc": "$148.00"},
    "VGT":  {"weight": "9.71%", "dca": "$50/mes",   "target": "20%",   "verdict": "COMPRAR / Incrementar",             "score": 82, "gtc": None},
    "XLE":  {"weight": "9.04%", "dca": None,         "target": "~5%",   "verdict": "REDUCIR gradualmente",              "score": 52, "gtc": None},
    "SCHD": {"weight": "6.21%", "dca": "$100/mes",  "target": "15%",   "verdict": "COMPRAR / Incrementar",             "score": 80, "gtc": None},
    "MSTR": {"weight": "4.75%", "dca": None,         "target": "hold",  "verdict": "MANTENER — no ampliar hasta $80K",  "score": 55, "gtc": "$367.07"},
}

SUPPORT_RESIST = {
    "SPY":  {"s": 640,    "r": 680},
    "GLD":  {"s": 400,    "r": 450},
    "ARKW": {"s": 110,    "r": 148},
    "VGT":  {"s": 680,    "r": 807},
    "XLE":  {"s": 57,     "r": 65},
    "SCHD": {"s": 29.50,  "r": 31.95},
    "MSTR": {"s": 126,    "r": 195},
}

# ── HELPERS ──
def score_to_emoji(score):
    if score >= 75: return "🟢"
    if score >= 55: return "🟡"
    return "🔴"

def change_emoji(pct):
    if pct >= 0: return "📈"
    return "📉"

def fmt_num(n, decimals=2):
    if n is None: return "N/D"
    try:
        return f"{float(n):,.{decimals}f}"
    except:
        return "N/D"

def fmt_pct(n):
    if n is None: return "N/D"
    try:
        return f"{float(n)*100:.1f}%"
    except:
        return "N/D"

def fmt_large(n):
    if n is None: return "N/D"
    try:
        n = float(n)
        if abs(n) >= 1e12: return f"${n/1e12:.2f}T"
        if abs(n) >= 1e9:  return f"${n/1e9:.2f}B"
        if abs(n) >= 1e6:  return f"${n/1e6:.1f}M"
        return f"${n:,.2f}"
    except:
        return "N/D"

def check_alerts(ticker, price):
    alerts = []
    lvl = SUPPORT_RESIST.get(ticker.upper())
    if not lvl:
        return ""
    if price <= lvl["s"] * 1.02:
        alerts.append(f"⚠️ Cerca del soporte ${lvl['s']}")
    if price >= lvl["r"] * 0.98:
        alerts.append(f"🔔 Cerca de resistencia ${lvl['r']}")
    return "\n".join(alerts)

def rate_metric(label, value):
    try:
        v = float(value)
    except:
        return "⬜"
    if label == "pe":
        if v <= 0: return "🟡"
        if v < 20: return "🟢"
        if v < 40: return "🟡"
        return "🔴"
    if label == "roe":
        if v > 0.20: return "🟢"
        if v > 0.10: return "🟡"
        if v < 0:    return "🔴"
        return "🟡"
    if label == "margin":
        if v > 0.20: return "🟢"
        if v > 0.05: return "🟡"
        return "🔴"
    if label == "debt":
        if v < 0.5:  return "🟢"
        if v < 1.5:  return "🟡"
        return "🔴"
    if label == "beta":
        if v < 0.8:  return "🟢"
        if v < 1.3:  return "🟡"
        return "🔴"
    if label == "yield":
        if v > 0.03: return "🟢"
        if v > 0.01: return "🟡"
        return "⬜"
    return "⬜"

# ── FETCH DATA ──
def get_quote(ticker):
    try:
        q = finnhub_client.quote(ticker)
        return q
    except Exception as e:
        logger.error(f"Quote error {ticker}: {e}")
        return None

def get_fundamentals(ticker):
    try:
        data = finnhub_client.company_basic_financials(ticker, "all")
        return data
    except Exception as e:
        logger.error(f"Fundamentals error {ticker}: {e}")
        return None

def get_profile(ticker):
    try:
        return finnhub_client.company_profile2(symbol=ticker)
    except Exception as e:
        logger.error(f"Profile error {ticker}: {e}")
        return None

def get_recommendation(ticker):
    try:
        recs = finnhub_client.recommendation_trends(ticker)
        if recs:
            return recs[0]
        return None
    except Exception as e:
        logger.error(f"Recommendation error {ticker}: {e}")
        return None

def get_price_target(ticker):
    try:
        return finnhub_client.price_target(ticker)
    except Exception as e:
        logger.error(f"Price target error {ticker}: {e}")
        return None

def get_news(ticker):
    try:
        from datetime import timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        news = finnhub_client.company_news(ticker, _from=week_ago, to=today)
        return news[:3] if news else []
    except Exception as e:
        logger.error(f"News error {ticker}: {e}")
        return []

def get_btc_price():
    try:
        q = finnhub_client.quote("BINANCE:BTCUSDT")
        return q
    except:
        try:
            q = finnhub_client.quote("BTC-USD") 
            return q
        except:
            return None

# ── BUILD MESSAGE ──
def build_ticker_message(ticker):
    ticker = ticker.upper().strip()

    # Quote
    q = get_quote(ticker)
    if not q or q.get("c", 0) == 0:
        return f"❌ No encontré datos para `{ticker}`.\n\nVerificá que el ticker sea correcto. Para tickers argentinos usá el formato `GGAL.BA`, `YPF`, `^MERV`."

    price    = q.get("c", 0)
    prev     = q.get("pc", 0)
    change   = q.get("d", 0)
    pct      = q.get("dp", 0)
    high     = q.get("h", 0)
    low      = q.get("l", 0)
    high52   = q.get("52WeekHigh") or 0
    low52    = q.get("52WeekLow") or 0

    sign = "+" if change >= 0 else ""
    emoji = change_emoji(pct)

    # Profile
    profile = get_profile(ticker)
    name = profile.get("name", ticker) if profile else ticker
    industry = profile.get("finnhubIndustry", "") if profile else ""
    mktcap = fmt_large(profile.get("marketCapitalization", 0) * 1e6) if profile else "N/D"

    # Fundamentals
    fund = get_fundamentals(ticker)
    metrics = fund.get("metric", {}) if fund else {}

    pe        = metrics.get("peNormalizedAnnual") or metrics.get("peTTM")
    roe       = metrics.get("roeTTM")
    margin    = metrics.get("netProfitMarginTTM")
    beta      = metrics.get("beta")
    div_yield = metrics.get("dividendYieldIndicatedAnnual")
    debt_eq   = metrics.get("totalDebt/totalEquityAnnual")
    eps       = metrics.get("epsTTM") or metrics.get("epsNormalizedAnnual")
    rev_growth= metrics.get("revenueGrowthTTMYoy")
    h52       = metrics.get("52WeekHigh") or high52
    l52       = metrics.get("52WeekLow")  or low52

    # Analyst
    rec = get_recommendation(ticker)
    pt  = get_price_target(ticker)

    # Portfolio context
    portfolio = MY_PORTFOLIO.get(ticker)
    alerts = check_alerts(ticker, price)

    # ── COMPOSE MESSAGE ──
    msg = f"{emoji} *{ticker} — {name}*\n"
    if industry:
        msg += f"_{industry}_\n"
    msg += "\n"

    # Price block
    msg += f"💵 *Precio:* ${fmt_num(price)} ({sign}{fmt_num(pct, 2)}%)\n"
    msg += f"📊 Hoy: ${fmt_num(low)} — ${fmt_num(high)}\n"
    if h52 and l52:
        msg += f"📅 52W:  ${fmt_num(l52)} — ${fmt_num(h52)}\n"
    msg += f"🏢 Market cap: {mktcap}\n"

    # Alerts
    if alerts:
        msg += f"\n{alerts}\n"

    # Fundamentals
    msg += "\n📈 *Fundamentales*\n"
    if pe:
        msg += f"{rate_metric('pe', pe)} P/E: {fmt_num(pe)}x\n"
    if eps:
        msg += f"💹 EPS: ${fmt_num(eps)}\n"
    if roe:
        msg += f"{rate_metric('roe', roe)} ROE: {fmt_pct(roe)}\n"
    if margin:
        msg += f"{rate_metric('margin', margin)} Margen neto: {fmt_pct(margin)}\n"
    if beta:
        msg += f"{rate_metric('beta', beta)} Beta: {fmt_num(beta)}\n"
    if div_yield and float(div_yield) > 0:
        msg += f"{rate_metric('yield', div_yield)} Dividend yield: {fmt_pct(div_yield)}\n"
    if debt_eq:
        msg += f"{rate_metric('debt', debt_eq)} Deuda/Equity: {fmt_num(debt_eq)}x\n"
    if rev_growth:
        g_emoji = "🟢" if float(rev_growth) > 0 else "🔴"
        msg += f"{g_emoji} Revenue growth: {fmt_pct(rev_growth)}\n"

    # Analyst
    if pt and pt.get("targetMean"):
        upside = ((pt["targetMean"] - price) / price) * 100
        up_sign = "+" if upside >= 0 else ""
        msg += f"\n🎯 *Analistas*\n"
        msg += f"PT promedio: ${fmt_num(pt['targetMean'])} ({up_sign}{upside:.1f}% upside)\n"
        msg += f"Rango: ${fmt_num(pt.get('targetLow'))} — ${fmt_num(pt.get('targetHigh'))}\n"
    if rec:
        total = (rec.get("strongBuy",0) + rec.get("buy",0) + rec.get("hold",0) + rec.get("sell",0) + rec.get("strongSell",0)) or 1
        buy_pct = ((rec.get("strongBuy",0) + rec.get("buy",0)) / total) * 100
        msg += f"📊 Recomendación: {buy_pct:.0f}% compra · {rec.get('hold',0)} hold · {rec.get('sell',0)+rec.get('strongSell',0)} venta\n"

    # My portfolio position
    if portfolio:
        msg += f"\n💼 *Mi posición*\n"
        msg += f"Peso: {portfolio['weight']} del portfolio\n"
        if portfolio["dca"]:
            msg += f"DCA: {portfolio['dca']}\n"
        msg += f"Target: {portfolio['target']}\n"
        if portfolio["gtc"]:
            msg += f"⬆️ GTC SELL activo: {portfolio['gtc']}\n"
        msg += f"\n{score_to_emoji(portfolio['score'])} *Veredicto:* {portfolio['verdict']}\n"
        msg += f"Score: {portfolio['score']}/100\n"

    # News
    news = get_news(ticker)
    if news:
        msg += f"\n📰 *Noticias recientes*\n"
        for n in news:
            headline = n.get("headline", "")[:80]
            source   = n.get("source", "")
            msg += f"• {headline} _{source}_\n"

    msg += f"\n_Datos vía Finnhub · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"

    return msg

def build_portfolio_summary():
    msg = "💼 *Grynbaum Capital — Portfolio IBKR*\n"
    msg += f"_Actualizado {datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    msg += f"Total invertido: ~$7,650 | P&G: -3.0%\n"
    msg += f"DCA mensual: $500\n\n"

    for ticker, ctx in MY_PORTFOLIO.items():
        q = get_quote(ticker)
        if not q or q.get("c", 0) == 0:
            msg += f"• *{ticker}* — Error al cargar\n"
            continue
        price = q.get("c", 0)
        pct   = q.get("dp", 0)
        sign  = "+" if pct >= 0 else ""
        emoji = "📈" if pct >= 0 else "📉"
        score_e = score_to_emoji(ctx["score"])
        msg += f"{score_e} *{ticker}* ${fmt_num(price)} ({sign}{fmt_num(pct)}%) — {ctx['weight']}\n"

    msg += "\n_Mandá /TICKER para análisis completo_"
    return msg

def build_btc_message():
    q = get_btc_price()
    msg = "₿ *Bitcoin — BTC/USD*\n\n"
    if q and q.get("c", 0) > 0:
        price  = q.get("c", 0)
        change = q.get("d", 0)
        pct    = q.get("dp", 0)
        sign   = "+" if change >= 0 else ""
        emoji  = "📈" if change >= 0 else "📉"
        msg += f"{emoji} Precio: ${fmt_num(price, 0)}\n"
        msg += f"Cambio: {sign}${fmt_num(abs(change), 0)} ({sign}{fmt_num(pct)}%)\n\n"

        # Semáforo vs MSTR avg cost
        if price > 80000:
            msg += "🟢 Por encima del costo promedio de MSTR ($75,696)\n"
        elif price > 60000:
            msg += "🟡 Por debajo del costo promedio de MSTR ($75,696)\n"
        else:
            msg += "🔴 Zona de riesgo para MSTR\n"
    else:
        msg += "No se pudo obtener el precio de BTC en este momento.\n"

    msg += f"\n💼 *Mi posición BTC*\n"
    msg += f"DCA: $100/mes en Binance\n"
    msg += f"Emergency fund: $3,400 (banco + Binance Earn)\n"
    msg += f"Exposición indirecta: MSTR (4.75% portfolio IBKR)\n"
    msg += f"\n_Datos vía Finnhub · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    return msg

# ── HANDLERS ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Grynbaum Capital Bot*\n\n"
        "Comandos disponibles:\n\n"
        "📊 `/portfolio` — Resumen de tu portfolio\n"
        "₿ `/btc` — Estado de Bitcoin\n"
        "🔍 `/TICKER` — Análisis de cualquier ticker\n\n"
        "*Ejemplos:*\n"
        "`/SPY` `/GLD` `/ARKW` `/VGT`\n"
        "`/AAPL` `/NVDA` `/MELI`\n"
        "`/BTC-USD` `/ETH-USD`\n\n"
        "*Tickers argentinos:*\n"
        "`/GGAL.BA` `/YPF` `/PAMP.BA`\n"
        "Para el Merval: `/^MERV`\n\n"
        "🟢 = positivo  🟡 = neutro  🔴 = negativo"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando portfolio…")
    msg = build_portfolio_summary()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def btc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando datos de BTC…")
    msg = build_btc_message()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Extraer el ticker del comando (ej: /SPY → SPY)
    command = update.message.text.split()[0].lstrip("/")
    ticker  = command.upper()

    # Ignorar comandos reservados
    if ticker in ["START", "HELP", "PORTFOLIO", "BTC"]:
        return

    await update.message.reply_text(f"⏳ Analizando {ticker}…")
    msg = build_ticker_message(ticker)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    # Si el usuario manda el ticker sin / también funciona
    if text and len(text) <= 12 and text.replace("-","").replace(".","").replace("^","").isalnum():
        await update.message.reply_text(f"⏳ Analizando {text}…")
        msg = build_ticker_message(text)
        await update.message.reply_text(msg, parse_mode="Markdown")

# ── MAIN ──
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      start))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("btc",       btc_cmd))

    # Handler genérico para cualquier /TICKER
    app.add_handler(MessageHandler(filters.COMMAND, ticker_cmd))

    # Handler para texto sin / (opcional)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot iniciado ✓")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
