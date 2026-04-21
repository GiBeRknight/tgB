import logging
import re
import bcrypt
import httpx
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from telegram import InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_PASSWORD, BOOKING_CONTACT_FALLBACK_URL, BOOKING_CONTACT_ID
from bot.db import async_session
from bot.models import ActionLog, Realtor, Region, RegionGroup, RegionPhoto, User

logger = logging.getLogger(__name__)

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
STATE_ADD_SCHEME_PHOTO = "add_scheme_photo"
STATE_EDIT_SCHEME_PHOTO = "edit_scheme_photo"
STATE_ADD_LINK_DOC = "add_link_doc"
STATE_ADD_GROUP = "add_group"
STATE_GROUP_ADD_LABEL = "group_add_label"

# --- Keyboards ---


async def _build_start_keyboard() -> InlineKeyboardMarkup:
    """Build start keyboard: one button per used group, plus buttons for ungrouped regions."""
    async with async_session() as session:
        regions = (await session.execute(select(Region))).scalars().all()
        groups = (await session.execute(select(RegionGroup))).scalars().all()

    groups_by_id = {g.id: g for g in groups}
    used_group_ids: set[int] = set()
    ungrouped_names: set[str] = set()

    for r in regions:
        if r.group_id is not None and r.group_id in groups_by_id:
            used_group_ids.add(r.group_id)
        else:
            ungrouped_names.add(r.name)

    buttons: list[list[InlineKeyboardButton]] = []
    for g in sorted((groups_by_id[gid] for gid in used_group_ids), key=lambda x: x.label):
        buttons.append([InlineKeyboardButton(g.label, callback_data=f"regiongroup_{g.id}")])
    for name in sorted(ungrouped_names):
        buttons.append([InlineKeyboardButton(name, callback_data=f"regionname_{name}")])

    return InlineKeyboardMarkup(buttons)

ADMIN_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Переглянути ділянки", callback_data="admin_view_regions")],
        [InlineKeyboardButton("Додати новий", callback_data="admin_add")],
        [InlineKeyboardButton("Копіювати з новою ціною", callback_data="admin_copy_price")],
        [InlineKeyboardButton("Копіювати з новим ім'ям", callback_data="admin_copy_name")],
        [InlineKeyboardButton("Редагувати", callback_data="admin_edit")],
        [InlineKeyboardButton("Створити ріелтора", callback_data="admin_create_realtor")],
        [InlineKeyboardButton("Групи регіонів", callback_data="admin_groups")],
    ]
)

REALTOR_MENU = None  # Realtors see the same view as regular users (with extra info)

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

ADMIN_NAV_KEYBOARD = ReplyKeyboardMarkup(
    [["Головна сторінка", "Контакти"], ["Адмін-панель"]],
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
    "link_doc": "Документ доступності (Google Drive)",
    "scheme_photo_id": "Фото-схема",
}

OPTIONAL_EDIT_FIELDS = {"describe", "link_map", "link_youtube", "link_doc"}


