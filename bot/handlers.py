from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import ADMIN_PASSWORD
from bot.db import async_session
from bot.models import Region, User

# --- Conversation states ---
(
    LOGIN_PASSWORD,
    ADD_NAME,
    ADD_PRICE,
    ADD_PLOTS,
    ADD_DESCRIBE,
    ADD_LINK_MAP,
    ADD_LINK_YOUTUBE,
    ADD_CONFIRM,
    EDIT_PICK_REGION,
    EDIT_PICK_FIELD,
    EDIT_VALUE,
) = range(11)

# --- Keyboards ---
REGIONS_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Фонтанка1", callback_data="region_fontanka1")],
        [InlineKeyboardButton("Фонтанка2", callback_data="region_fontanka2")],
        [InlineKeyboardButton("Сухий Лиман", callback_data="region_sukhyi_lyman")],
    ]
)

START_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Фонтанка1", callback_data="region_fontanka1")],
        [InlineKeyboardButton("Фонтанка2", callback_data="region_fontanka2")],
        [InlineKeyboardButton("Сухий Лиман", callback_data="region_sukhyi_lyman")],
        [InlineKeyboardButton("Увійти як Адмін", callback_data="admin_login")],
    ]
)

ADMIN_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Додати новий", callback_data="admin_add")],
        [InlineKeyboardButton("Редагувати", callback_data="admin_edit")],
        [InlineKeyboardButton("Назад", callback_data="admin_back")],
    ]
)

CONFIRM_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Так", callback_data="confirm_yes"),
            InlineKeyboardButton("Ні", callback_data="confirm_no"),
        ]
    ]
)

FIELD_LABELS = {
    "name": "Назва",
    "price": "Ціна",
    "plots_number": "Кількість ділянок",
    "describe": "Опис",
    "link_map": "Посилання на карту",
    "link_youtube": "Посилання на YouTube",
}


# ──────────────────────────────────────
#  /start
# ──────────────────────────────────────
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
        reply_markup=START_KEYBOARD,
    )


# ──────────────────────────────────────
#  Region selection (public)
# ──────────────────────────────────────
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


# ──────────────────────────────────────
#  /help
# ──────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Запустити бота\n" "/help - Показати цю підказку"
    )


# ──────────────────────────────────────
#  Admin login flow
# ──────────────────────────────────────
async def admin_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Check if already admin
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if user and user.is_admin:
            await query.edit_message_text(
                "Ви вже адміністратор.", reply_markup=ADMIN_MENU
            )
            return ConversationHandler.END

    await query.edit_message_text("Введіть пароль адміністратора:")
    return LOGIN_PASSWORD


async def admin_login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()

    if password != ADMIN_PASSWORD:
        await update.message.reply_text(
            "Невірний пароль. Спробуйте /start щоб почати знову."
        )
        return ConversationHandler.END

    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if user:
            user.is_admin = True
            await session.commit()

    await update.message.reply_text("Ви увійшли як адмін.", reply_markup=ADMIN_MENU)
    return ConversationHandler.END


# ──────────────────────────────────────
#  Admin menu callbacks
# ──────────────────────────────────────
async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return ConversationHandler.END

    if query.data == "admin_add":
        context.user_data["new_region"] = {}
        await query.edit_message_text("Введіть назву:")
        return ADD_NAME

    if query.data == "admin_edit":
        async with async_session() as session:
            regions = (await session.execute(select(Region))).scalars().all()
        if not regions:
            await query.edit_message_text(
                "Немає регіонів для редагування.", reply_markup=ADMIN_MENU
            )
            return ConversationHandler.END
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(r.name, callback_data=f"editreg_{r.id}")]
                for r in regions
            ]
        )
        await query.edit_message_text("Оберіть регіон:", reply_markup=keyboard)
        return EDIT_PICK_REGION

    if query.data == "admin_back":
        await query.edit_message_text(
            "Це бот першої земельної компанії, будь ласка оберіть який регіон вас цікавить",
            reply_markup=START_KEYBOARD,
        )
        return ConversationHandler.END

    return ConversationHandler.END


# ──────────────────────────────────────
#  Add region conversation
# ──────────────────────────────────────
async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_region"]["name"] = update.message.text.strip()
    await update.message.reply_text("Введіть ціну:")
    return ADD_PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = Decimal(update.message.text.strip().replace(",", "."))
    except InvalidOperation:
        await update.message.reply_text("Невірний формат. Введіть число:")
        return ADD_PRICE
    context.user_data["new_region"]["price"] = price
    await update.message.reply_text("Введіть кількість ділянок:")
    return ADD_PLOTS


