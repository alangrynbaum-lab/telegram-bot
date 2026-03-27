import os
import logging
import finnhub
import requests
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ── CONFIG ──
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
FINNHUB_KEY    = os.environ.get("FINNHUB_KEY")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
finnhub_client = finnhub.Client(api_key=FINNHUB_KEY)

# ── PORTFOLIO ──
MY_PORTFOLIO = {
    "SPY":  {"weight":"39.5%",  "dca":"$350/mes", "target":"45%",   "verdict":"COMPRAR / Mantener DCA",           "score":88, "gtc":None},
    "GLD":  {"weight":"16.35%", "dca":None,        "target":"~10%",  "verdict":"REDUCIR gradualmente",             "score":62, "gtc":None},
    "ARKW": {"weight":"14.12%", "dca":None,        "target":"salir", "verdict":"VENDER en $148 (GTC activo)",      "score":42, "gtc":"$148.00"},
    "VGT":  {"weight":"9.71%",  "dca":"$50/mes",  "target":"20%",   "verdict":"COMPRAR / Incrementar",            "score":82, "gtc":None},
    "XLE":  {"weight":"9.04%",  "dca":None,        "target":"~5%",   "verdict":"REDUCIR gradualmente",             "score":52, "gtc":None},
    "SCHD": {"weight":"6.21%",  "dca":"$100/mes", "target":"15%",   "verdict":"COMPRAR / Incrementar",            "score":80, "gtc":None},
    "MSTR": {"weight":"4.75%",  "dca":None,        "target":"hold",  "verdict":"MANTENER — no ampliar hasta $80K", "score":55, "gtc":"$367.07"},
}

SUPPORT_RESIST = {
    "SPY":  {"s":640,   "r":680},
    "GLD":  {"s":400,   "r":450},
    "ARKW": {"s":110,   "r":148},
    "VGT":  {"s":680,   "r":807},
    "XLE":  {"s":57,    "r":65},
    "SCHD": {"s":29.50, "r":31.95},
    "MSTR": {"s":126,   "r":195},
}

# Tickers argentinos conocidos → usar Yahoo siempre
ARG_TICKERS = {
    "GGAL","GGAL.BA","PAMP","PAMP.BA","YPF","YPFD.BA","BBAR","BBAR.BA",
    "BMA","BMA.BA","TXAR","TXAR.BA","LOMA","LOMA.BA","CEPU","CEPU.BA",
    "TECO2","TECO2.BA","SUPV","SUPV.BA","CRES","CRES.BA","EDN","EDN.BA",
    "COME","COME.BA","IRSA","IRSA.BA","BYMA","BYMA.BA","HARG","HARG.BA",
    "AMZND.BA","AAPLD.BA","MSFTD.BA","GOOGLD.BA","METAD.BA","NVDAD.BA",
    "^MERV","MERVAL",
}

# ETFs que Finnhub no tiene velas históricas — usar Yahoo para candles
ETF_USE_YAHOO = {
    "SPY","GLD","ARKW","VGT","XLE","SCHD","QQQ","IWM","TLT","GDX",
    "SLV","DIA","XLF","XLK","XLE","ARKK","ARKG","ARKF",
}

# ── YAHOO HELPERS ──
def yf_ticker(ticker):
    """Normaliza el ticker para Yahoo Finance."""
    t = ticker.upper()
    if t == "MERVAL" or t == "^MERV":
        return "^MERV"
    return t

def get_yf_data(ticker, period="1y"):
    """Obtiene datos históricos de Yahoo Finance."""
    try:
        t  = yf_ticker(ticker)
        df = yf.download(t, period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        return df
    except Exception as e:
        logger.error(f"YF data error {ticker}: {e}")
        return None

def get_yf_quote(ticker):
    """Obtiene cotización actual de Yahoo Finance."""
    try:
        t    = yf_ticker(ticker)
        info = yf.Ticker(t).fast_info
        return {
            "c":  float(info.last_price or 0),
            "h":  float(info.day_high or 0),
            "l":  float(info.day_low or 0),
            "pc": float(info.previous_close or 0),
            "v":  float(info.three_month_average_volume or 0),
        }
    except Exception as e:
        logger.error(f"YF quote error {ticker}: {e}")
        return None

def get_yf_info(ticker):
    """Obtiene info completa de Yahoo Finance (fundamentales, nombre, etc)."""
    try:
        t    = yf_ticker(ticker)
        info = yf.Ticker(t).info
        return info
    except Exception as e:
        logger.error(f"YF info error {ticker}: {e}")
        return {}

# ── INDICADORES TÉCNICOS ──
def calc_rsi(closes, period=14):
    closes = np.array(closes, dtype=float)
    if len(closes) < period + 2:
        return None
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g  = np.mean(gains[:period])
    avg_l  = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)

