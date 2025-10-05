from aiogram.dispatcher.filters.state import State, StatesGroup

class BookingFlow(StatesGroup):
    WaitingService = State()
    WaitingDate = State()
    WaitingTime = State()
    WaitingPhone = State()
    Confirm = State()