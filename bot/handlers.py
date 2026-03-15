from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from telegram import InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import ADMIN_PASSWORD
from bot.db import async_session
from bot.models import ActionLog, Realtor, Region, RegionPhoto, User

# --- Manual state constants ---
STATE_IDLE = "idle"
STATE_LOGIN_PASSWORD = "login_password"
STATE_ADD_NAME = "add_name"
STATE_ADD_PRICE = "add_price"
STATE_ADD_PLOTS = "add_plots"
STATE_ADD_SIZE = "add_size"
STATE_ADD_DESCRIBE = "add_describe"
STATE_ADD_LINK_MAP = "add_link_map"
STATE_ADD_LINK_YOUTUBE = "add_link_youtube"
STATE_EDIT_VALUE = "edit_value"
STATE_COPY_NEW_PRICE = "copy_new_price"
STATE_COPY_NEW_NAME = "copy_new_name"
STATE_CREATE_REALTOR_NAME = "create_realtor_name"
STATE_CREATE_REALTOR_PASSWORD = "create_realtor_password"
STATE_ADD_PHOTO = "add_photo"
STATE_EDIT_ADD_PHOTO = "edit_add_photo"

# --- Keyboards ---


async def _build_start_keyboard() -> InlineKeyboardMarkup:
    """Build start keyboard with unique region names from DB."""
    async with async_session() as session:
        regions = (await session.execute(select(Region))).scalars().all()
    unique_names = sorted(set(r.name for r in regions))
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"regionname_{name}")]
        for name in unique_names
    ]
    return InlineKeyboardMarkup(buttons)

ADMIN_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Додати новий", callback_data="admin_add")],
        [InlineKeyboardButton("Копіювати з новою ціною", callback_data="admin_copy_price")],
        [InlineKeyboardButton("Копіювати з новим ім'ям", callback_data="admin_copy_name")],
        [InlineKeyboardButton("Редагувати", callback_data="admin_edit")],
        [InlineKeyboardButton("Створити ріелтора", callback_data="admin_create_realtor")],
        [InlineKeyboardButton("Назад", callback_data="admin_back")],
    ]
)

