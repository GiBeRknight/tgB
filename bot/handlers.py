from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db import async_session
from bot.models import User

REGIONS_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("Фонтанка1", callback_data="region_fontanka1")],
    [InlineKeyboardButton("Фонтанка2", callback_data="region_fontanka2")],
    [InlineKeyboardButton("Сухий Лиман", callback_data="region_sukhyi_lyman")],
])


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
        "Це бот першої земельної компанії, будь ласка оберіть який регіон вас цікавить",
        reply_markup=REGIONS_KEYBOARD,
    )


async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    labels = {
        "region_fontanka1": "Фонтанка1",
        "region_fontanka2": "Фонтанка2",
        "region_sukhyi_lyman": "Сухий Лиман",
    }
    region = labels.get(query.data, query.data)
    await query.edit_message_text(f"Ви обрали: {region}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Register and start the bot\n"
        "/help - Show this message"
    )
