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
    "BOND": "🏦 Bono",
    "MUTUALFUND": "🗂 Fondo Mutuo",
    "INDEX": "📊 Índice",
}


def detect_ticker(ticker: str) -> str:
    crypto_aliases = {
        "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
        "ADA": "ADA-USD", "XRP": "XRP-USD", "BNB": "BNB-USD",
        "DOGE": "DOGE-USD", "AVAX": "AVAX-USD", "DOT": "DOT-USD",
        "LINK": "LINK-USD", "MATIC": "MATIC-USD", "LTC": "LTC-USD",
    }
    return crypto_aliases.get(ticker.upper(), ticker.upper())


def calc_rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = -delta.clip(upper=0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def calc_macd(series: pd.Series):
    if len(series) < 26:
        return None, None, None
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return (
        round(float(macd_line.iloc[-1]), 4),
        round(float(signal_line.iloc[-1]), 4),
        round(float(histogram.iloc[-1]), 4),
    )


def calc_ema(series: pd.Series, period: int = 200) -> float:
    if len(series) < period:
        return None
    ema = series.ewm(span=period, adjust=False).mean()
    return round(float(ema.iloc[-1]), 4)


def format_large_number(n) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "N/A"
    n = float(n)
    if n >= 1_000_000_000_000:
        return f"${n/1_000_000_000_000:.2f}T"
    elif n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"${n/1_000:.2f}K"
    return f"${n:.2f}"


def format_volume(n) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "N/A"
    n = float(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n/1_000:.2f}K"
    return str(int(n))


def get_asset_info(ticker_raw: str) -> dict:
    ticker = detect_ticker(ticker_raw)

    try:
        t = yf.Ticker(ticker)

        # Obtener histórico primero (más confiable)
        hist = t.history(period="1y")
        if hist.empty:
            # Intentar con 5d por si es un activo con menos historia
            hist = t.history(period="5d")
            if hist.empty:
                return {"error": True}

        close = hist["Close"]
        price = float(close.iloc[-1])

        # Info del activo
        try:
            info = t.info
        except Exception:
            info = {}

        quote_type = info.get("quoteType", "EQUITY")
        asset_type = ASSET_TYPE_MAP.get(quote_type, f"📄 {quote_type}")
        name = info.get("longName") or info.get("shortName") or ticker
        currency = info.get("currency", "USD")

        # Precios del día desde history
        day_high = float(hist["High"].iloc[-1])
        day_low = float(hist["Low"].iloc[-1])
        volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else None

        # Variación respecto al día anterior
        prev_close = None
        change_pct = None
        if len(close) >= 2:
            prev_close = float(close.iloc[-2])
            change_pct = ((price - prev_close) / prev_close) * 100

        avg_volume = info.get("averageVolume")
        market_cap = info.get("marketCap")

        # Indicadores técnicos
        rsi = calc_rsi(close)
        macd_val, macd_signal, macd_hist = calc_macd(close)
        ema200 = calc_ema(close, 200)
        ema50 = calc_ema(close, 50)

        rsi_signal = "🟢 Sobreventa" if rsi and rsi < 30 else ("🔴 Sobrecompra" if rsi and rsi > 70 else "⚪ Neutral")
        macd_signal_txt = "🟢 Alcista" if macd_hist and macd_hist > 0 else "🔴 Bajista"

        ema_signal = "N/A"
        if ema200 and price:
            ema_signal = "🟢 Sobre EMA200" if price > ema200 else "🔴 Bajo EMA200"

        return {
            "error": False,
            "ticker": ticker,
            "name": name,
            "asset_type": asset_type,
            "currency": currency,
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "day_high": day_high,
            "day_low": day_low,
            "volume": volume,
            "avg_volume": avg_volume,
            "market_cap": market_cap,
            "rsi": rsi,
            "rsi_signal": rsi_signal,
            "macd": macd_val,
            "macd_signal_val": macd_signal,
            "macd_hist": macd_hist,
            "macd_signal_txt": macd_signal_txt,
            "ema200": ema200,
            "ema50": ema50,
            "ema_signal": ema_signal,
        }

    except Exception as e:
        return {"error": True, "detail": str(e)}


def escape_md(text: str) -> str:
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special)}])', r'\\\1', str(text))


def fmt_price(val, currency="USD") -> str:
    if val is None:
        return "N/A"
    symbol = "$" if currency == "USD" else currency + " "
    return f"{symbol}{float(val):,.4f}" if float(val) < 1 else f"{symbol}{float(val):,.2f}"


def format_message(d: dict) -> str:
    ticker = escape_md(d["ticker"])
    name = escape_md(d["name"])
    asset_type = escape_md(d["asset_type"])
    currency = d.get("currency", "USD")

    price_str = escape_md(fmt_price(d["price"], currency))

    chg = d.get("change_pct")
    if chg is not None:
        chg_emoji = "🟢" if chg >= 0 else "🔴"
        chg_str = escape_md(f"{chg:+.2f}%")
        change_line = f"{chg_emoji} Variación: *{chg_str}*"
    else:
        change_line = "⚪ Variación: N/A"

    high = escape_md(fmt_price(d.get("day_high"), currency))
    low = escape_md(fmt_price(d.get("day_low"), currency))
    vol = escape_md(format_volume(d.get("volume")))
    avg_vol = escape_md(format_volume(d.get("avg_volume")))
    mcap = escape_md(format_large_number(d.get("market_cap")))

    rsi_val = escape_md(str(d.get("rsi", "N/A")))
    rsi_sig = escape_md(d.get("rsi_signal", ""))

    macd_val = escape_md(str(d.get("macd", "N/A")))
    macd_sig_val = escape_md(str(d.get("macd_signal_val", "N/A")))
    macd_hist = escape_md(str(d.get("macd_hist", "N/A")))
    macd_sig_txt = escape_md(d.get("macd_signal_txt", ""))

    ema200 = escape_md(fmt_price(d.get("ema200"), currency)) if d.get("ema200") else "N/A"
    ema50 = escape_md(fmt_price(d.get("ema50"), currency)) if d.get("ema50") else "N/A"
    ema_sig = escape_md(d.get("ema_signal", "N/A"))

    msg = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{ticker}* — {name}\n"
        f"{asset_type}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *Precio:* `{price_str}`\n"
        f"{change_line}\n"
        f"📈 Máx del día: `{high}`\n"
        f"📉 Mín del día: `{low}`\n\n"
        f"━━ 📊 *VOLUMEN* ━━\n"
        f"🔢 Volumen: `{vol}`\n"
        f"📊 Vol\\. Promedio: `{avg_vol}`\n"
        f"💰 Market Cap: `{mcap}`\n\n"
        f"━━ 🧮 *INDICADORES TÉCNICOS* ━━\n"
        f"📐 RSI \\(14\\): `{rsi_val}` — {rsi_sig}\n\n"
        f"📉 MACD:\n"
        f"  • Línea: `{macd_val}`\n"
        f"  • Señal: `{macd_sig_val}`\n"
        f"  • Histograma: `{macd_hist}`\n"
        f"  • Tendencia: {macd_sig_txt}\n\n"
        f"📏 EMA 200: `{ema200}`\n"
        f"📏 EMA 50: `{ema50}`\n"
        f"  • Estado: {ema_sig}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Datos: Yahoo Finance \\| Actualizados al momento_"
    )
    return msg
