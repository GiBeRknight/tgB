import asyncio
import logging

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from bot.config import BOT_TOKEN
from bot.db import init_db
from bot.handlers import help_command, region_callback, start

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def post_init(application):
    await init_db()
    logger.info("Database tables created")


def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region_"))

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