def calc_ema(closes, period):
    closes = np.array(closes, dtype=float)
    if len(closes) < period:
        return None
    k   = 2 / (period + 1)
    ema = float(np.mean(closes[:period]))
    for p in closes[period:]:
        ema = float(p) * k + ema * (1 - k)
    return round(ema, 2)

def calc_macd(closes, fast=12, slow=26, signal=9):
    closes = np.array(closes, dtype=float)
    if len(closes) < slow + signal + 5:
        return None, None, None
    k_f = 2 / (fast + 1)
    k_s = 2 / (slow + 1)
    ef  = float(np.mean(closes[:fast]))
    es  = float(np.mean(closes[:slow]))
    macd_line = []
    for i in range(slow, len(closes)):
        ef = float(closes[i]) * k_f + ef * (1 - k_f)
        es = float(closes[i]) * k_s + es * (1 - k_s)
        macd_line.append(ef - es)
    if len(macd_line) < signal + 2:
        return None, None, None
    k_sig = 2 / (signal + 1)
    sig   = float(np.mean(macd_line[:signal]))
    for v in macd_line[signal:]:
        sig = v * k_sig + sig * (1 - k_sig)
    mv = round(macd_line[-1], 3)
    sv = round(sig, 3)
    return mv, sv, round(mv - sv, 3)

def get_candles_for_analysis(ticker):
    """Obtiene velas históricas. Usa Yahoo para ETFs y ARG, Finnhub para el resto."""
    t = ticker.upper()
    use_yahoo = t in ETF_USE_YAHOO or t in ARG_TICKERS or t.endswith(".BA") or t.startswith("^")

    if use_yahoo:
        df = get_yf_data(t, period="2y")
        if df is not None and not df.empty:
            closes = df["Close"].dropna().tolist()
            volumes= df["Volume"].dropna().tolist()
            # Aplanar si viene como lista de listas (multi-index)
            closes  = [float(c[0]) if hasattr(c, '__len__') else float(c) for c in closes]
            volumes = [float(v[0]) if hasattr(v, '__len__') else float(v) for v in volumes]
            return closes, volumes
        return [], []
    else:
        try:
            end   = int(datetime.now().timestamp())
            start = int((datetime.now() - timedelta(days=730)).timestamp())
            data  = finnhub_client.stock_candles(t, "D", start, end)
            if data and data.get("s") == "ok":
                return data.get("c", []), data.get("v", [])
        except Exception as e:
            logger.error(f"Finnhub candles error {t}: {e}")
        # Fallback a Yahoo
        df = get_yf_data(t, period="2y")
        if df is not None and not df.empty:
            closes  = [float(c) for c in df["Close"].dropna().tolist()]
            volumes = [float(v) for v in df["Volume"].dropna().tolist()]
            return closes, volumes
        return [], []

# ── SEMÁFOROS ──
def sem_rsi(rsi):
    if rsi is None: return "⬜", "Sin datos"
    if rsi < 30:  return "🟢", f"{rsi} — Sobreventa (posible rebote)"
    if rsi < 45:  return "🟡", f"{rsi} — Zona bajista"
    if rsi < 55:  return "⬜", f"{rsi} — Neutro"
    if rsi < 70:  return "🟢", f"{rsi} — Zona alcista"
    return "🔴", f"{rsi} — Sobrecompra (posible corrección)"

def sem_macd(m, s, h):
    if m is None: return "⬜", "Sin datos"
    if m > s and h > 0: return "🟢", f"Alcista (MACD {m:+.2f} > señal {s:.2f})"
    if m < s and h < 0: return "🔴", f"Bajista (MACD {m:+.2f} < señal {s:.2f})"
    return "🟡", f"Cruce (MACD {m:+.2f} / señal {s:.2f})"

