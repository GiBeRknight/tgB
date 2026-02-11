from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import ADMIN_PASSWORD
from bot.db import async_session
from bot.models import Region, User

# --- Manual state constants ---
STATE_IDLE = "idle"
STATE_LOGIN_PASSWORD = "login_password"
STATE_ADD_NAME = "add_name"
STATE_ADD_PRICE = "add_price"
STATE_ADD_PLOTS = "add_plots"
STATE_ADD_DESCRIBE = "add_describe"
STATE_ADD_LINK_MAP = "add_link_map"
STATE_ADD_LINK_YOUTUBE = "add_link_youtube"
STATE_EDIT_VALUE = "edit_value"
STATE_COPY_NEW_PRICE = "copy_new_price"
STATE_COPY_NEW_NAME = "copy_new_name"

# --- Keyboards ---
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
        [InlineKeyboardButton("Копіювати з новою ціною", callback_data="admin_copy_price")],
        [InlineKeyboardButton("Копіювати з новим ім'ям", callback_data="admin_copy_name")],
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


def _get_state(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("state", STATE_IDLE)


def _set_state(context: ContextTypes.DEFAULT_TYPE, state: str):
    context.user_data["state"] = state


# ──────────────────────────────────────
#  /start
# ──────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    _set_state(context, STATE_IDLE)
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
#  /help
# ──────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Запустити бота\n"
        "/help - Показати цю підказку\n"
        "/cancel - Скасувати поточну дію"
    )


# ──────────────────────────────────────
#  /cancel
# ──────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _set_state(context, STATE_IDLE)
    context.user_data.pop("new_region", None)
    context.user_data.pop("edit_region_id", None)
    context.user_data.pop("edit_field", None)
    await update.message.reply_text("Скасовано. Натисніть /start щоб почати знову.")


# ──────────────────────────────────────
#  Region selection (public)
# ──────────────────────────────────────
async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    messages = {
        "region_fontanka1": "Усі земельні ділянки у Фонтанці1",
        "region_fontanka2": "Усі земельні ділянки у Фонтанці2",
        "region_sukhyi_lyman": "Усі земельні ділянки у Сухому Лимані",
    }
    text = messages.get(query.data, query.data)
    await query.edit_message_text(text)


# ──────────────────────────────────────
#  Admin callback dispatcher
# ──────────────────────────────────────
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_login":
        await _handle_admin_login(query, context)
    elif data == "admin_add":
        await _handle_admin_add(query, context)
    elif data == "admin_copy_price":
        await _handle_copy_list(query, context, "price")
    elif data == "admin_copy_name":
        await _handle_copy_list(query, context, "name")
    elif data == "admin_edit":
        await _handle_admin_edit(query, context)
    elif data == "admin_back":
        _set_state(context, STATE_IDLE)
        await query.edit_message_text(
            "Це бот першої земельної компанії, будь ласка оберіть який регіон вас цікавить",
            reply_markup=START_KEYBOARD,
        )
    elif data.startswith("copyreg_price_"):
        await _handle_copy_pick(query, context, "price")
    elif data.startswith("copyreg_name_"):
        await _handle_copy_pick(query, context, "name")
    elif data.startswith("editreg_"):
        await _handle_edit_pick_region(query, context)
    elif data.startswith("editfield_"):
        await _handle_edit_pick_field(query, context)
    elif data in ("confirm_yes", "confirm_no"):
        await _handle_add_confirm(query, context)