async def add_plots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        plots = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Невірний формат. Введіть ціле число:")
        return ADD_PLOTS
    context.user_data["new_region"]["plots_number"] = plots
    await update.message.reply_text("Введіть опис (або /skip):")
    return ADD_DESCRIBE


async def add_describe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["describe"] = None if text == "/skip" else text
    await update.message.reply_text("Введіть посилання на карту (або /skip):")
    return ADD_LINK_MAP


async def add_link_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["link_map"] = None if text == "/skip" else text
    await update.message.reply_text("Введіть посилання на YouTube (або /skip):")
    return ADD_LINK_YOUTUBE


async def add_link_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["link_youtube"] = None if text == "/skip" else text

    data = context.user_data["new_region"]
    summary = (
        f"Назва: {data['name']}\n"
        f"Ціна: {data['price']}\n"
        f"Кількість ділянок: {data['plots_number']}\n"
        f"Опис: {data.get('describe') or '—'}\n"
        f"Карта: {data.get('link_map') or '—'}\n"
        f"YouTube: {data.get('link_youtube') or '—'}"
    )
    await update.message.reply_text(
        f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD
    )
    return ADD_CONFIRM


async def add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_yes":
        data = context.user_data.pop("new_region", {})
        region = Region(**data)
        async with async_session() as session:
            session.add(region)
            await session.commit()
        await query.edit_message_text("Регіон збережено!", reply_markup=ADMIN_MENU)
    else:
        context.user_data.pop("new_region", None)
        await query.edit_message_text("Скасовано.", reply_markup=ADMIN_MENU)

    return ConversationHandler.END


# ──────────────────────────────────────
#  Edit region conversation
# ──────────────────────────────────────
async def edit_pick_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    region_id = int(query.data.replace("editreg_", ""))
    context.user_data["edit_region_id"] = region_id

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"editfield_{field}")]
            for field, label in FIELD_LABELS.items()
        ]
    )
    await query.edit_message_text("Оберіть поле для редагування:", reply_markup=keyboard)
    return EDIT_PICK_FIELD


async def edit_pick_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("editfield_", "")
    context.user_data["edit_field"] = field
    label = FIELD_LABELS.get(field, field)
    await query.edit_message_text(f"Введіть нове значення для '{label}':")
    return EDIT_VALUE


async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.pop("edit_field")
    region_id = context.user_data.pop("edit_region_id")
    raw = update.message.text.strip()

    # Validate numeric fields
    if field == "price":
        try:
            value = Decimal(raw.replace(",", "."))
        except InvalidOperation:
            await update.message.reply_text("Невірний формат. Введіть число:")
            context.user_data["edit_field"] = field
            context.user_data["edit_region_id"] = region_id
            return EDIT_VALUE
    elif field == "plots_number":
        try:
            value = int(raw)
        except ValueError:
            await update.message.reply_text("Невірний формат. Введіть ціле число:")
            context.user_data["edit_field"] = field
            context.user_data["edit_region_id"] = region_id
            return EDIT_VALUE
    else:
        value = raw

    async with async_session() as session:
        region = await session.get(Region, region_id)
        if region:
            setattr(region, field, value)
            await session.commit()
            await update.message.reply_text("Оновлено!", reply_markup=ADMIN_MENU)
        else:
            await update.message.reply_text(
                "Регіон не знайдено.", reply_markup=ADMIN_MENU
            )

    return ConversationHandler.END


# ──────────────────────────────────────
#  Cancel
# ──────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Скасовано. Натисніть /start щоб почати знову.")
    return ConversationHandler.END


# ──────────────────────────────────────
#  Build conversation handler
# ──────────────────────────────────────
def build_admin_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_login_start, pattern="^admin_login$"),
            CallbackQueryHandler(admin_menu_callback, pattern="^admin_(add|edit|back)$"),
        ],
        states={
            LOGIN_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_login_password)
            ],
            ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)
            ],
            ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)
            ],
            ADD_PLOTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plots)
            ],
            ADD_DESCRIBE: [
                MessageHandler(filters.TEXT, add_describe)
            ],
            ADD_LINK_MAP: [
                MessageHandler(filters.TEXT, add_link_map)
            ],
            ADD_LINK_YOUTUBE: [
                MessageHandler(filters.TEXT, add_link_youtube)
            ],
            ADD_CONFIRM: [
                CallbackQueryHandler(add_confirm, pattern="^confirm_(yes|no)$")
            ],
            EDIT_PICK_REGION: [
                CallbackQueryHandler(edit_pick_region, pattern="^editreg_")
            ],
            EDIT_PICK_FIELD: [
                CallbackQueryHandler(edit_pick_field, pattern="^editfield_")
            ],
            EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
