from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

REGISTER_TEXT = "Регистрация"
LOGIN_TEXT = "Вход"
ADMIN_TEXT = "Админка"
ADMIN_ADD_PLOT_TEXT = "Добавить участок"
ADMIN_MARK_SOLD_TEXT = "Отметить как продан/свободен"
ADMIN_BACK_TEXT = "Назад"


def auth_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=REGISTER_TEXT), KeyboardButton(text=LOGIN_TEXT)]
        ],
        resize_keyboard=True,
        selective=True,
    )


def menu_keyboard(places: list[str], is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for place in places:
        row.append(KeyboardButton(text=place))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if is_admin:
        rows.append([KeyboardButton(text=ADMIN_TEXT)])
    if not rows:
        rows = [[KeyboardButton(text="Нет доступных участков")]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, selective=True)


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ADMIN_ADD_PLOT_TEXT)],
            [KeyboardButton(text=ADMIN_MARK_SOLD_TEXT)],
            [KeyboardButton(text=ADMIN_BACK_TEXT)],
        ],
        resize_keyboard=True,
        selective=True,
    )
