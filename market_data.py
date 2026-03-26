import yfinance as yf
import pandas as pd
import numpy as np
import re

ASSET_TYPE_MAP = {
    "EQUITY": "📈 Acción",
    "ETF": "📦 ETF",
    "CRYPTOCURRENCY": "🪙 Cripto",
    "CURRENCY": "💱 Forex",
    "FUTURE": "🥇 Commodity/Futuro",
    "MUTUALFUND": "🗂 Fondo Mutuo",
    "INDEX": "📊 Índice",
}

ALIASES = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "ADA": "ADA-USD", "XRP": "XRP-USD", "DOGE": "DOGE-USD",
    "BNB": "BNB-USD", "AVAX": "AVAX-USD", "LTC": "LTC-USD",
    "GOLD": "GC=F", "ORO": "GC=F",
    "PLATA": "SI=F", "SILVER": "SI=F",
    "PETROLEO": "CL=F", "OIL": "CL=F",
    "GAS": "NG=F",
    "MERVAL": "^MERV", "SP500": "^GSPC", "NASDAQ": "^IXIC", "DOW": "^DJI",
    "EURUSD": "EURUSD=X", "USDJPY": "USDJPY=X",
    "GBPUSD": "GBPUSD=X", "USDARS": "USDARS=X",
}

def detect_ticker(ticker: str) -> str:
    return ALIASES.get(ticker.upper(), ticker.upper())

def calc_rsi(series, period=14):
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None

def calc_macd(series):
    if len(series) < 26:
        return None, None, None
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return round(float(macd.iloc[-1]), 4), round(float(signal.iloc[-1]), 4), round(float(hist.iloc[-1]), 4)

def calc_ema(series, period=200):
    if len(series) < period:
        return None
    return round(float(series.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

def format_large_number(n):
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "N/A"
    n = float(n)
    if n >= 1e12: return f"${n/1e12:.2f}T"
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    return f"${n:,.0f}"

def format_volume(n):
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "N/A"
    n = float(n)
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.2f}M"
    if n >= 1e3: return f"{n/1e3:.2f}K"
    return str(int(n))

def get_asset_info(ticker_raw: str) -> dict:
    ticker = detect_ticker(ticker_raw)
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty:
            hist = t.history(period="5d")
            if hist.empty:
                return {"error": True}

        close = hist["Close"]
        price = float(close.iloc[-1])

        try:
            info = t.info
        except:
            info = {}

        quote_type = info.get("quoteType", "EQUITY")
        asset_type = ASSET_TYPE_MAP.get(quote_type, "📄 Otro")
        name = info.get("longName") or info.get("shortName") or ticker
        currency = info.get("currency", "USD")

        day_high = float(hist["High"].iloc[-1])
        day_low = float(hist["Low"].iloc[-1])
        volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else None
        prev_close = float(close.iloc[-2]) if len(close) >= 2 else None
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else None

        rsi = calc_rsi(close)
        macd_val, macd_sig, macd_hist = calc_macd(close)
        ema200 = calc_ema(close, 200)
        ema50 = calc_ema(close, 50)

        rsi_signal = "🟢 Sobreventa" if rsi and rsi < 30 else ("🔴 Sobrecompra" if rsi and rsi > 70 else "⚪ Neutral")
        macd_signal_txt = "🟢 Alcista" if macd_hist and macd_hist > 0 else "🔴 Bajista"
        ema_signal = ("🟢 Sobre EMA200" if price > ema200 else "🔴 Bajo EMA200") if ema200 else "N/A"

        return {
            "error": False, "ticker": ticker, "name": name,
            "asset_type": asset_type, "currency": currency,
            "price": price, "change_pct": change_pct,
            "day_high": day_high, "day_low": day_low,
            "volume": volume, "market_cap": info.get("marketCap"),
            "avg_volume": info.get("averageVolume"),
            "rsi": rsi, "rsi_signal": rsi_signal,
            "macd": macd_val, "macd_signal_val": macd_sig,
            "macd_hist": macd_hist, "macd_signal_txt": macd_signal_txt,
            "ema200": ema200, "ema50": ema50, "ema_signal": ema_signal,
        }
    except Exception as e:
        return {"error": True, "detail": str(e)}

def escape_md(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\-])', r'\\\1', str(text))

def fmt_price(val, currency="USD") -> str:
    if val is None: return "N/A"
    s = "$" if currency == "USD" else f"{currency} "
    return f"{s}{float(val):,.4f}" if float(val) < 1 else f"{s}{float(val):,.2f}"

def format_message(d: dict) -> str:
    chg = d.get("change_pct")
    chg_emoji = "🟢" if chg and chg >= 0 else "🔴"
    chg_str = escape_md(f"{chg:+.2f}%") if chg is not None else "N/A"
    currency = d.get("currency", "USD")

    msg = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{escape_md(d['ticker'])}* — {escape_md(d['name'])}\n"
        f"{escape_md(d['asset_type'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *Precio:* `{escape_md(fmt_price(d['price'], currency))}`\n"
        f"{chg_emoji} Variación: *{chg_str}*\n"
        f"📈 Máx del día: `{escape_md(fmt_price(d.get('day_high'), currency))}`\n"
        f"📉 Mín del día: `{escape_md(fmt_price(d.get('day_low'), currency))}`\n\n"
        f"🔢 Volumen: `{escape_md(format_volume(d.get('volume')))}`\n"
        f"💰 Market Cap: `{escape_md(format_large_number(d.get('market_cap')))}`\n\n"
        f"━━ 🧮 *INDICADORES TÉCNICOS* ━━\n"
        f"📐 RSI \\(14\\): `{escape_md(str(d.get('rsi','N/A')))}` — {escape_md(d.get('rsi_signal',''))}\n\n"
        f"📉 MACD:\n"
        f"  • Línea: `{escape_md(str(d.get('macd','N/A')))}`\n"
        f"  • Señal: `{escape_md(str(d.get('macd_signal_val','N/A')))}`\n"
        f"  • Histograma: `{escape_md(str(d.get('macd_hist','N/A')))}`\n"
        f"  • Tendencia: {escape_md(d.get('macd_signal_txt',''))}\n\n"
        f"📏 EMA 200: `{escape_md(fmt_price(d.get('ema200'), currency)) if d.get('ema200') else 'N/A'}`\n"
        f"📏 EMA 50: `{escape_md(fmt_price(d.get('ema50'), currency)) if d.get('ema50') else 'N/A'}`\n"
        f"  • Estado: {escape_md(d.get('ema_signal','N/A'))}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Datos: Yahoo Finance \\| Actualizados al momento_"
    )
    return msg
