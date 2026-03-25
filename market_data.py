import os
import re
import requests

API_KEY = os.environ.get("TWELVE_DATA_KEY", "")
BASE_URL = "https://api.twelvedata.com"

CRYPTO_ALIASES = {
    "BTC": "BTC/USD", "ETH": "ETH/USD", "SOL": "SOL/USD",
    "ADA": "ADA/USD", "XRP": "XRP/USD", "BNB": "BNB/USD",
    "DOGE": "DOGE/USD", "AVAX": "AVAX/USD", "DOT": "DOT/USD",
    "LINK": "LINK/USD", "MATIC": "MATIC/USD", "LTC": "LTC/USD",
}


def detect_ticker(ticker: str) -> tuple:
    upper = ticker.upper()
    if upper in CRYPTO_ALIASES:
        return CRYPTO_ALIASES[upper], True
    return upper, False


def api_get(endpoint: str, params: dict) -> dict:
    params["apikey"] = API_KEY
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_asset_info(ticker_raw: str) -> dict:
    symbol, is_crypto = detect_ticker(ticker_raw)

    quote = api_get("quote", {"symbol": symbol})
    if quote.get("status") == "error" or "close" not in quote:
        return {"error": True}

    try:
        price = float(quote.get("close") or 0)
        prev_close = float(quote.get("previous_close") or 0)
        day_high = float(quote.get("high") or 0)
        day_low = float(quote.get("low") or 0)
        volume = float(quote.get("volume")) if quote.get("volume") else None
        name = quote.get("name", symbol)
        change_pct = float(quote.get("percent_change") or 0)
        asset_type = "🪙 Cripto" if is_crypto else "📈 Acción / ETF"

        rsi_data = api_get("rsi", {"symbol": symbol, "interval": "1day", "time_period": 14, "outputsize": 1})
        rsi = None
        if rsi_data.get("values"):
            rsi = round(float(rsi_data["values"][0]["rsi"]), 2)

        macd_data = api_get("macd", {"symbol": symbol, "interval": "1day", "outputsize": 1})
        macd_val = macd_sig_val = macd_hist_val = None
        if macd_data.get("values"):
            v = macd_data["values"][0]
            macd_val = round(float(v.get("macd", 0)), 4)
            macd_sig_val = round(float(v.get("macd_signal", 0)), 4)
            macd_hist_val = round(float(v.get("macd_hist", 0)), 4)

        ema200_data = api_get("ema", {"symbol": symbol, "interval": "1day", "time_period": 200, "outputsize": 1})
        ema200 = None
        if ema200_data.get("values"):
            ema200 = round(float(ema200_data["values"][0]["ema"]), 4)

        ema50_data = api_get("ema", {"symbol": symbol, "interval": "1day", "time_period": 50, "outputsize": 1})
        ema50 = None
        if ema50_data.get("values"):
            ema50 = round(float(ema50_data["values"][0]["ema"]), 4)

        rsi_signal = "🟢 Sobreventa" if rsi and rsi < 30 else ("🔴 Sobrecompra" if rsi and rsi > 70 else "⚪ Neutral")
        macd_signal_txt = "🟢 Alcista" if macd_hist_val and macd_hist_val > 0 else "🔴 Bajista"
        ema_signal = ("🟢 Sobre EMA200" if price > ema200 else "🔴 Bajo EMA200") if ema200 else "N/A"

        return {
            "error": False,
            "ticker": symbol,
            "name": name,
            "asset_type": asset_type,
            "currency": "USD",
            "price": price,
            "change_pct": change_pct,
            "day_high": day_high,
            "day_low": day_low,
            "volume": volume,
            "rsi": rsi,
            "rsi_signal": rsi_signal,
            "macd": macd_val,
            "macd_signal_val": macd_sig_val,
            "macd_hist": macd_hist_val,
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
    s = "$" if currency == "USD" else currency + " "
    return f"{s}{float(val):,.4f}" if float(val) < 1 else f"{s}{float(val):,.2f}"


def format_volume(n) -> str:
    if n is None:
        return "N/A"
    n = float(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n/1_000:.2f}K"
    return str(int(n))


def format_message(d: dict) -> str:
    ticker = escape_md(d["ticker"])
    name = escape_md(d["name"])
    asset_type = escape_md(d["asset_type"])
    currency = d.get("currency", "USD")
    price_str = escape_md(fmt_price(d["price"], currency))

    chg = d.get("change_pct")
    chg_emoji = "🟢" if chg and chg >= 0 else "🔴"
    chg_str = escape_md(f"{chg:+.2f}%") if chg is not None else "N/A"
    change_line = f"{chg_emoji} Variación: *{chg_str}*"

    msg = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{ticker}* — {name}\n"
        f"{asset_type}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *Precio:* `{escape_md(fmt_price(d['price'], currency))}`\n"
        f"{change_line}\n"
        f"📈 Máx del día: `{escape_md(fmt_price(d.get('day_high'), currency))}`\n"
        f"📉 Mín del día: `{escape_md(fmt_price(d.get('day_low'), currency))}`\n\n"
        f"🔢 Volumen: `{escape_md(format_volume(d.get('volume')))}`\n\n"
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
        f"_Datos: Twelve Data \\| Actualizados al momento_"
    )
    return msg