# ──────────────────────────────────────
#  Admin login
# ──────────────────────────────────────
async def _handle_admin_login(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if user and user.is_admin:
            await query.edit_message_text(
                "Ви вже адміністратор.", reply_markup=ADMIN_MENU
            )
            return

    _set_state(context, STATE_LOGIN_PASSWORD)
    await query.edit_message_text("Введіть пароль адміністратора:")


# ──────────────────────────────────────
#  Admin add / edit entry
# ──────────────────────────────────────
async def _handle_admin_add(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return

    context.user_data["new_region"] = {}
    _set_state(context, STATE_ADD_NAME)
    await query.edit_message_text("Введіть назву:")


async def _handle_admin_edit(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return

    async with async_session() as session:
        regions = (await session.execute(select(Region))).scalars().all()
    if not regions:
        await query.edit_message_text(
            "Немає регіонів для редагування.", reply_markup=ADMIN_MENU
        )
        return
    buttons = [
        [InlineKeyboardButton(
            f"{r.name} — {r.price}$" if r.price else r.name,
            callback_data=f"editreg_{r.id}",
        )]
        for r in regions
    ]
    buttons.append([InlineKeyboardButton("Назад", callback_data="admin_back")])
    keyboard = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Оберіть регіон:", reply_markup=keyboard)


# ──────────────────────────────────────
#  Copy region (with new price / name)
# ──────────────────────────────────────
async def _handle_copy_list(query, context, copy_field: str):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return

    async with async_session() as session:
        regions = (await session.execute(select(Region))).scalars().all()
    if not regions:
        await query.edit_message_text(
            "Немає регіонів для копіювання.", reply_markup=ADMIN_MENU
        )
        return
    buttons = [
        [InlineKeyboardButton(
            f"{r.name} — {r.price}$" if r.price else r.name,
            callback_data=f"copyreg_{copy_field}_{r.id}",
        )]
        for r in regions
    ]
    back_cb = "admin_copy_price" if copy_field == "price" else "admin_copy_name"
    buttons.append([InlineKeyboardButton("Назад", callback_data="admin_back")])
    keyboard = InlineKeyboardMarkup(buttons)
    label = "ціною" if copy_field == "price" else "ім'ям"
    await query.edit_message_text(
        f"Оберіть регіон для копіювання з новою {label}:", reply_markup=keyboard
    )


async def _handle_copy_pick(query, context, copy_field: str):
    prefix = f"copyreg_{copy_field}_"
    region_id = int(query.data.replace(prefix, ""))

    async with async_session() as session:
        region = await session.get(Region, region_id)
        if not region:
            await query.edit_message_text("Регіон не знайдено.", reply_markup=ADMIN_MENU)
            return
        context.user_data["new_region"] = {
            "name": region.name,
            "price": region.price,
            "plots_number": region.plots_number,
            "describe": region.describe,
            "link_map": region.link_map,
            "link_youtube": region.link_youtube,
        }

    if copy_field == "price":
        _set_state(context, STATE_COPY_NEW_PRICE)
        await query.edit_message_text("Введіть нову ціну:")
    else:
        _set_state(context, STATE_COPY_NEW_NAME)
        await query.edit_message_text("Введіть нове ім'я:")


# ──────────────────────────────────────
#  Edit region callbacks
# ──────────────────────────────────────
async def _handle_edit_pick_region(query, context):
    region_id = int(query.data.replace("editreg_", ""))
    context.user_data["edit_region_id"] = region_id

    buttons = [
        [InlineKeyboardButton(label, callback_data=f"editfield_{field}")]
        for field, label in FIELD_LABELS.items()
    ]
    buttons.append([InlineKeyboardButton("Назад", callback_data="admin_edit")])
    keyboard = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(
        "Оберіть поле для редагування:", reply_markup=keyboard
    )


async def _handle_edit_pick_field(query, context):
    field = query.data.replace("editfield_", "")
    context.user_data["edit_field"] = field
    label = FIELD_LABELS.get(field, field)
    _set_state(context, STATE_EDIT_VALUE)
    await query.edit_message_text(f"Введіть нове значення для '{label}':")


# ──────────────────────────────────────
#  Add region confirm
# ──────────────────────────────────────
async def _handle_add_confirm(query, context):
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
    _set_state(context, STATE_IDLE)


# ──────────────────────────────────────
#  Text message router (state machine)
# ──────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = _get_state(context)

    if state == STATE_COPY_NEW_PRICE:
        await _on_copy_new_price(update, context)
    elif state == STATE_COPY_NEW_NAME:
        await _on_copy_new_name(update, context)
    elif state == STATE_LOGIN_PASSWORD:
        await _on_login_password(update, context)
    elif state == STATE_ADD_NAME:
        await _on_add_name(update, context)
    elif state == STATE_ADD_PRICE:
        await _on_add_price(update, context)
    elif state == STATE_ADD_PLOTS:
        await _on_add_plots(update, context)
    elif state == STATE_ADD_DESCRIBE:
        await _on_add_describe(update, context)
    elif state == STATE_ADD_LINK_MAP:
        await _on_add_link_map(update, context)
    elif state == STATE_ADD_LINK_YOUTUBE:
        await _on_add_link_youtube(update, context)
    elif state == STATE_EDIT_VALUE:
        await _on_edit_value(update, context)


# ──────────────────────────────────────
#  Login password
# ──────────────────────────────────────
async def _on_login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()

    if password != ADMIN_PASSWORD:
        _set_state(context, STATE_IDLE)
        await update.message.reply_text(
            "Невірний пароль. Спробуйте /start щоб почати знову."
        )
        return

    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if user:
            user.is_admin = True
            await session.commit()

    _set_state(context, STATE_IDLE)
    await update.message.reply_text("Ви увійшли як адмін.", reply_markup=ADMIN_MENU)


# ──────────────────────────────────────
#  Add region steps
# ──────────────────────────────────────
async def _on_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_region"]["name"] = update.message.text.strip()
    _set_state(context, STATE_ADD_PRICE)
    await update.message.reply_text("Введіть ціну:")


async def _on_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = Decimal(update.message.text.strip().replace(",", "."))
    except InvalidOperation:
        await update.message.reply_text("Невірний формат. Введіть число:")
        return
    context.user_data["new_region"]["price"] = price
    _set_state(context, STATE_ADD_PLOTS)
    await update.message.reply_text("Введіть кількість ділянок:")


async def _on_add_plots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        plots = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Невірний формат. Введіть ціле число:")
        return
    context.user_data["new_region"]["plots_number"] = plots
    _set_state(context, STATE_ADD_DESCRIBE)
    await update.message.reply_text("Введіть опис (або /skip):")


async def _on_add_describe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["describe"] = None if text == "/skip" else text
    _set_state(context, STATE_ADD_LINK_MAP)
    await update.message.reply_text("Введіть посилання на карту (або /skip):")


async def _on_add_link_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["link_map"] = None if text == "/skip" else text
    _set_state(context, STATE_ADD_LINK_YOUTUBE)
    await update.message.reply_text("Введіть посилання на YouTube (або /skip):")


async def _on_add_link_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["link_youtube"] = None if text == "/skip" else text

    _set_state(context, STATE_IDLE)
    summary = _region_summary(context.user_data["new_region"])
    await update.message.reply_text(
        f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD
    )


def _region_summary(data: dict) -> str:
    return (
        f"Назва: {data.get('name', '—')}\n"
        f"Ціна: {data.get('price', '—')}\n"
        f"Кількість ділянок: {data.get('plots_number', '—')}\n"
        f"Опис: {data.get('describe') or '—'}\n"
        f"Карта: {data.get('link_map') or '—'}\n"
        f"YouTube: {data.get('link_youtube') or '—'}"
    )


# ──────────────────────────────────────
#  Copy region – enter new value
# ──────────────────────────────────────
async def _on_copy_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = Decimal(update.message.text.strip().replace(",", "."))
    except InvalidOperation:
        await update.message.reply_text("Невірний формат. Введіть число:")
        return
    context.user_data["new_region"]["price"] = price
    _set_state(context, STATE_IDLE)
    summary = _region_summary(context.user_data["new_region"])
    await update.message.reply_text(
        f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD
    )


async def _on_copy_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_region"]["name"] = update.message.text.strip()
    _set_state(context, STATE_IDLE)
    summary = _region_summary(context.user_data["new_region"])
    await update.message.reply_text(
        f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD
    )


# ──────────────────────────────────────
#  Edit region value
# ──────────────────────────────────────
async def _on_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("edit_field")
    region_id = context.user_data.get("edit_region_id")
    raw = update.message.text.strip()

    if field == "price":
        try:
            value = Decimal(raw.replace(",", "."))
        except InvalidOperation:
            await update.message.reply_text("Невірний формат. Введіть число:")
            return
    elif field == "plots_number":
        try:
            value = int(raw)
        except ValueError:
            await update.message.reply_text("Невірний формат. Введіть ціле число:")
            return
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

    _set_state(context, STATE_IDLE)
    context.user_data.pop("edit_field", None)
    context.user_data.pop("edit_region_id", None)
