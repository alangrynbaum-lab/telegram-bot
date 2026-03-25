import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from market_data import get_asset_info, format_message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "TU_TOKEN_AQUI")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Bienvenido al Bot de Mercados Financieros*\n\n"
        "Usá el comando `/TICKER` para obtener información de cualquier activo\\.\n\n"
        "*Ejemplos:*\n"
        "• `/AAPL` — Apple \\(acción\\)\n"
        "• `/BTC` — Bitcoin \\(cripto\\)\n"
        "• `/EURUSD=X` — EUR/USD \\(forex\\)\n"
        "• `/GC=F` — Oro \\(commodity\\)\n"
        "• `/SPY` — S\\&P 500 ETF\n"
        "• `/TLT` — Bono del Tesoro ETF\n\n"
        "📊 Muestra: precio, variación, volumen, RSI, MACD, EMA200, market cap y más\\."
    )
    await update.message.reply_text(msg, parse_mode="MarkdownV2")


async def handle_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    ticker = text.lstrip("/").upper().split()[0]

    await update.message.reply_text(f"🔍 Buscando *{ticker}*\\.\\.\\.", parse_mode="MarkdownV2")

    data = get_asset_info(ticker)

    if data.get("error"):
        await update.message.reply_text(
            f"❌ No se encontró el ticker *{ticker}*\\.\n\n"
            "Verificá que sea un símbolo válido de Yahoo Finance\\.\n"
            "Ejemplos: `AAPL`, `BTC-USD`, `EURUSD=X`, `GC=F`",
            parse_mode="MarkdownV2"
        )
        return

    message = format_message(data)
    await update.message.reply_text(message, parse_mode="MarkdownV2")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.COMMAND, handle_ticker))

    logger.info("🤖 Bot iniciado y escuchando...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
