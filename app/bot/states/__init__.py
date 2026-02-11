from aiogram.fsm.state import State, StatesGroup


class AuthStates(StatesGroup):
    choose = State()
    reg_username = State()
    reg_password = State()
    login_username = State()
    login_password = State()


class PlotStates(StatesGroup):
    choose_place = State()
    enter_plot_number = State()


class AdminStates(StatesGroup):
    choose = State()
    add_place_name = State()
    add_plot_number = State()
    add_area_m2 = State()
    add_price = State()
    add_is_sold = State()
    mark_place_name = State()
    mark_plot_number = State()
    mark_is_sold = State()