def sem_ema(price, ema, label):
    if ema is None: return "⬜", f"Sin datos"
    diff = ((price - ema) / ema) * 100
    s    = "+" if diff >= 0 else ""
    if price > ema: return "🟢", f"${ema:,.2f} — precio encima ({s}{diff:.1f}%)"
    return "🔴", f"${ema:,.2f} — precio debajo ({diff:.1f}%)"

def sem_vol(vol_hoy, vol_avg):
    if not vol_avg or vol_avg == 0: return "⬜", "Sin datos"
    ratio = vol_hoy / vol_avg
    if ratio > 1.5:  return "🔴", f"{ratio:.1f}x el promedio — volumen muy alto"
    if ratio > 1.1:  return "🟡", f"{ratio:.1f}x el promedio — volumen alto"
    if ratio > 0.8:  return "🟢", f"{ratio:.1f}x el promedio — volumen normal"
    return "🟡", f"{ratio:.1f}x el promedio — volumen bajo"

def calc_tendencia(price, ema200, ema50, rsi, macd, signal):
    c, m, l = 0, 0, 0
    if rsi is not None:
        if rsi < 35:   c += 1
        elif rsi > 65: c -= 1
    if macd is not None and signal is not None:
        if macd > signal: c += 1; m += 1
        else:             c -= 1; m -= 1
    if ema50 is not None:
        if price > ema50: c += 1
        else:             c -= 1
    if ema200 is not None:
        diff = ((price - ema200) / ema200) * 100
        if price > ema200: m += 1; l += 2
        else:              m -= 1; l -= 2
        if diff > 10:      l += 1
        elif diff < -10:   l -= 1

    def lbl(s):
        if s >= 3:  return "🟢 Alcista fuerte"
        if s >= 1:  return "🟢 Alcista"
        if s == 0:  return "⬜ Neutral"
        if s >= -2: return "🔴 Bajista"
        return "🔴 Bajista fuerte"

    return lbl(c), lbl(m), lbl(l)

# ── FORMATTERS ──
def fmt(n, d=2):
    if n is None: return "N/D"
    try:
        v = float(n)
        if abs(v) >= 1e9:  return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"${v/1e6:.1f}M"
        return f"{v:,.{d}f}"
    except: return "N/D"

def fmtp(n):
    if n is None: return "N/D"
    try: return f"{float(n)*100:.1f}%"
    except: return "N/D"

def fmtv(n):
    """Formatea volumen."""
    if n is None or n == 0: return "N/D"
    try:
        v = float(n)
        if v >= 1e9: return f"{v/1e9:.2f}B"
        if v >= 1e6: return f"{v/1e6:.1f}M"
        if v >= 1e3: return f"{v/1e3:.0f}K"
        return str(int(v))
    except: return "N/D"

def score_em(s):
    if s >= 75: return "🟢"
    if s >= 55: return "🟡"
    return "🔴"

def rate(label, v):
    try: v = float(v)
    except: return "⬜"
    if label == "pe":
        if v <= 0:  return "🟡"
        if v < 20:  return "🟢"
        if v < 40:  return "🟡"
        return "🔴"
    if label == "roe":
        if v > 0.20: return "🟢"
        if v > 0.10: return "🟡"
        return "🔴" if v < 0 else "🟡"
    if label == "margin":
        if v > 0.20: return "🟢"
        if v > 0.05: return "🟡"
        return "🔴"
    if label == "debt":
        if v < 0.5: return "🟢"
        if v < 1.5: return "🟡"
        return "🔴"
    if label == "beta":
        if v < 0.8: return "🟢"
        if v < 1.3: return "🟡"
        return "🔴"
    if label == "yield":
        if v > 0.03: return "🟢"
        if v > 0.01: return "🟡"
        return "⬜"
    return "⬜"

def check_alerts(ticker, price):
    lvl = SUPPORT_RESIST.get(ticker.upper())
    if not lvl: return ""
    out = []
    if price <= lvl["s"] * 1.02:
        d = ((price - lvl["s"]) / lvl["s"]) * 100
        out.append(f"⚠️ Cerca del soporte ${lvl['s']} ({d:+.1f}%)")
    if price >= lvl["r"] * 0.98:
        d = ((price - lvl["r"]) / lvl["r"]) * 100
        out.append(f"🔔 Cerca de resistencia ${lvl['r']} ({d:+.1f}%)")
    return "\n".join(out)

