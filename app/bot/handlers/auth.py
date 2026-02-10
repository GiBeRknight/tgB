from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import ADMIN_TEXT, LOGIN_TEXT, REGISTER_TEXT, auth_keyboard, menu_keyboard
from app.bot.states import AdminStates, AuthStates, PlotStates
from app.db.repositories.plots import PlotsRepository
from app.db.repositories.users import UsersRepository
from app.db.session import get_session
from app.services import auth as auth_service

router = Router()


async def _show_menu(
    message: Message, state: FSMContext, repo: PlotsRepository, is_admin: bool
) -> None:
    places = await repo.get_places_list(limit=6)
    await state.set_state(PlotStates.choose_place)
    await message.answer(
        "Выберите участок:", reply_markup=menu_keyboard(places, is_admin=is_admin)
    )


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    async with get_session() as session:
        users_repo = UsersRepository(session)
        plots_repo = PlotsRepository(session)
        existing = await users_repo.get_by_telegram_id(message.from_user.id)
        if existing is not None:
            await state.clear()
            await _show_menu(message, state, plots_repo, existing.is_admin)
            return

    await state.set_state(AuthStates.choose)
    await message.answer(
        "Добро пожаловать! Выберите действие:", reply_markup=auth_keyboard()
    )


@router.message(Command("logout"))
async def handle_logout(message: Message, state: FSMContext) -> None:
    async with get_session() as session:
        users_repo = UsersRepository(session)
        await users_repo.unbind_telegram_id(message.from_user.id)
    await state.clear()
    await state.set_state(AuthStates.choose)
    await message.answer("Вы вышли из аккаунта.", reply_markup=auth_keyboard())


@router.message(AuthStates.choose)
async def handle_choice(message: Message, state: FSMContext) -> None:
    if message.text == REGISTER_TEXT:
        await state.set_state(AuthStates.reg_username)
        await message.answer("Введите username:")
        return
    if message.text == LOGIN_TEXT:
        await state.set_state(AuthStates.login_username)
        await message.answer("Введите username:")
        return
    await message.answer("Пожалуйста, выберите действие кнопкой ниже.")


@router.message(AuthStates.reg_username)
async def handle_register_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=message.text.strip())
    await state.set_state(AuthStates.reg_password)
    await message.answer("Введите пароль:")


@router.message(AuthStates.reg_password)
async def handle_register_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    username = data.get("username")
    if not username:
        await state.set_state(AuthStates.reg_username)
        await message.answer("Введите username:")
        return
    async with get_session() as session:
        users_repo = UsersRepository(session)
        plots_repo = PlotsRepository(session)
        try:
            user = await auth_service.register(users_repo, username, message.text)
        except auth_service.UserAlreadyExists as exc:
            await state.set_state(AuthStates.reg_username)
            await message.answer(str(exc))
            return
        except auth_service.ValidationError as exc:
            await state.set_state(AuthStates.reg_username)
            await message.answer(str(exc))
            return
        bound = await users_repo.bind_telegram_id(user.id, message.from_user.id)
        if bound is None:
            await message.answer("Не удалось привязать Telegram ID.")
            return
        await state.clear()
        await _show_menu(message, state, plots_repo, user.is_admin)


@router.message(AuthStates.login_username)
async def handle_login_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=message.text.strip())
    await state.set_state(AuthStates.login_password)
    await message.answer("Введите пароль:")


@router.message(AuthStates.login_password)
async def handle_login_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    username = data.get("username")
    if not username:
        await state.set_state(AuthStates.login_username)
        await message.answer("Введите username:")
        return
    async with get_session() as session:
        users_repo = UsersRepository(session)
        plots_repo = PlotsRepository(session)
        try:
            user = await auth_service.login(
                users_repo, username, message.text, message.from_user.id
            )
        except auth_service.InvalidCredentials as exc:
            await state.set_state(AuthStates.login_username)
            await message.answer(str(exc))
            return
        await state.clear()
        await _show_menu(message, state, plots_repo, user.is_admin)
