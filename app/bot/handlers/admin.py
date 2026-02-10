from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError

from app.bot.keyboards import (
    ADMIN_ADD_PLOT_TEXT,
    ADMIN_BACK_TEXT,
    ADMIN_MARK_SOLD_TEXT,
    admin_keyboard,
    menu_keyboard,
)
from app.bot.states import AdminStates, PlotStates
from app.db.repositories.plots import PlotsRepository
from app.db.repositories.users import UsersRepository
from app.db.session import get_session

router = Router()

PLOT_NUMBER_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


async def _ensure_admin(message: Message) -> bool:
    async with get_session() as session:
        users_repo = UsersRepository(session)
        user = await users_repo.get_by_telegram_id(message.from_user.id)
        return user is not None and user.is_admin


async def _show_menu(message: Message, state: FSMContext) -> None:
    async with get_session() as session:
        plots_repo = PlotsRepository(session)
        places = await plots_repo.get_places_list(limit=6)
        await state.set_state(PlotStates.choose_place)
        await message.answer("Выберите участок:", reply_markup=menu_keyboard(places, True))


@router.message(AdminStates.choose)
async def handle_admin_menu(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    if message.text == ADMIN_ADD_PLOT_TEXT:
        await state.set_state(AdminStates.add_place_name)
        await message.answer("Введите название объекта (place_name):")
        return
    if message.text == ADMIN_MARK_SOLD_TEXT:
        await state.set_state(AdminStates.mark_place_name)
        await message.answer("Введите название объекта (place_name):")
        return
    if message.text == ADMIN_BACK_TEXT:
        await _show_menu(message, state)
        return
    await message.answer("Выберите действие:", reply_markup=admin_keyboard())


@router.message(AdminStates.add_place_name)
async def handle_add_place_name(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    place_name = message.text.strip()
    if not place_name:
        await message.answer("Введите корректное название объекта.")
        return
    await state.update_data(place_name=place_name)
    await state.set_state(AdminStates.add_plot_number)
    await message.answer("Введите номер участка:")


@router.message(AdminStates.add_plot_number)
async def handle_add_plot_number(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    plot_number = message.text.strip()
    if not PLOT_NUMBER_RE.match(plot_number):
        await message.answer("Номер участка: 1-20 символов (буквы/цифры/подчеркивание).")
        return
    await state.update_data(plot_number=plot_number)
    await state.set_state(AdminStates.add_area_m2)
    await message.answer("Введите площадь (м2):")


@router.message(AdminStates.add_area_m2)
async def handle_add_area(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    try:
        area_m2 = int(message.text.strip())
        if area_m2 <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Площадь должна быть положительным числом.")
        return
    await state.update_data(area_m2=area_m2)
    await state.set_state(AdminStates.add_price)
    await message.answer("Введите стоимость (например 120000.00):")


@router.message(AdminStates.add_price)
async def handle_add_price(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    try:
        price = Decimal(message.text.replace(" ", "").replace(",", "."))
        if price <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await message.answer("Стоимость должна быть положительным числом.")
        return
    await state.update_data(price=price)
    await state.set_state(AdminStates.add_is_sold)
    await message.answer("Участок продан? (да/нет)")


@router.message(AdminStates.add_is_sold)
async def handle_add_is_sold(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    answer = message.text.strip().lower()
    if answer not in {"да", "нет"}:
        await message.answer("Ответьте 'да' или 'нет'.")
        return
    data = await state.get_data()
    async with get_session() as session:
        plots_repo = PlotsRepository(session)
        try:
            await plots_repo.create_plot(
                place_name=data["place_name"],
                area_m2=data["area_m2"],
                price=data["price"],
                plot_number=data["plot_number"],
                is_sold=answer == "да",
            )
        except IntegrityError:
            await session.rollback()
            await message.answer("Участок с таким номером уже существует.")
            await state.set_state(AdminStates.add_plot_number)
            await message.answer("Введите номер участка:")
            return
    await message.answer("Участок добавлен.")
    await _show_menu(message, state)


@router.message(AdminStates.mark_place_name)
async def handle_mark_place(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    place_name = message.text.strip()
    if not place_name:
        await message.answer("Введите корректное название объекта.")
        return
    await state.update_data(place_name=place_name)
    await state.set_state(AdminStates.mark_plot_number)
    await message.answer("Введите номер участка:")


@router.message(AdminStates.mark_plot_number)
async def handle_mark_plot_number(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    plot_number = message.text.strip()
    if not PLOT_NUMBER_RE.match(plot_number):
        await message.answer("Номер участка: 1-20 символов (буквы/цифры/подчеркивание).")
        return
    await state.update_data(plot_number=plot_number)
    await state.set_state(AdminStates.mark_is_sold)
    await message.answer("Отметить как продан? (да/нет)")


@router.message(AdminStates.mark_is_sold)
async def handle_mark_is_sold(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message):
        await message.answer("Доступ запрещен.")
        return
    answer = message.text.strip().lower()
    if answer not in {"да", "нет"}:
        await message.answer("Ответьте 'да' или 'нет'.")
        return
    data = await state.get_data()
    async with get_session() as session:
        plots_repo = PlotsRepository(session)
        plot = await plots_repo.set_sold(
            data["place_name"], data["plot_number"], answer == "да"
        )
        if plot is None:
            await message.answer("Участок не найден. Проверьте данные и попробуйте снова.")
            await state.set_state(AdminStates.mark_plot_number)
            return
    await message.answer("Статус участка обновлен.")
    await _show_menu(message, state)