def dist_levels(ticker, price):
    lvl = SUPPORT_RESIST.get(ticker.upper())
    if not lvl: return ""
    ds = ((price - lvl["s"]) / lvl["s"]) * 100
    dr = ((lvl["r"] - price) / price) * 100
    return f"Soporte ${lvl['s']} ({ds:+.1f}%) · Resist. ${lvl['r']} ({dr:+.1f}% arriba)"

# ── FETCH QUOTE (Finnhub o Yahoo) ──
def get_quote(ticker):
    t = ticker.upper()
    use_yahoo = t in ARG_TICKERS or t.endswith(".BA") or t.startswith("^") or t in ETF_USE_YAHOO
    if use_yahoo:
        q = get_yf_quote(t)
        if q and q.get("c", 0) > 0:
            return q, True
        return None, True
    try:
        q = finnhub_client.quote(t)
        if q and q.get("c", 0) > 0:
            return q, False
    except:
        pass
    # fallback Yahoo
    q = get_yf_quote(t)
    return (q, True) if q and q.get("c", 0) > 0 else (None, False)

# ── MAIN ANALYSIS ──
def build_message(ticker):
    ticker = ticker.upper().strip()
    if ticker == "MERVAL":
        ticker = "^MERV"

    q, from_yahoo = get_quote(ticker)

    if not q or q.get("c", 0) == 0:
        return (
            f"❌ No encontré datos para `{ticker}`\n\n"
            f"Probá con:\n"
            f"• Tickers US: `SPY` `AAPL` `NVDA`\n"
            f"• Cripto: `BTC-USD` `ETH-USD`\n"
            f"• Arg (bolsa): `GGAL.BA` `PAMP.BA` `YPF`\n"
            f"• Merval: `/merval`"
        )

    price  = float(q.get("c", 0))
    change = float(q.get("d", price - q.get("pc", price)))
    if "d" not in q:
        change = price - float(q.get("pc", price))
    pct    = float(q.get("dp", (change / q.get("pc", price)) * 100 if q.get("pc") else 0))
    high_d = float(q.get("h", 0))
    low_d  = float(q.get("l", 0))
    prev   = float(q.get("pc", 0))
    vol_hoy= float(q.get("v", 0))

    sign  = "+" if change >= 0 else ""
    arrow = "📈" if change >= 0 else "📉"

    # Info / nombre
    name, industry, mktcap_str, vol_avg = ticker, "", "N/D", 0
    if from_yahoo or ticker in ETF_USE_YAHOO or ticker.endswith(".BA") or ticker.startswith("^"):
        info = get_yf_info(ticker)
        name      = info.get("longName") or info.get("shortName") or ticker
        industry  = info.get("sector") or info.get("category") or ""
        mc        = info.get("marketCap") or 0
        mktcap_str= fmt(mc) if mc else "N/D"
        vol_avg   = float(info.get("averageVolume") or info.get("averageDailyVolume10Day") or 0)
        if vol_hoy == 0:
            vol_hoy = float(info.get("regularMarketVolume") or 0)
    else:
        try:
            prof      = finnhub_client.company_profile2(symbol=ticker)
            name      = prof.get("name", ticker)
            industry  = prof.get("finnhubIndustry", "")
            mc        = (prof.get("marketCapitalization") or 0) * 1e6
            mktcap_str= fmt(mc) if mc > 0 else "N/D"
        except: pass

    # Candles y técnicos
    closes, volumes = get_candles_for_analysis(ticker)
    rsi    = calc_rsi(closes) if len(closes) > 16 else None
    macd_v, macd_s, macd_h = calc_macd(closes) if len(closes) > 35 else (None, None, None)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else None
    ema50  = calc_ema(closes, 50)  if len(closes) >= 50  else None
    ema20  = calc_ema(closes, 20)  if len(closes) >= 20  else None

    # Variación semanal y mensual usando historial
    var_sem, var_mes = None, None
    if len(closes) >= 22:
        var_sem = ((closes[-1] - closes[-6])  / closes[-6])  * 100 if len(closes) >= 6  else None
        var_mes = ((closes[-1] - closes[-22]) / closes[-22]) * 100 if len(closes) >= 22 else None

    # Volumen promedio de las velas si no lo tenemos
    if vol_avg == 0 and len(volumes) >= 20:
        vol_avg = float(np.mean(volumes[-20:]))
    if vol_hoy == 0 and len(volumes) > 0:
        vol_hoy = float(volumes[-1])

    # Semáforos
    rsi_s,  rsi_d  = sem_rsi(rsi)
    macd_s2,macd_d = sem_macd(macd_v, macd_s, macd_h)
    e200_s, e200_d = sem_ema(price, ema200, "EMA200")
    e50_s,  e50_d  = sem_ema(price, ema50,  "EMA50")
    e20_s,  e20_d  = sem_ema(price, ema20,  "EMA20")
    vol_s,  vol_d  = sem_vol(vol_hoy, vol_avg)

    t_c, t_m, t_l = calc_tendencia(price, ema200, ema50, rsi, macd_v, macd_s)

    # Fundamentales (Finnhub para acciones, Yahoo para ETFs/ARG)
    pe=roe=margin=beta=div_yield=debt_eq=eps=rev_gr=h52=l52=None
    if from_yahoo or ticker in ETF_USE_YAHOO or ticker.endswith(".BA"):
        info = get_yf_info(ticker) if 'info' not in dir() else info
        try:
            pe        = info.get("trailingPE") or info.get("forwardPE")
            roe       = info.get("returnOnEquity")
            margin    = info.get("profitMargins")
            beta      = info.get("beta")
            div_yield = info.get("dividendYield")
            debt_eq   = info.get("debtToEquity", 0)
            if debt_eq: debt_eq = float(debt_eq) / 100
            eps       = info.get("trailingEps")
            rev_gr    = info.get("revenueGrowth")
            h52       = info.get("fiftyTwoWeekHigh")
            l52       = info.get("fiftyTwoWeekLow")
        except: pass
    else:
        try:
            fund    = finnhub_client.company_basic_financials(ticker, "all")
            met     = fund.get("metric", {})
            pe        = met.get("peNormalizedAnnual") or met.get("peTTM")
            roe       = met.get("roeTTM")
            margin    = met.get("netProfitMarginTTM")
            beta      = met.get("beta")
            div_yield = met.get("dividendYieldIndicatedAnnual")
            debt_eq   = met.get("totalDebt/totalEquityAnnual")
            eps       = met.get("epsTTM")
            rev_gr    = met.get("revenueGrowthTTMYoy")
            h52       = met.get("52WeekHigh")
            l52       = met.get("52WeekLow")
        except: pass

    # Analistas
    pt, rec = None, None
    if not from_yahoo and not ticker.endswith(".BA") and not ticker.startswith("^"):
        try: pt  = finnhub_client.price_target(ticker)
        except: pass
        try:
            r   = finnhub_client.recommendation_trends(ticker)
            rec = r[0] if r else None
        except: pass

    # Noticias (solo Finnhub para acciones US)
    news = []
    if not ticker.endswith(".BA") and not ticker.startswith("^"):
        try:
            today    = datetime.now().strftime("%Y-%m-%d")
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            news     = finnhub_client.company_news(ticker, _from=week_ago, to=today)
            news     = news[:3] if news else []
        except: pass

    alerts   = check_alerts(ticker, price)
    portfolio= MY_PORTFOLIO.get(ticker)

    # ── ARMAR MENSAJE ──
    msg  = f"{arrow} *{ticker}"
    if name and name != ticker: msg += f" — {name}"
    msg += "*\n"
    if industry: msg += f"_{industry}_\n"
    msg += "\n"

    # Precio
    msg += f"💵 *Precio:* ${fmt(price)} ({sign}{fmt(pct)}%)\n"
    msg += f"📊 *Hoy:* Máx ${fmt(high_d)} / Mín ${fmt(low_d)}\n"
    if prev: msg += f"⏮ *Cierre ant.:* ${fmt(prev)}\n"
    if var_sem is not None: msg += f"📆 *Var. semanal:* {'+' if var_sem>=0 else ''}{var_sem:.1f}%\n"
    if var_mes is not None: msg += f"📆 *Var. mensual:* {'+' if var_mes>=0 else ''}{var_mes:.1f}%\n"
    if h52 and l52: msg += f"📅 *52 semanas:* ${fmt(l52)} — ${fmt(h52)}\n"
    if mktcap_str != "N/D": msg += f"🏢 *Market cap:* {mktcap_str}\n"

    # Volumen
    msg += f"\n📦 *Volumen*\n"
    msg += f"{vol_s} Hoy: {fmtv(vol_hoy)} | Promedio: {fmtv(vol_avg)}\n"
    if vol_d != "Sin datos": msg += f"   {vol_d}\n"

    # Alertas soporte/resistencia
    if alerts: msg += f"\n{alerts}\n"
    dist = dist_levels(ticker, price)
    if dist: msg += f"📏 {dist}\n"

    # Técnico
    msg += f"\n📊 *Análisis técnico*\n"
    msg += f"{rsi_s} *RSI (14):* {rsi_d}\n"
    msg += f"{macd_s2} *MACD:* {macd_d}\n"
    msg += f"{e200_s} *EMA 200:* {e200_d}\n"
    msg += f"{e50_s} *EMA 50:* {e50_d}\n"
    msg += f"{e20_s} *EMA 20:* {e20_d}\n"

    # Tendencias
    msg += f"\n📅 *Tendencia*\n"
    msg += f"Corto plazo:   {t_c}\n"
    msg += f"Mediano plazo: {t_m}\n"
    msg += f"Largo plazo:   {t_l}\n"

    # Fundamentales
    has_fund = any(x is not None for x in [pe,roe,margin,beta,div_yield,debt_eq,eps,rev_gr])
    if has_fund:
        msg += f"\n📈 *Fundamentales*\n"
        if pe:        msg += f"{rate('pe',pe)} P/E: {fmt(pe)}x\n"
        if eps:       msg += f"💹 EPS: ${fmt(eps)}\n"
        if roe:       msg += f"{rate('roe',roe)} ROE: {fmtp(roe)}\n"
        if margin:    msg += f"{rate('margin',margin)} Margen neto: {fmtp(margin)}\n"
        if beta:      msg += f"{rate('beta',beta)} Beta: {fmt(beta)}\n"
        if div_yield and float(div_yield or 0) > 0:
            msg += f"{rate('yield',div_yield)} Yield: {fmtp(div_yield)}\n"
        if debt_eq:   msg += f"{rate('debt',debt_eq)} Deuda/Equity: {fmt(debt_eq)}x\n"
        if rev_gr:
            g = "🟢" if float(rev_gr) > 0 else "🔴"
            msg += f"{g} Revenue growth: {fmtp(rev_gr)}\n"

    # Analistas
    if pt and pt.get("targetMean"):
        up   = ((pt["targetMean"] - price) / price) * 100
        ups  = "+" if up >= 0 else ""
        msg += f"\n🎯 *Analistas*\n"
        msg += f"PT promedio: ${fmt(pt['targetMean'])} ({ups}{up:.1f}%)\n"
        if pt.get("targetHigh") and pt.get("targetLow"):
            msg += f"Rango PT: ${fmt(pt['targetLow'])} — ${fmt(pt['targetHigh'])}\n"
    if rec:
        tot = (rec.get("strongBuy",0)+rec.get("buy",0)+rec.get("hold",0)+rec.get("sell",0)+rec.get("strongSell",0)) or 1
        bp  = ((rec.get("strongBuy",0)+rec.get("buy",0))/tot)*100
        msg += f"📊 Recomendación: {bp:.0f}% compra · {rec.get('hold',0)} hold · {rec.get('sell',0)+rec.get('strongSell',0)} venta\n"

    # Portfolio
    if portfolio:
        msg += f"\n💼 *Mi posición*\n"
        msg += f"Peso: {portfolio['weight']} del portfolio\n"
        if portfolio["dca"]: msg += f"DCA: {portfolio['dca']}\n"
        msg += f"Target: {portfolio['target']}\n"
        if portfolio["gtc"]: msg += f"⬆️ GTC SELL activo: {portfolio['gtc']}\n"
        msg += f"\n{score_em(portfolio['score'])} *Veredicto:* {portfolio['verdict']}\n"
        msg += f"Score: {portfolio['score']}/100\n"

    # Noticias
    if news:
        msg += f"\n📰 *Noticias recientes*\n"
        for n in news:
            h = (n.get("headline") or "")[:75]
            s = n.get("source", "")
            msg += f"• {h} — _{s}_\n"

    src = "Yahoo Finance + Finnhub" if from_yahoo else "Finnhub"
    msg += f"\n_Datos vía {src} · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    return msg

