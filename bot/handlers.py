from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from bot.db import async_session
from bot.models import User


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    async with async_session() as session:
        user = await session.get(User, tg_user.id)
        if user is None:
            user = User(
                id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            session.add(user)
            await session.commit()

    await update.message.reply_text(
        f"Hello, {tg_user.first_name}! You are registered."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Register and start the bot\n"
        "/help - Show this message"
    )