def _get_state(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("state", STATE_IDLE)


def _set_state(context: ContextTypes.DEFAULT_TYPE, state: str):
    context.user_data["state"] = state


def _get_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return ADMIN_MENU


async def _log_action(user_id: int, username: str | None, action: str):
    async with async_session() as session:
        log = ActionLog(user_id=user_id, username=username, action=action)
        session.add(log)
        await session.commit()


def _fmt_size(v) -> str:
    """Format Decimal/number without trailing zeros."""
    if v is None:
        return "—"
    s = str(v)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


async def _nav_keyboard_for(user_id: int) -> ReplyKeyboardMarkup:
    """Return the admin nav keyboard if the user is an admin, else the default."""
    async with async_session() as session:
        user = await session.get(User, user_id)
    return ADMIN_NAV_KEYBOARD if user and user.is_admin else DEFAULT_NAV_KEYBOARD


async def _fetch_drive_etag(url: str) -> str | None:
    """Return an identifier (ETag or Content-Length) for the file at the URL, or None."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            r = await client.head(url)
        etag = r.headers.get("etag") or r.headers.get("content-length")
        return etag
    except Exception as exc:
        logger.warning("HEAD %s failed: %s", url, exc)
        return None


async def _send_region_doc(bot, chat_id: int, region: Region) -> None:
    """Send the accessibility document, using cached Telegram file_id when possible."""
    if not region.link_doc:
        return
    download_url = _gdrive_to_download(region.link_doc)
    current_etag = await _fetch_drive_etag(download_url)

    # Fast path: etag matches cache → send by file_id
    if region.doc_file_id and current_etag and current_etag == region.doc_etag:
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=region.doc_file_id,
                caption="📄 Документ доступності",
            )
            return
        except Exception as exc:
            logger.warning("Cached file_id send failed for region %s: %s", region.id, exc)

    # Full path: send by URL, capture new file_id
    try:
        msg = await bot.send_document(
            chat_id=chat_id,
            document=download_url,
            caption="📄 Документ доступності",
        )
    except Exception as exc:
        logger.warning("Doc send failed for region %s: %s", region.id, exc)
        return

    new_file_id = msg.document.file_id if msg and msg.document else None
    if new_file_id:
        async with async_session() as session:
            fresh = await session.get(Region, region.id)
            if fresh:
                fresh.doc_file_id = new_file_id
                fresh.doc_etag = current_etag
                await session.commit()


def _gdrive_to_download(url: str) -> str:
    """Convert a Google Drive view/share URL to a direct download URL."""
    # Pattern: https://drive.google.com/file/d/FILE_ID/view...
    m = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    # Pattern: https://drive.google.com/open?id=FILE_ID
    m = re.search(r"drive\.google\.com/open\?id=([^&]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


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
    nav_kb = ADMIN_NAV_KEYBOARD if user.is_admin else DEFAULT_NAV_KEYBOARD
    await update.message.reply_text(
        "Вітаємо! Це бот першої земельної компанії.",
        reply_markup=nav_kb,
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
#  /skip
# ──────────────────────────────────────
async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = _get_state(context)

    if state == STATE_ADD_DESCRIBE:
        await _on_add_describe(update, context)
        return
    if state == STATE_ADD_LINK_MAP:
        await _on_add_link_map(update, context)
        return
    if state == STATE_ADD_LINK_YOUTUBE:
        await _on_add_link_youtube(update, context)
        return
    if state == STATE_ADD_LINK_DOC:
        await _on_add_link_doc(update, context)
        return

    if state == STATE_EDIT_VALUE:
        field = context.user_data.get("edit_field")
        region_id = context.user_data.get("edit_region_id")
        if field not in OPTIONAL_EDIT_FIELDS:
            await update.message.reply_text("Це поле не можна очистити.")
            return
        tg_user = update.effective_user
        async with async_session() as session:
            region = await session.get(Region, region_id)
            if not region:
                await update.message.reply_text(
                    "Регіон не знайдено.", reply_markup=_get_menu(context)
                )
                _set_state(context, STATE_IDLE)
                context.user_data.pop("edit_field", None)
                return
            setattr(region, field, None)
            if field == "link_doc":
                region.doc_file_id = None
                region.doc_etag = None
            await session.commit()
            region_name = region.name
        await _log_action(
            tg_user.id, tg_user.username, f"Очистив поле «{field}» регіону «{region_name}»"
        )
        await update.message.reply_text(
            "Очищено! Оберіть поле для редагування:",
            reply_markup=_edit_fields_keyboard(region_id),
        )
        _set_state(context, STATE_IDLE)
        context.user_data.pop("edit_field", None)
        return


# ──────────────────────────────────────
#  Region selection (public)
# ──────────────────────────────────────
async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("regiongroup_"):
        group_id = int(data.replace("regiongroup_", "", 1))
        async with async_session() as session:
            group = await session.get(RegionGroup, group_id)
            regions = (
                await session.execute(
                    select(Region).where(Region.group_id == group_id)
                )
            ).scalars().all()
        if not group:
            keyboard = await _build_start_keyboard()
            await query.edit_message_text("Групу не знайдено.", reply_markup=keyboard)
            return
        sub_names = sorted(set(r.name for r in regions))
        buttons = [
            [InlineKeyboardButton(name, callback_data=f"regionname_{name}")]
            for name in sub_names
        ]
        buttons.append([InlineKeyboardButton("Назад", callback_data="region_back")])
        reply_markup = InlineKeyboardMarkup(buttons)
        msg_text = f"Оберіть локацію в «{group.label}»:"
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(msg_text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(msg_text, reply_markup=reply_markup)

    elif data.startswith("regionname_"):
        # Show all regions with this name (buttons: name — price$ — size сот.)
        name = data.replace("regionname_", "", 1)
        async with async_session() as session:
            regions = (
                await session.execute(select(Region).where(Region.name == name))
            ).scalars().all()
        buttons = [
            [InlineKeyboardButton(
                f"{r.name} — {r.price}$ — {_fmt_size(r.size)} сот.",
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
        map_line = f'Карта: <a href="{region.link_map}">Переглянути на карті</a>' if region.link_map else "Карта: —"
        yt_line = f'YouTube: <a href="{region.link_youtube}">Переглянути відео</a>' if region.link_youtube else "YouTube: —"
        role = context.user_data.get("role")
        is_privileged = role in ("admin", "realtor")
        text = (
            f"Назва: {region.name}\n"
            f"Ціна за сотку: {region.price}$\n"
        )
        if is_privileged:
            text += f"Кількість ділянок: {region.plots_number}\n"
        text += (
            f"Розмір: {_fmt_size(region.size)} сот.\n"
            f"Опис: {region.describe or '—'}\n"
            f"{map_line}\n"
            f"{yt_line}"
        )
        nav_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("Назад", callback_data=f"regionname_{region.name}"),
            InlineKeyboardButton("Забронювати", callback_data=f"regionbook_{region.id}"),
            InlineKeyboardButton("Головна", callback_data="region_back"),
        ]])
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
                    parse_mode="HTML" if i == 0 else None,
                ))
            await context.bot.send_media_group(chat_id=chat_id, media=media)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

        # Send scheme photo for admins/realtors
        if is_privileged and region.scheme_photo_id:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=region.scheme_photo_id,
                caption="Фото-схема ділянки",
            )

        # Send accessibility document (cached via file_id when Drive file unchanged)
        if is_privileged and region.link_doc:
            await _send_region_doc(context.bot, chat_id, region)

        await context.bot.send_message(chat_id=chat_id, text="Оберіть дію:", reply_markup=nav_btn)

    elif data == "region_back":
        keyboard = await _build_start_keyboard()
        msg_text = "Це бот першої земельної компанії, будь ласка оберіть який регіон вас цікавить"
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(msg_text, reply_markup=keyboard)
        else:
            await query.edit_message_text(msg_text, reply_markup=keyboard)

    elif data.startswith("regionbook_"):
        await _handle_booking(query, context)


async def _handle_booking(query, context):
    """Forward a booking request to the configured contact and confirm to user."""
    region_id = int(query.data.replace("regionbook_", ""))
    tg_user = query.from_user

    async with async_session() as session:
        region = await session.get(Region, region_id)
    if not region:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Ділянку не знайдено. Спробуйте ще раз.",
        )
        return

    username = f"@{tg_user.username}" if tg_user.username else "—"
    full_name = " ".join(filter(None, [tg_user.first_name, tg_user.last_name])) or "—"
    request_text = (
        "🔔 Нова заявка на бронювання\n"
        f"Від: {full_name} ({username}, id:{tg_user.id})\n"
        f"Ділянка: {region.name} — {region.price}$ ({_fmt_size(region.size)} сот.)"
    )

    sent_ok = False
    if BOOKING_CONTACT_ID:
        try:
            await context.bot.send_message(chat_id=BOOKING_CONTACT_ID, text=request_text)
            sent_ok = True
        except Exception as exc:
            logger.warning("Booking forward failed: %s", exc)

    if sent_ok:
        await _log_action(
            tg_user.id, tg_user.username, f"Заявка на бронювання «{region.name}»"
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✅ Заявку надіслано! Артем зв'яжеться з вами найближчим часом.",
        )
    else:
        fallback_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Написати напряму", url=BOOKING_CONTACT_FALLBACK_URL)]]
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Не вдалося автоматично надіслати заявку. Напишіть, будь ласка, напряму:",
            reply_markup=fallback_kb,
        )


# ──────────────────────────────────────
#  Admin callback dispatcher
# ──────────────────────────────────────
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_view_regions":
        keyboard = await _build_start_keyboard()
        await query.edit_message_text("Оберіть регіон:", reply_markup=keyboard)
    elif data == "admin_add":
        await _handle_admin_add(query, context)
    elif data == "admin_copy_price":
        await _handle_copy_list(query, context, "price")
    elif data == "admin_copy_name":
        await _handle_copy_list(query, context, "name")
    elif data == "admin_edit":
        await _handle_admin_edit(query, context)
    elif data == "admin_create_realtor":
        await _handle_create_realtor(query, context)
    elif data == "admin_groups":
        await _handle_admin_groups(query, context)
    elif data == "admin_group_add":
        _set_state(context, STATE_GROUP_ADD_LABEL)
        await query.edit_message_text("Введіть назву групи (наприклад: Грюнсдорф):")
    elif data.startswith("admin_group_del_"):
        group_id = int(data.replace("admin_group_del_", ""))
        async with async_session() as session:
            group = await session.get(RegionGroup, group_id)
            if group:
                label = group.label
                await session.delete(group)
                await session.commit()
                await _log_action(query.from_user.id, query.from_user.username, f"Видалив групу «{label}»")
        await _handle_admin_groups(query, context)
    elif data.startswith("noop_"):
        pass  # informational buttons, no action needed
    elif data == "admin_back":
        _set_state(context, STATE_IDLE)
        menu = _get_menu(context)
        await query.edit_message_text("Панель адміністратора:", reply_markup=menu)
    elif data.startswith("copyreg_price_"):
        await _handle_copy_pick(query, context, "price")
    elif data.startswith("copyreg_name_"):
        await _handle_copy_pick(query, context, "name")
    elif data.startswith("editreg_"):
        await _handle_edit_pick_region(query, context)
    elif data.startswith("editfield_"):
        await _handle_edit_pick_field(query, context)
    elif data.startswith("assigngroup_"):
        await _handle_assign_group(query, context)
    elif data.startswith("delreg_"):
        await _handle_delete_region_confirm(query, context)
    elif data.startswith("delregyes_"):
        await _handle_delete_region(query, context)
    elif data.startswith("delregno_"):
        region_id = int(data.replace("delregno_", ""))
        await query.edit_message_text(
            "Оберіть поле для редагування:", reply_markup=_edit_fields_keyboard(region_id)
        )
    elif data in ("confirm_yes", "confirm_no"):
        await _handle_add_confirm(query, context)
    elif data == "addphoto_done":
        await _show_add_group_picker(query, context)
    elif data.startswith("addgroup_"):
        raw = data.replace("addgroup_", "")
        context.user_data["new_region"]["group_id"] = None if raw == "none" else int(raw)
        _set_state(context, STATE_IDLE)
        photos = context.user_data.get("new_region_photos", [])
        summary = await _region_summary(context.user_data.get("new_region", {}), photos)
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
    elif data == "skip_scheme_photo":
        # Skip scheme photo during creation, proceed to regular photos
        _set_state(context, STATE_ADD_PHOTO)
        skip_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⏩ Пропустити / Готово", callback_data="addphoto_done")]]
        )
        await query.edit_message_text(
            "Надішліть фото ділянки (PNG/JPG/WebP), можна кілька по одному:",
            reply_markup=skip_kb,
        )


# ──────────────────────────────────────
#  Region groups management
# ──────────────────────────────────────
async def _handle_admin_groups(query, context):
    async with async_session() as session:
        groups = (await session.execute(select(RegionGroup))).scalars().all()
    buttons: list[list[InlineKeyboardButton]] = []
    for g in groups:
        buttons.append([
            InlineKeyboardButton(g.label, callback_data=f"noop_group_{g.id}"),
            InlineKeyboardButton("❌", callback_data=f"admin_group_del_{g.id}"),
        ])
    buttons.append([InlineKeyboardButton("➕ Додати групу", callback_data="admin_group_add")])
    buttons.append([InlineKeyboardButton("Назад", callback_data="admin_back")])
    text = "Групи регіонів:" if groups else "Груп поки немає."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


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
            await update.message.reply_text("Режим адміністратора.", reply_markup=ADMIN_NAV_KEYBOARD)
            await update.message.reply_text("Панель адміністратора:", reply_markup=ADMIN_MENU)
            return
        if user and user.is_realtor:
            context.user_data["role"] = "realtor"
            keyboard = await _build_start_keyboard()
            await update.message.reply_text(
                "Ви увійшли як ріелтор. Оберіть регіон:",
                reply_markup=keyboard,
            )
            return

    _set_state(context, STATE_LOGIN_PASSWORD)
    await update.message.reply_text("Введіть пароль:")


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
    context.user_data["new_region_photos"] = []
    _set_state(context, STATE_ADD_NAME)
    await query.edit_message_text("Введіть назву:")


async def _handle_admin_edit(query, context):
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return
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
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return
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
            "link_doc": region.link_doc,
            "scheme_photo_id": region.scheme_photo_id,
            "group_id": region.group_id,
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
def _edit_fields_keyboard(region_id: int) -> InlineKeyboardMarkup:
    """Build the field-selection keyboard for editing a region."""
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"editfield_{field}")]
        for field, label in FIELD_LABELS.items()
    ]
    buttons.append([InlineKeyboardButton("🖼 Фото", callback_data="editfield_photo_file_id")])
    buttons.append([InlineKeyboardButton("📁 Група", callback_data="editfield_group")])
    buttons.append([InlineKeyboardButton("🗑 Видалити ділянку", callback_data=f"delreg_{region_id}")])
    buttons.append([InlineKeyboardButton("Назад", callback_data="admin_edit")])
    return InlineKeyboardMarkup(buttons)


async def _handle_edit_pick_region(query, context):
    region_id = int(query.data.replace("editreg_", ""))
    context.user_data["edit_region_id"] = region_id

    await query.edit_message_text(
        "Оберіть поле для редагування:", reply_markup=_edit_fields_keyboard(region_id)
    )


async def _handle_delete_region_confirm(query, context):
    region_id = int(query.data.replace("delreg_", ""))
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return
        region = await session.get(Region, region_id)
        if not region:
            await query.edit_message_text("Регіон не знайдено.", reply_markup=_get_menu(context))
            return
        label = f"{region.name} — {region.price}$" if region.price else region.name
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Так, видалити", callback_data=f"delregyes_{region_id}"),
            InlineKeyboardButton("Ні", callback_data=f"delregno_{region_id}"),
        ]
    ])
    await query.edit_message_text(
        f"Видалити ділянку «{label}»?\nЦю дію неможливо скасувати.",
        reply_markup=keyboard,
    )


async def _handle_delete_region(query, context):
    region_id = int(query.data.replace("delregyes_", ""))
    async with async_session() as session:
        user = await session.get(User, query.from_user.id)
        if not user or not user.is_admin:
            await query.edit_message_text("У вас немає прав адміністратора.")
            return
        region = await session.get(Region, region_id)
        if not region:
            await query.edit_message_text("Регіон не знайдено.", reply_markup=_get_menu(context))
            return
        name = region.name
        await session.delete(region)
        await session.commit()
    await _log_action(
        query.from_user.id, query.from_user.username, f"Видалив ділянку «{name}» (#{region_id})"
    )
    context.user_data.pop("edit_region_id", None)
    await _handle_admin_edit(query, context)


async def _handle_edit_pick_field(query, context):
    field = query.data.replace("editfield_", "")
    context.user_data["edit_field"] = field
    label = FIELD_LABELS.get(field, field)
    if field == "group":
        await _handle_edit_group(query, context)
        return
    elif field == "photo_file_id":
        region_id = context.user_data.get("edit_region_id")
        text, kb = await _photo_mgmt(region_id, context)
        await query.edit_message_text(text, reply_markup=kb)
        return
    elif field == "scheme_photo_id":
        _set_state(context, STATE_EDIT_SCHEME_PHOTO)
        await query.edit_message_text("Надішліть нову фото-схему ділянки:")
        return
    else:
        _set_state(context, STATE_EDIT_VALUE)
        hint = " (або /skip щоб очистити)" if field in OPTIONAL_EDIT_FIELDS else ""
        await query.edit_message_text(f"Введіть нове значення для '{label}'{hint}:")


async def _handle_edit_group(query, context):
    """Show group assignment options for the region being edited."""
    region_id = context.user_data.get("edit_region_id")
    async with async_session() as session:
        region = await session.get(Region, region_id)
        groups = (await session.execute(select(RegionGroup))).scalars().all()

    current_group = next((g for g in groups if region and g.id == region.group_id), None)

    buttons: list[list[InlineKeyboardButton]] = []
    for g in groups:
        marker = " ✅" if current_group and current_group.id == g.id else ""
        buttons.append([InlineKeyboardButton(
            f"{g.label}{marker}",
            callback_data=f"assigngroup_{g.id}",
        )])
    none_marker = " ✅" if current_group is None else ""
    buttons.append([InlineKeyboardButton(
        f"Без групи{none_marker}", callback_data="assigngroup_none"
    )])
    buttons.append([InlineKeyboardButton("Назад", callback_data=f"editreg_{region_id}")])
    current_text = f"Поточна група: «{current_group.label}»" if current_group else "Регіон не входить у жодну групу"
    await query.edit_message_text(
        f"{current_text}\n\nОберіть групу для «{region.name}»:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_assign_group(query, context):
    """Set region.group_id without touching the name."""
    raw = query.data.replace("assigngroup_", "")
    new_group_id: int | None = None if raw == "none" else int(raw)
    region_id = context.user_data.get("edit_region_id")

    async with async_session() as session:
        region = await session.get(Region, region_id)
        group = await session.get(RegionGroup, new_group_id) if new_group_id else None
        if not region or (new_group_id is not None and not group):
            await query.edit_message_text(
                "Помилка: регіон або групу не знайдено.", reply_markup=_get_menu(context)
            )
            return

        if region.group_id == new_group_id:
            label = group.label if group else "без групи"
            await query.edit_message_text(
                f"«{region.name}» вже {label}.\n\nОберіть поле для редагування:",
                reply_markup=_edit_fields_keyboard(region_id),
            )
            return

        region.group_id = new_group_id
        region_name = region.name
        await session.commit()

    label = group.label if group else "без групи"
    await _log_action(
        query.from_user.id,
        query.from_user.username,
        f"Змінив групу регіону «{region_name}» на «{label}»",
    )
    await query.edit_message_text(
        f"Групу регіону «{region_name}» змінено на «{label}».\n\n"
        f"Оберіть поле для редагування:",
        reply_markup=_edit_fields_keyboard(region_id),
    )


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
        nav_kb = await _nav_keyboard_for(update.effective_user.id)
        await update.message.reply_text(
            "Зв'яжіться з нами:\n"
            "https://t.me/dilyanki_odesa",
            reply_markup=nav_kb,
        )
        return
    if text == "Адмін-панель":
        async with async_session() as session:
            user = await session.get(User, update.effective_user.id)
        if not user or not user.is_admin:
            return
        _set_state(context, STATE_IDLE)
        context.user_data["role"] = "admin"
        await update.message.reply_text("Панель адміністратора:", reply_markup=ADMIN_MENU)
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
    elif state == STATE_ADD_LINK_DOC:
        await _on_add_link_doc(update, context)
    elif state == STATE_EDIT_VALUE:
        await _on_edit_value(update, context)
    elif state == STATE_GROUP_ADD_LABEL:
        await _on_group_add_label(update, context)


# ──────────────────────────────────────
#  Group add steps
# ──────────────────────────────────────
async def _on_group_add_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = update.message.text.strip()
    async with async_session() as session:
        session.add(RegionGroup(label=label))
        await session.commit()
    await _log_action(
        update.effective_user.id,
        update.effective_user.username,
        f"Додав групу «{label}»",
    )
    _set_state(context, STATE_IDLE)
    await update.message.reply_text(
        f"Групу «{label}» створено!", reply_markup=_get_menu(context)
    )


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
        await update.message.reply_text("Ви увійшли як адмін.", reply_markup=ADMIN_NAV_KEYBOARD)
        await update.message.reply_text("Панель адміністратора:", reply_markup=ADMIN_MENU)
        return

    async with async_session() as session:
        realtors = (await session.execute(select(Realtor))).scalars().all()
    matched = next(
        (r for r in realtors if bcrypt.checkpw(password.encode(), r.password.encode())),
        None,
    )
    if matched:
        async with async_session() as session:
            user = await session.get(User, tg_user.id)
            if user:
                user.is_realtor = True
                await session.commit()
        _set_state(context, STATE_IDLE)
        context.user_data["role"] = "realtor"
        await _log_action(tg_user.id, tg_user.username, f"Увійшов як ріелтор «{matched.name}»")
        keyboard = await _build_start_keyboard()
        await update.message.reply_text(
            f"Ви увійшли як ріелтор «{matched.name}». Оберіть регіон:",
            reply_markup=keyboard,
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
        size = Decimal(update.message.text.strip().replace(",", "."))
    except InvalidOperation:
        await update.message.reply_text("Невірний формат. Введіть число:")
        return
    context.user_data["new_region"]["size"] = size
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
    _set_state(context, STATE_ADD_LINK_DOC)
    await update.message.reply_text("Введіть посилання на документ доступності (Google Drive) або /skip:")


async def _on_add_link_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["new_region"]["link_doc"] = None if text == "/skip" else text
    _set_state(context, STATE_ADD_SCHEME_PHOTO)
    skip_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏩ Пропустити", callback_data="skip_scheme_photo")]]
    )
    await update.message.reply_text(
        "Надішліть фото-схему ділянки (або пропустіть):",
        reply_markup=skip_kb,
    )


async def _region_summary(data: dict, photos: list | None = None) -> str:
    count = len(photos) if photos else 0
    photo_str = f"є ({count} шт.)" if count else "немає"
    group_label = "—"
    gid = data.get("group_id")
    if gid is not None:
        async with async_session() as session:
            g = await session.get(RegionGroup, gid)
            if g:
                group_label = g.label
    return (
        f"Назва: {data.get('name', '—')}\n"
        f"Ціна: {data.get('price', '—')}\n"
        f"Кількість ділянок: {data.get('plots_number', '—')}\n"
        f"Розмір (сотки): {_fmt_size(data.get('size', 5))}\n"
        f"Опис: {data.get('describe') or '—'}\n"
        f"Карта: {data.get('link_map') or '—'}\n"
        f"YouTube: {data.get('link_youtube') or '—'}\n"
        f"Документ доступності: {data.get('link_doc') or '—'}\n"
        f"Група: {group_label}\n"
        f"Фото: {photo_str}"
    )


async def _show_add_group_picker(query, context):
    """Show group selection buttons for the region being added."""
    _set_state(context, STATE_ADD_GROUP)
    async with async_session() as session:
        groups = (await session.execute(select(RegionGroup))).scalars().all()
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(g.label, callback_data=f"addgroup_{g.id}")]
        for g in sorted(groups, key=lambda x: x.label)
    ]
    buttons.append([InlineKeyboardButton("Без групи", callback_data="addgroup_none")])
    await query.edit_message_text(
        "Оберіть групу для регіону:",
        reply_markup=InlineKeyboardMarkup(buttons),
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
    summary = await _region_summary(context.user_data["new_region"], photos)
    await update.message.reply_text(
        f"Зберегти?\n\n{summary}", reply_markup=CONFIRM_KEYBOARD
    )


async def _on_copy_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_region"]["name"] = update.message.text.strip()
    _set_state(context, STATE_IDLE)
    photos = context.user_data.get("new_region_photos", [])
    summary = await _region_summary(context.user_data["new_region"], photos)
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

    if field in ("price", "size"):
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

    tg_user = update.effective_user
    async with async_session() as session:
        region = await session.get(Region, region_id)
        if region:
            setattr(region, field, value)
            if field == "link_doc":
                region.doc_file_id = None
                region.doc_etag = None
            await session.commit()
            await _log_action(
                tg_user.id,
                tg_user.username,
                f"Відредагував поле «{field}» регіону «{region.name}»",
            )
            await update.message.reply_text(
                "Оновлено! Оберіть поле для редагування:",
                reply_markup=_edit_fields_keyboard(region_id),
            )
        else:
            await update.message.reply_text(
                "Регіон не знайдено.", reply_markup=_get_menu(context)
            )

    _set_state(context, STATE_IDLE)
    context.user_data.pop("edit_field", None)


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

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    async with async_session() as session:
        realtor = Realtor(name=name, password=hashed, created_by=tg_user.id)
        session.add(realtor)
        await session.commit()

    _set_state(context, STATE_IDLE)
    await _log_action(tg_user.id, tg_user.username, f"Створив ріелтора «{name}»")
    await update.message.reply_text(
        f"Ріелтор «{name}» створений.",
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

    if state == STATE_ADD_SCHEME_PHOTO:
        context.user_data["new_region"]["scheme_photo_id"] = file_id
        _set_state(context, STATE_ADD_PHOTO)
        skip_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⏩ Пропустити / Готово", callback_data="addphoto_done")]]
        )
        await update.message.reply_text(
            "Фото-схему збережено! Надішліть фото ділянки (PNG/JPG/WebP), можна кілька по одному:",
            reply_markup=skip_kb,
        )
        return

    if state == STATE_EDIT_SCHEME_PHOTO:
        region_id = context.user_data.get("edit_region_id")
        async with async_session() as session:
            region = await session.get(Region, region_id)
            if region:
                region.scheme_photo_id = file_id
                await session.commit()
        await _log_action(
            update.effective_user.id,
            update.effective_user.username,
            f"Оновив фото-схему регіону #{region_id}",
        )
        _set_state(context, STATE_IDLE)
        await update.message.reply_text(
            "Фото-схему оновлено! Оберіть поле для редагування:",
            reply_markup=_edit_fields_keyboard(region_id),
        )
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