# ── MERVAL ──
def build_merval():
    msg = "🇦🇷 *Índice Merval*\n\n"
    try:
        q = get_yf_quote("^MERV")
        if q and q.get("c", 0) > 0:
            p  = float(q["c"])
            pc = float(q.get("pc", p))
            ch = p - pc
            pt = (ch / pc * 100) if pc else 0
            s  = "+" if ch >= 0 else ""
            em = "📈" if ch >= 0 else "📉"
            msg += f"{em} *Precio:* {p:,.0f} ARS ({s}{pt:.1f}%)\n"
            msg += f"Hoy: Máx {q.get('h',0):,.0f} / Mín {q.get('l',0):,.0f}\n\n"
        else:
            msg += "No se pudo obtener el precio del Merval.\n\n"
    except Exception as e:
        logger.error(f"Merval error: {e}")
        msg += "Error al obtener el Merval.\n\n"

    principales = [
        ("GGAL.BA",  "Galicia"),
        ("PAMP.BA",  "Pampa Energía"),
        ("YPFD.BA",  "YPF"),
        ("BBAR.BA",  "BBVA Argentina"),
        ("BMA.BA",   "Banco Macro"),
        ("TXAR.BA",  "Ternium Arg."),
        ("LOMA.BA",  "Loma Negra"),
        ("CEPU.BA",  "Central Puerto"),
        ("TECO2.BA", "Telecom"),
    ]
    msg += "*Principales acciones:*\n"
    for sym, nombre in principales:
        try:
            q = get_yf_quote(sym)
            if q and q.get("c", 0) > 0:
                p   = float(q["c"])
                pc2 = float(q.get("pc", p))
                ch2 = p - pc2
                pt2 = (ch2 / pc2 * 100) if pc2 else 0
                s2  = "+" if ch2 >= 0 else ""
                em2 = "📈" if ch2 >= 0 else "📉"
                msg += f"{em2} *{sym}* ({nombre}): ${p:,.1f} ({s2}{pt2:.1f}%)\n"
            else:
                msg += f"⬜ *{sym}* — Sin datos\n"
        except:
            msg += f"⬜ *{sym}* — Error\n"

    msg += f"\n_Mandá /GGAL.BA o cualquier ticker .BA para análisis completo_"
    msg += f"\n_Datos vía Yahoo Finance · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    return msg