REALTOR_MENU = InlineKeyboardMarkup(
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

DEFAULT_NAV_KEYBOARD = ReplyKeyboardMarkup(
    [["Головна сторінка", "Контакти"]],
    resize_keyboard=True,
)

FIELD_LABELS = {
    "name": "Назва",
    "price": "Ціна",
    "plots_number": "Кількість ділянок",
    "size": "Розмір (сотки)",
    "describe": "Опис",
    "link_map": "Посилання на карту",
    "link_youtube": "Посилання на YouTube",
    "photo_file_id": "Фото",
}


def _get_state(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("state", STATE_IDLE)


def _set_state(context: ContextTypes.DEFAULT_TYPE, state: str):
    context.user_data["state"] = state


def _get_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return ADMIN_MENU if context.user_data.get("role") == "admin" else REALTOR_MENU


async def _log_action(user_id: int, username: str | None, action: str):
    async with async_session() as session:
        log = ActionLog(user_id=user_id, username=username, action=action)
        session.add(log)
        await session.commit()


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

    # Send persistent navigation buttons
    await update.message.reply_text(
        "Вітаємо! Це бот першої земельної компанії.",
        reply_markup=DEFAULT_NAV_KEYBOARD,
    )

    keyboard = await _build_start_keyboard()
    await update.message.reply_text(
        "Будь ласка оберіть який регіон вас цікавить",
        reply_markup=keyboard,
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
    context.user_data.pop("new_region_photos", None)
    context.user_data.pop("edit_region_id", None)
    context.user_data.pop("edit_field", None)
    await update.message.reply_text("Скасовано. Натисніть /start щоб почати знову.")


# ──────────────────────────────────────
#  Region selection (public)
# ──────────────────────────────────────
async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("regionname_"):
        # Show all regions with this name (buttons: name — price$ — size сот.)
        name = data.replace("regionname_", "", 1)
        async with async_session() as session:
            regions = (
                await session.execute(select(Region).where(Region.name == name))
            ).scalars().all()
        buttons = [
            [InlineKeyboardButton(
                f"{r.name} — {r.price}$ — {r.size} сот.",
                callback_data=f"regiondetail_{r.id}",
            )]
            for r in regions
        ]
        buttons.append([InlineKeyboardButton("Назад", callback_data="region_back")])
        reply_markup = InlineKeyboardMarkup(buttons)
        msg_text = f"Ділянки у «{name}»:" if regions else "Немає ділянок у цьому регіоні."
        if not regions:
            reply_markup = await _build_start_keyboard()
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(msg_text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(msg_text, reply_markup=reply_markup)

    elif data.startswith("regiondetail_"):
        # Show full info about a specific region
        region_id = int(data.replace("regiondetail_", ""))
        async with async_session() as session:
            region = await session.get(Region, region_id)
            if not region:
                keyboard = await _build_start_keyboard()
                await query.edit_message_text("Регіон не знайдено.", reply_markup=keyboard)
                return
            photos_result = await session.execute(
                select(RegionPhoto)
                .where(RegionPhoto.region_id == region_id)
                .order_by(RegionPhoto.position)
            )
            photos = photos_result.scalars().all()
        text = (
            f"Назва: {region.name}\n"
            f"Ціна: {region.price}$\n"
            f"Кількість ділянок: {region.plots_number}\n"
            f"Розмір: {region.size} сот.\n"
            f"Опис: {region.describe or '—'}\n"
            f"Карта: {region.link_map or '—'}\n"
            f"YouTube: {region.link_youtube or '—'}"
        )
        back_btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Назад", callback_data=f"regionname_{region.name}")]]
        )
        chat_id = query.message.chat_id
        await query.message.delete()

        if photos:
            # Build media group: first photo gets the caption with region info
            media = []
            for i, p in enumerate(photos):
                if p.file_type == "photo":
                    file_input = p.file_id
                else:
                    tg_file = await context.bot.get_file(p.file_id)
                    file_bytes = await tg_file.download_as_bytearray()
                    file_input = bytes(file_bytes)
                media.append(InputMediaPhoto(
                    media=file_input,
                    caption=text if i == 0 else None,
                ))
            await context.bot.send_media_group(chat_id=chat_id, media=media)
            # Back button as a separate message (media groups don't support inline keyboards)
            await context.bot.send_message(chat_id=chat_id, text="Оберіть дію:", reply_markup=back_btn)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=back_btn)

    elif data == "region_back":
        keyboard = await _build_start_keyboard()
        msg_text = "Це бот першої земельної компанії, будь ласка оберіть який регіон вас цікавить"
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(msg_text, reply_markup=keyboard)
        else:
            await query.edit_message_text(msg_text, reply_markup=keyboard)


# ──────────────────────────────────────
#  Admin callback dispatcher
# ──────────────────────────────────────
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_add":
        await _handle_admin_add(query, context)
    elif data == "admin_copy_price":
        await _handle_copy_list(query, context, "price")
    elif data == "admin_copy_name":
        await _handle_copy_list(query, context, "name")
    elif data == "admin_edit":
        await _handle_admin_edit(query, context)
    elif data == "admin_create_realtor":
        await _handle_create_realtor(query, context)
    elif data == "admin_back":
        _set_state(context, STATE_IDLE)
        keyboard = await _build_start_keyboard()
        await query.edit_message_text(
            "Це бот першої земельної компанії, будь ласка оберіть який регіон вас цікавить",
            reply_markup=keyboard,
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
    elif data == "addphoto_done":
        _set_state(context, STATE_IDLE)
        photos = context.user_data.get("new_region_photos", [])
        summary = _region_summary(context.user_data.get("new_region", {}), photos)
        await query.edit_message_text(f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD)
    elif data.startswith("photomgr_"):
        region_id = int(data.replace("photomgr_", ""))
        _set_state(context, STATE_IDLE)
        text, kb = await _photo_mgmt(region_id, context)
        await query.edit_message_text(text, reply_markup=kb)
    elif data.startswith("photodel_"):
        await _handle_photodel(query, context)
    elif data.startswith("photoadd_"):
        region_id = int(data.replace("photoadd_", ""))
        context.user_data["edit_region_id"] = region_id
        _set_state(context, STATE_EDIT_ADD_PHOTO)
        done_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Готово", callback_data=f"photomgr_{region_id}")]]
        )
        await query.edit_message_text(
            "Надішліть фото (PNG/JPG/WebP), можна кілька по одному:", reply_markup=done_kb
        )


# ──────────────────────────────────────
#  Create realtor
# ──────────────────────────────────────
async def _handle_create_realtor(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("Тільки адміністратор може створювати ріелторів.")
            return

    _set_state(context, STATE_CREATE_REALTOR_NAME)
    await query.edit_message_text("Введіть ім'я ріелтора:")


# ──────────────────────────────────────
#  /admin command
# ──────────────────────────────────────
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    async with async_session() as session:
        user = await session.get(User, tg_user.id)
        if user and user.is_admin:
            context.user_data["role"] = "admin"
            await update.message.reply_text("Панель адміністратора:", reply_markup=ADMIN_MENU)
            return
        if user and user.is_realtor:
            context.user_data["role"] = "realtor"
            await update.message.reply_text("Панель ріелтора:", reply_markup=REALTOR_MENU)
            return

    _set_state(context, STATE_LOGIN_PASSWORD)
    await update.message.reply_text("Введіть пароль:")


# ──────────────────────────────────────
#  Admin add / edit entry
# ──────────────────────────────────────
async def _handle_admin_add(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or (not user.is_admin and not user.is_realtor):
            await query.edit_message_text("У вас немає прав адміністратора.")
            return

    context.user_data["new_region"] = {}
    context.user_data["new_region_photos"] = []
    _set_state(context, STATE_ADD_NAME)
    await query.edit_message_text("Введіть назву:")


async def _handle_admin_edit(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or (not user.is_admin and not user.is_realtor):
            await query.edit_message_text("У вас немає прав адміністратора.")
            return

    async with async_session() as session:
        regions = (await session.execute(select(Region))).scalars().all()
    if not regions:
        await query.edit_message_text(
            "Немає регіонів для редагування.", reply_markup=_get_menu(context)
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
        if not user or (not user.is_admin and not user.is_realtor):
            await query.edit_message_text("У вас немає прав адміністратора.")
            return

    async with async_session() as session:
        regions = (await session.execute(select(Region))).scalars().all()
    if not regions:
        await query.edit_message_text(
            "Немає регіонів для копіювання.", reply_markup=_get_menu(context)
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
            await query.edit_message_text("Регіон не знайдено.", reply_markup=_get_menu(context))
            return
        photos_result = await session.execute(
            select(RegionPhoto)
            .where(RegionPhoto.region_id == region_id)
            .order_by(RegionPhoto.position)
        )
        photo_ids = [(p.file_id, p.file_type) for p in photos_result.scalars().all()]
        context.user_data["new_region"] = {
            "name": region.name,
            "price": region.price,
            "plots_number": region.plots_number,
            "size": region.size,
            "describe": region.describe,
            "link_map": region.link_map,
            "link_youtube": region.link_youtube,
        }
        context.user_data["new_region_photos"] = photo_ids

    if copy_field == "price":
        _set_state(context, STATE_COPY_NEW_PRICE)
        await query.edit_message_text("Введіть нову ціну:")
    else:
        _set_state(context, STATE_COPY_NEW_NAME)
        await query.edit_message_text("Введіть нове ім'я:")


# ──────────────────────────────────────
#  Photo management helpers
# ──────────────────────────────────────
async def _photo_mgmt(region_id: int, context) -> tuple:
    """Return (text, keyboard) for the photo management menu."""
    async with async_session() as session:
        result = await session.execute(
            select(RegionPhoto)
            .where(RegionPhoto.region_id == region_id)
            .order_by(RegionPhoto.position)
        )
        photos = result.scalars().all()
        rows = [
            [InlineKeyboardButton(f"❌ Фото {i + 1}", callback_data=f"photodel_{p.id}")]
            for i, p in enumerate(photos)
        ]
    rows.append([InlineKeyboardButton("➕ Додати фото", callback_data=f"photoadd_{region_id}")])
    region_id_stored = context.user_data.get("edit_region_id", region_id)
    rows.append([InlineKeyboardButton("← Назад", callback_data=f"editreg_{region_id_stored}")])
    count = len(photos)
    text = f"Фото ділянки ({count} шт.):" if count else "Фото немає."
    return text, InlineKeyboardMarkup(rows)


async def _handle_photodel(query, context):
    photo_id = int(query.data.replace("photodel_", ""))
    async with async_session() as session:
        photo = await session.get(RegionPhoto, photo_id)
        if not photo:
            await query.answer("Фото вже видалено.")
            return
        region_id = photo.region_id
        await session.delete(photo)
        await session.commit()
    await _log_action(
        query.from_user.id,
        query.from_user.username,
        f"Видалив фото #{photo_id} регіону #{region_id}",
    )
    text, kb = await _photo_mgmt(region_id, context)
    await query.edit_message_text(text, reply_markup=kb)


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
    if field == "photo_file_id":
        region_id = context.user_data.get("edit_region_id")
        text, kb = await _photo_mgmt(region_id, context)
        await query.edit_message_text(text, reply_markup=kb)
        return
    else:
        _set_state(context, STATE_EDIT_VALUE)
        await query.edit_message_text(f"Введіть нове значення для '{label}':")


# ──────────────────────────────────────
#  Add region confirm
# ──────────────────────────────────────
async def _handle_add_confirm(query, context):
    if query.data == "confirm_yes":
        data = context.user_data.pop("new_region", {})
        photos = context.user_data.pop("new_region_photos", [])
        region = Region(**data)
        async with async_session() as session:
            session.add(region)
            await session.flush()  # populate region.id
            for i, (fid, ftype) in enumerate(photos):
                session.add(RegionPhoto(region_id=region.id, file_id=fid, file_type=ftype, position=i))
            await session.commit()
        await _log_action(
            query.from_user.id,
            query.from_user.username,
            f"Зберіг регіон «{region.name}» ({len(photos)} фото)",
        )
        await query.edit_message_text("Регіон збережено!", reply_markup=_get_menu(context))
    else:
        context.user_data.pop("new_region", None)
        context.user_data.pop("new_region_photos", None)
        await query.edit_message_text("Скасовано.", reply_markup=_get_menu(context))
    _set_state(context, STATE_IDLE)


# ──────────────────────────────────────
#  Text message router (state machine)
# ──────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # --- Default navigation buttons ---
    if text == "Головна сторінка":
        _set_state(context, STATE_IDLE)
        keyboard = await _build_start_keyboard()
        await update.message.reply_text(
            "Будь ласка оберіть який регіон вас цікавить",
            reply_markup=keyboard,
        )
        return
    if text == "Контакти":
        await update.message.reply_text(
            "Зв'яжіться з нами:\n"
            "https://t.me/dilyanki_odesa",
            reply_markup=DEFAULT_NAV_KEYBOARD,
        )
        return

    state = _get_state(context)

    if state == STATE_COPY_NEW_PRICE:
        await _on_copy_new_price(update, context)
    elif state == STATE_COPY_NEW_NAME:
        await _on_copy_new_name(update, context)
    elif state == STATE_ADD_PHOTO:
        done_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Готово", callback_data="addphoto_done")]]
        )
        await update.message.reply_text(
            "Надішліть фото або натисніть кнопку:", reply_markup=done_kb
        )
    elif state == STATE_EDIT_ADD_PHOTO:
        region_id = context.user_data.get("edit_region_id")
        done_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Готово", callback_data=f"photomgr_{region_id}")]]
        )
        await update.message.reply_text(
            "Надішліть фото або натисніть кнопку:", reply_markup=done_kb
        )
    elif state == STATE_CREATE_REALTOR_NAME:
        await _on_create_realtor_name(update, context)
    elif state == STATE_CREATE_REALTOR_PASSWORD:
        await _on_create_realtor_password(update, context)
    elif state == STATE_LOGIN_PASSWORD:
        await _on_login_password(update, context)
    elif state == STATE_ADD_NAME:
        await _on_add_name(update, context)
    elif state == STATE_ADD_PRICE:
        await _on_add_price(update, context)
    elif state == STATE_ADD_PLOTS:
        await _on_add_plots(update, context)
    elif state == STATE_ADD_SIZE:
        await _on_add_size(update, context)
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
    tg_user = update.effective_user

    if password == ADMIN_PASSWORD:
        async with async_session() as session:
            user = await session.get(User, tg_user.id)
            if user:
                user.is_admin = True
                await session.commit()
        _set_state(context, STATE_IDLE)
        context.user_data["role"] = "admin"
        await _log_action(tg_user.id, tg_user.username, "Увійшов як адмін")
        await update.message.reply_text("Ви увійшли як адмін.", reply_markup=ADMIN_MENU)
        return

    async with async_session() as session:
        realtors = (await session.execute(select(Realtor))).scalars().all()
    matched = next((r for r in realtors if r.password == password), None)
    if matched:
        async with async_session() as session:
            user = await session.get(User, tg_user.id)
            if user:
                user.is_realtor = True
                await session.commit()
        _set_state(context, STATE_IDLE)
        context.user_data["role"] = "realtor"
        await _log_action(tg_user.id, tg_user.username, f"Увійшов як ріелтор «{matched.name}»")
        await update.message.reply_text(
            f"Ви увійшли як ріелтор «{matched.name}».", reply_markup=REALTOR_MENU
        )
        return

    _set_state(context, STATE_IDLE)
    await update.message.reply_text("Невірний пароль. Спробуйте /admin щоб спробувати знову.")


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
    _set_state(context, STATE_ADD_SIZE)
    await update.message.reply_text("Введіть розмір ділянки (сотки):")


async def _on_add_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["new_region"]["size"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Невірний формат. Введіть ціле число:")
        return
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
    _set_state(context, STATE_ADD_PHOTO)
    skip_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏩ Пропустити / Готово", callback_data="addphoto_done")]]
    )
    await update.message.reply_text(
        "Надішліть фото ділянки (PNG/JPG/WebP), можна кілька по одному:",
        reply_markup=skip_kb,
    )


def _region_summary(data: dict, photos: list | None = None) -> str:
    count = len(photos) if photos else 0
    photo_str = f"є ({count} шт.)" if count else "немає"
    return (
        f"Назва: {data.get('name', '—')}\n"
        f"Ціна: {data.get('price', '—')}\n"
        f"Кількість ділянок: {data.get('plots_number', '—')}\n"
        f"Розмір (сотки): {data.get('size', 5)}\n"
        f"Опис: {data.get('describe') or '—'}\n"
        f"Карта: {data.get('link_map') or '—'}\n"
        f"YouTube: {data.get('link_youtube') or '—'}\n"
        f"Фото: {photo_str}"
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
    photos = context.user_data.get("new_region_photos", [])
    summary = _region_summary(context.user_data["new_region"], photos)
    await update.message.reply_text(
        f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD
    )


async def _on_copy_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_region"]["name"] = update.message.text.strip()
    _set_state(context, STATE_IDLE)
    photos = context.user_data.get("new_region_photos", [])
    summary = _region_summary(context.user_data["new_region"], photos)
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
    elif field in ("plots_number", "size"):
        try:
            value = int(raw)
        except ValueError:
            await update.message.reply_text("Невірний формат. Введіть ціле число:")
            return
    else:
        value = raw

    tg_user = update.effective_user
    async with async_session() as session:
        region = await session.get(Region, region_id)
        if region:
            setattr(region, field, value)
            await session.commit()
            await _log_action(
                tg_user.id,
                tg_user.username,
                f"Відредагував поле «{field}» регіону «{region.name}»",
            )
            await update.message.reply_text("Оновлено!", reply_markup=_get_menu(context))
        else:
            await update.message.reply_text(
                "Регіон не знайдено.", reply_markup=_get_menu(context)
            )

    _set_state(context, STATE_IDLE)
    context.user_data.pop("edit_field", None)
    context.user_data.pop("edit_region_id", None)


# ──────────────────────────────────────
#  Create realtor steps
# ──────────────────────────────────────
async def _on_create_realtor_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_realtor_name"] = update.message.text.strip()
    _set_state(context, STATE_CREATE_REALTOR_PASSWORD)
    await update.message.reply_text("Введіть пароль для ріелтора:")


async def _on_create_realtor_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.pop("new_realtor_name", "")
    password = update.message.text.strip()
    tg_user = update.effective_user

    async with async_session() as session:
        realtor = Realtor(name=name, password=password, created_by=tg_user.id)
        session.add(realtor)
        await session.commit()

    _set_state(context, STATE_IDLE)
    await _log_action(tg_user.id, tg_user.username, f"Створив ріелтора «{name}»")
    await update.message.reply_text(
        f"Ріелтор «{name}» створений.\nПароль: {password}",
        reply_markup=ADMIN_MENU,
    )


# ──────────────────────────────────────
#  Photo message handler
# ──────────────────────────────────────
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = _get_state(context)
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
    else:
        return

    if state == STATE_ADD_PHOTO:
        photos = context.user_data.setdefault("new_region_photos", [])
        photos.append((file_id, file_type))
        done_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Готово", callback_data="addphoto_done")]]
        )
        await update.message.reply_text(
            f"Фото {len(photos)} отримано! Надішліть ще або:", reply_markup=done_kb
        )
        return

    if state == STATE_EDIT_ADD_PHOTO:
        region_id = context.user_data.get("edit_region_id")
        async with async_session() as session:
            result = await session.execute(
                select(RegionPhoto)
                .where(RegionPhoto.region_id == region_id)
                .order_by(RegionPhoto.position.desc())
            )
            last = result.scalars().first()
            next_pos = (last.position + 1) if last else 0
            session.add(RegionPhoto(region_id=region_id, file_id=file_id, file_type=file_type, position=next_pos))
            await session.commit()
        await _log_action(
            update.effective_user.id,
            update.effective_user.username,
            f"Додав фото до регіону #{region_id}",
        )
        done_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Готово", callback_data=f"photomgr_{region_id}")]]
        )
        await update.message.reply_text(
            "Фото збережено! Надішліть ще або:", reply_markup=done_kb
        )
        return


