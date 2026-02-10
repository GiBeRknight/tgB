from __future__ import annotations

import re

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import ADMIN_TEXT, admin_keyboard, menu_keyboard
from app.bot.states import AdminStates, PlotStates
from app.db.repositories.users import UsersRepository
from app.db.repositories.plots import PlotsRepository
from app.db.session import get_session
from app.services import plots as plots_service

router = Router()

PLOT_NUMBER_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


@router.message(PlotStates.choose_place)
async def handle_choose_place(message: Message, state: FSMContext) -> None:
    if message.text == ADMIN_TEXT:
        async with get_session() as session:
            users_repo = UsersRepository(session)
            user = await users_repo.get_by_telegram_id(message.from_user.id)
            if user is None or not user.is_admin:
                await message.answer("Доступ запрещен.")
                return
        await state.set_state(AdminStates.choose)
        await message.answer("Админка:", reply_markup=admin_keyboard())
        return

    place_name = message.text.strip()
    await state.update_data(place_name=place_name)

    image = plots_service.get_place_image(place_name)
    if image:
        await message.answer_photo(image, caption=f"Объект: {place_name}")
    else:
        await message.answer(f"Объект: {place_name}")

    await state.set_state(PlotStates.enter_plot_number)
    await message.answer("Введите номер участка:")


@router.message(PlotStates.enter_plot_number)
async def handle_plot_number(message: Message, state: FSMContext) -> None:
    plot_number = message.text.strip()
    if not PLOT_NUMBER_RE.match(plot_number):
        await message.answer("Введите номер участка в формате 1-20 символов (буквы/цифры).")
        return

    data = await state.get_data()
    place_name = data.get("place_name")
    if not place_name:
        async with get_session() as session:
            plots_repo = PlotsRepository(session)
            places = await plots_repo.get_places_list(limit=6)
            await state.set_state(PlotStates.choose_place)
            await message.answer("Выберите объект:", reply_markup=menu_keyboard(places))
        return

    async with get_session() as session:
        plots_repo = PlotsRepository(session)
        plot = await plots_repo.get_plot(place_name, plot_number)

        if plot is None:
            await message.answer(
                "Участок не найден. Проверьте номер и попробуйте снова."
            )
            return

        await message.answer(plots_service.format_plot_details(plot))