# ── PORTFOLIO SUMMARY ──
def build_portfolio():
    msg  = "💼 *Grynbaum Capital — Portfolio IBKR*\n"
    msg += f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
    msg += "Total: ~$7,650 invertido | P&G: \\-3.0%\nDCA mensual: $500\n\n"
    for ticker, ctx in MY_PORTFOLIO.items():
        try:
            q, _ = get_quote(ticker)
            if q and q.get("c", 0) > 0:
                p  = float(q["c"])
                pt = float(q.get("dp", 0))
                s  = "+" if pt >= 0 else ""
                em = "📈" if pt >= 0 else "📉"
                se = score_em(ctx["score"])
                msg += f"{se} *{ticker}* ${fmt(p)} ({s}{fmt(pt)}%) — {ctx['weight']}\n"
            else:
                msg += f"⬜ *{ticker}* — Sin datos\n"
        except:
            msg += f"⬜ *{ticker}* — Error\n"
    msg += "\n_Mandá /TICKER para análisis completo_"
    return msg

# ── BTC ──
def build_btc():
    msg = "₿ *Bitcoin — BTC/USD*\n\n"
    try:
        q = finnhub_client.quote("BINANCE:BTCUSDT")
        if not q or q.get("c", 0) == 0:
            raise Exception("no data")
    except:
        try: q = get_yf_quote("BTC-USD")
        except: q = None

    if q and q.get("c", 0) > 0:
        p  = float(q["c"])
        ch = float(q.get("d", p - q.get("pc", p)))
        pt = float(q.get("dp", (ch/q.get("pc",p))*100 if q.get("pc") else 0))
        h  = float(q.get("h", 0))
        l  = float(q.get("l", 0))
        s  = "+" if ch >= 0 else ""
        em = "📈" if ch >= 0 else "📉"
        msg += f"{em} *Precio:* ${p:,.0f}\n"
        msg += f"Cambio: {s}${abs(ch):,.0f} ({s}{pt:.2f}%)\n"
        if h and l: msg += f"Hoy: Máx ${h:,.0f} / Mín ${l:,.0f}\n\n"

        MSTR_AVG = 75696
        if p > 80000:   msg += "🟢 Por encima del costo promedio de MSTR ($75,696)\n"
        elif p > 60000: msg += "🟡 Por debajo del costo promedio de MSTR ($75,696)\n"
        else:           msg += "🔴 Zona de riesgo para MSTR\n"
        diff = ((p - MSTR_AVG) / MSTR_AVG) * 100
        msg += f"Diferencia vs costo MSTR: {'+' if diff>=0 else ''}{diff:.1f}%\n"
    else:
        msg += "No se pudo obtener el precio de BTC.\n"

    msg += f"\n💼 *Mi posición BTC*\n"
    msg += f"DCA: $100/mes en Binance\n"
    msg += f"Emergency fund: $3,400 (banco + Binance Earn)\n"
    msg += f"Exposición indirecta vía MSTR: 4.75% portfolio\n"
    msg += f"\n_Datos vía Finnhub · {datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    return msg

# ── HANDLERS ──
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Grynbaum Capital Bot*\n\n"
        "📊 `/portfolio` — Resumen de tu portfolio\n"
        "₿ `/btc` — Bitcoin \\+ tu posición\n"
        "🇦🇷 `/merval` — Índice Merval \\+ principales acciones\n"
        "🔍 `/TICKER` — Análisis completo\n\n"
        "*Tu portfolio:*\n"
        "`/SPY` `/GLD` `/ARKW` `/VGT` `/XLE` `/SCHD` `/MSTR`\n\n"
        "*Otros tickers:*\n"
        "`/AAPL` `/NVDA` `/MELI` `/TSLA`\n"
        "`/BTC\\-USD` `/ETH\\-USD`\n"
        "`/GGAL.BA` `/PAMP.BA` `/YPFD.BA`\n\n"
        "*Cada análisis incluye:*\n"
        "• Precio, máx/mín, var\\. semanal y mensual\n"
        "• Volumen con semáforo\n"
        "• RSI, MACD, EMA20, EMA50, EMA200 con semáforos\n"
        "• Tendencia corto / mediano / largo plazo\n"
        "• Fundamentales con semáforos\n"
        "• Distancia a soporte y resistencia\n"
        "• Noticias recientes\n"
        "• Tu posición y veredicto \\(si es del portfolio\\)\n\n"
        "🟢 positivo  🟡 neutro  🔴 negativo  ⬜ sin datos"
    )
    await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando portfolio…")
    await update.message.reply_text(build_portfolio(), parse_mode="Markdown")

async def btc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando BTC…")
    await update.message.reply_text(build_btc(), parse_mode="Markdown")

async def merval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Cargando Merval…")
    await update.message.reply_text(build_merval(), parse_mode="Markdown")

async def ticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.split()[0].lstrip("/").upper()
    if command in ["START", "HELP", "PORTFOLIO", "BTC", "MERVAL"]:
        return
    await update.message.reply_text(f"⏳ Analizando {command}…")
    try:
        msg = build_message(command)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error building message for {command}: {e}")
        await update.message.reply_text(f"❌ Error al analizar {command}. Intentá de nuevo.")

async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text and len(text) <= 15 and all(c.isalnum() or c in "-_.^:" for c in text):
        await update.message.reply_text(f"⏳ Analizando {text}…")
        try:
            msg = build_message(text)
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error text msg {text}: {e}")
            await update.message.reply_text(f"❌ Error al analizar {text}.")

# ── MAIN ──
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",     start_cmd))
    app.add_handler(CommandHandler("help",      start_cmd))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("btc",       btc_cmd))
    app.add_handler(CommandHandler("merval",    merval_cmd))
    app.add_handler(MessageHandler(filters.COMMAND, ticker_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    logger.info("Bot iniciado ✓")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
