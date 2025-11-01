import logging
import asyncio
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo
import os

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from dotenv import load_dotenv

from config import settings
from db_pg import (
    init_db,
    list_services,
    add_service,
    get_service as get_service_db,
    upsert_client,
    get_client_by_tg,
    create_booking,
    list_future_active_bookings_by_client,
    get_booking,
    cancel_booking,
    sync_services_with_seed,
)

from states import BookingFlow
from calendar_integration import is_slot_free, create_event, delete_event, get_service as get_gcal
from keyboards import main_kb, services_ikb, time_slots_ikb, bookings_ikb, cancel_confirm_ikb, phone_request_kb, dates_ikb, confirm_ikb
from scheduler import setup_scheduler

# --- Logging & env ---
logging.basicConfig(level=logging.INFO)
load_dotenv()
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

# --- Create Google service account file if provided via env (Railway deploy) ---
if settings.GCREDS_JSON and not os.path.exists(settings.GCREDS_PATH):
    with open(settings.GCREDS_PATH, "w") as f:
        f.write(settings.GCREDS_JSON)
# ---------------------------------------------------------------------------

TZ = ZoneInfo(settings.TZ)
UTC = ZoneInfo("UTC")

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())


# --- Seed services (fixed list) ---
SERVICES_SEED = [
    ("Корекція брів", 30),
    ("Корекція і фарбування брів", 60),
    ("Ламінування брів комплекс", 60),
    ("Ламінування/освітлення брів", 30),
    ("Ламінування вій", 60),
    ("Перманентний макіяж брів", 150),
    ("Фарбування вій/брів", 15),
    ("Комплекс брови та вії", 120),
]

WORKING_START = dtime(10, 0)
WORKING_LAST_START = dtime(20, 30)

# --- Utils ---

def _generate_candidate_starts(chosen_date: date, now_local: datetime):
    """Повертає лише :00/:30 у межах 10:00..20:30, без уже минулих слотів для сьогодні."""
    slots = []
    today = now_local.date()
    for h in range(WORKING_START.hour, WORKING_LAST_START.hour + 1):
        for m in (0, 30):
            if h == WORKING_LAST_START.hour and m > WORKING_LAST_START.minute:
                continue
            slot_local = datetime.combine(chosen_date, dtime(h, m)).replace(tzinfo=TZ)
            if chosen_date == today and slot_local <= now_local:
                continue
            slots.append(f"{h:02d}:{m:02d}")
    return slots


async def _gen_available_dates_items(duration_min: int):
    service = get_gcal()
    today_local = datetime.now(TZ).date()
    horizon = today_local + timedelta(days=settings.BOOKING_HORIZON_DAYS)

    # Один запит на весь горизонт
    range_start_local = datetime.combine(today_local, dtime(0, 0)).replace(tzinfo=TZ)
    range_end_local   = datetime.combine(horizon,     dtime(23, 59, 59)).replace(tzinfo=TZ)
    body = {
        "timeMin": range_start_local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "timeMax": range_end_local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "items": [{"id": settings.GCAL_ID}],
    }

    fb = await asyncio.get_event_loop().run_in_executor(
        None, lambda: service.freebusy().query(body=body).execute()
    )
    busy_all = fb["calendars"][settings.GCAL_ID]["busy"]

    busy_intervals = []
    for b in busy_all:
        b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        b_end   = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        busy_intervals.append((b_start, b_end))

    def overlaps(s_utc, e_utc) -> bool:
        for bs, be in busy_intervals:
            if not (e_utc <= bs or s_utc >= be):
                return True
        return False

    items = []
    wk = ['Пн','Вт','Ср','Чт','Пт','Сб','Нд']
    d = today_local
    while d <= horizon:
        now_local = datetime.now(TZ)
        candidates = _generate_candidate_starts(d, now_local)
        for t in candidates:
            h, m = map(int, t.split(':'))
            start_local = datetime.combine(d, dtime(h, m)).replace(tzinfo=TZ)
            end_local   = start_local + timedelta(minutes=duration_min)
            s_utc = start_local.astimezone(UTC)
            e_utc = end_local.astimezone(UTC)
            if not overlaps(s_utc, e_utc):
                items.append((str(d), f"{d.day:02d}.{d.month:02d} {wk[d.weekday()]}"))
                break
        d += timedelta(days=1)
    return items
    

async def _get_available_times_for_date(chosen_date: date, duration_min: int):
    service = get_gcal()
    day_start_local = datetime.combine(chosen_date, dtime(0, 0)).replace(tzinfo=TZ)
    day_end_local = datetime.combine(chosen_date, dtime(23, 59, 59)).replace(tzinfo=TZ)
    body = {
        "timeMin": day_start_local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "timeMax": day_end_local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "items": [{"id": settings.GCAL_ID}],
    }
    fb = await asyncio.get_event_loop().run_in_executor(None, lambda: service.freebusy().query(body=body).execute())
    busy = fb["calendars"][settings.GCAL_ID]["busy"]

    now_local = datetime.now(TZ)
    candidates = _generate_candidate_starts(chosen_date, now_local)
    result = []
    for t in candidates:
        h, m = map(int, t.split(':'))
        start_local = datetime.combine(chosen_date, dtime(h, m)).replace(tzinfo=TZ)
        end_local = start_local + timedelta(minutes=duration_min)
        s_utc = start_local.astimezone(UTC)
        e_utc = end_local.astimezone(UTC)
        overlap = False
        for b in busy:
            b_start = datetime.fromisoformat(b['start'].replace('Z', '+00:00'))
            b_end = datetime.fromisoformat(b['end'].replace('Z', '+00:00'))
            if not (e_utc <= b_start or s_utc >= b_end):
                overlap = True
                break
        if not overlap:
            result.append(t)
    return result


async def _seed_services_if_needed():
    existing = await list_services()
    if not existing:
        for name, dur in SERVICES_SEED:
            await add_service(name, dur)


# --- Global menu handlers (cancel any previous state) ---
@dp.message_handler(commands=["start"], state='*')
async def start_cmd(m: types.Message, state: FSMContext = None):
    if state:
        await state.finish()
    await upsert_client(
        tg_id=m.from_user.id,
        username=m.from_user.username or None,
        first_name=m.from_user.first_name or None,
        last_name=m.from_user.last_name or None,
    )
    await m.answer("Вітаю!👋 Я бот запису до майстра Ірини Брижик. Оберіть, будь ласка, дію:", reply_markup=main_kb())


@dp.message_handler(Text(equals="ℹ️ Контакти"), state='*')
async def contacts_cmd(m: types.Message, state: FSMContext = None):
    if state:
        await state.finish()
    await m.answer(
        """Адреса:
Strada Ion Bogdan 18
Верхній домофон 6
https://maps.app.goo.gl/7AJXbvq1o9aeDUHR7?g_st=ipc
Instagram: https://www.instagram.com/bryzhyk.brows.bucharest?igsh=MXVxbTd0NDV5bTFscQ=="""
    )


@dp.message_handler(Text(equals="🧚 Записатися"), state='*')
async def book_cmd(m: types.Message, state: FSMContext):
    await state.finish()
    await BookingFlow.WaitingService.set()
    svcs = await list_services()
    await m.answer("Оберіть, будь ласка, послугу 👇:", reply_markup=services_ikb(svcs))


# --- Booking flow ---
@dp.callback_query_handler(lambda c: c.data.startswith("srv_"), state=BookingFlow.WaitingService)
async def choose_service(cq: types.CallbackQuery, state: FSMContext):
    service_id = int(cq.data.split("_")[1])
    svc = await get_service_db(service_id)
    if not svc:
        await cq.answer("Невідома послуга", show_alert=True)
        return
    await state.update_data(service_id=service_id)
    await BookingFlow.WaitingDate.set()

    items = await _gen_available_dates_items(duration_min=svc[2])
    if not items:
        await cq.message.edit_text("😔 На жаль, немає доступних дат у найближчі 30 днів.")
        await cq.answer()
        return

    await cq.message.edit_text("Оберіть, будь ласка, доступну дату 🗓️:", reply_markup=dates_ikb(items))
    await cq.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("date_"), state=BookingFlow.WaitingDate)
async def choose_date(cq: types.CallbackQuery, state: FSMContext):
    iso = cq.data.split("_")[1]
    try:
        chosen_date = datetime.strptime(iso, "%Y-%m-%d").date()
    except Exception:
        await cq.answer("Невірна дата", show_alert=True)
        return

    data = await state.get_data()
    svc = await get_service_db(int(data['service_id']))
    await state.update_data(date=str(chosen_date))

    slots = await _get_available_times_for_date(chosen_date, svc[2])
    if not slots:
        items = await _gen_available_dates_items(duration_min=svc[2])
        await cq.message.edit_text("😔 На жаль на цю дату вільних годин немає. Оберіть, будь ласка, іншу:", reply_markup=dates_ikb(items))
        await cq.answer()
        return

    await BookingFlow.WaitingTime.set()
    await cq.message.edit_text("Оберіть, будь ласка, час з доступних варіантів 🕒:", reply_markup=time_slots_ikb(slots))
    await cq.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("time_"), state=BookingFlow.WaitingTime)
async def choose_time(cq: types.CallbackQuery, state: FSMContext):
    t = cq.data.split("_")[1]
    try:
        hh, mm = map(int, t.split(":"))
    except Exception:
        await cq.answer("Невірний час", show_alert=True)
        return

    data = await state.get_data()
    svc = await get_service_db(int(data['service_id']))

    chosen_date = datetime.strptime(data.get('date'), "%Y-%m-%d").date()
    start_local = datetime.combine(chosen_date, dtime(hh, mm)).replace(tzinfo=TZ)
    end_local = start_local + timedelta(minutes=svc[2])
    free = await asyncio.get_event_loop().run_in_executor(None, lambda: is_slot_free(start_local.astimezone(UTC), end_local.astimezone(UTC)))
    if not free:
        slots = await _get_available_times_for_date(chosen_date, svc[2])
        if slots:
            await cq.message.edit_text("😔 На жаль цей час щойно зайняли. Оберіть, будь ласка, інший:", reply_markup=time_slots_ikb(slots))
        else:
            items = await _gen_available_dates_items(duration_min=svc[2])
            await cq.message.edit_text("😔 На жаль на цю дату вже немає вільних варіантів. Оберіть, будь ласка, іншу дату:", reply_markup=dates_ikb(items))
        await cq.answer()
        return

    await state.update_data(time=t)

    when_str = start_local.strftime('%H:%M %d.%m.%Y')
    service_name = svc[1]

    if cq.from_user.username:
        await BookingFlow.Confirm.set()
        await cq.message.edit_text(f"Підтверджуємо запис на {when_str} — {svc[1]}?", reply_markup=confirm_ikb())
    else:
        await BookingFlow.WaitingPhone.set()
        await cq.message.edit_text("У Вас немає @username. Поділіться контактом або введіть номер вручну.")
        await cq.message.answer("Надішліть контакт або натисніть 'Введу номер вручну'", reply_markup=phone_request_kb())
    await cq.answer()


@dp.message_handler(content_types=types.ContentTypes.CONTACT, state=BookingFlow.WaitingPhone)
async def phone_shared(m: types.Message, state: FSMContext):
    if not m.contact or not m.contact.phone_number:
        return await m.answer("Не бачу номера. Спробуйте ще раз або введіть вручну.")
    await state.update_data(phone=m.contact.phone_number)
    await BookingFlow.Confirm.set()
    await m.answer("Підтвердити запис?", reply_markup=types.ReplyKeyboardRemove())


@dp.message_handler(Text(equals="Введу номер вручну"), state=BookingFlow.WaitingPhone)
async def ask_phone_manual(m: types.Message):
    await m.answer("Введіть номер телефону одним рядком:", reply_markup=types.ReplyKeyboardRemove())


@dp.message_handler(state=BookingFlow.WaitingPhone)
async def phone_manual_entered(m: types.Message, state: FSMContext):
    phone = m.text.strip()
    if len(phone) < 5:
        return await m.answer("Занадто короткий номер. Введіть ще раз:")
    await state.update_data(phone=phone)
    await BookingFlow.Confirm.set()
    await m.answer("Підтвердити запис?", reply_markup=types.ReplyKeyboardRemove())


@dp.callback_query_handler(lambda c: c.data == "cancel_flow", state='*')
async def cancel_flow_cb(cq: types.CallbackQuery, state: FSMContext):
    await state.finish()
    try:
        await cq.message.edit_text("Скасовано.")
    except Exception:
        pass
    await cq.message.answer("Ви в головному меню.", reply_markup=main_kb())
    await cq.answer()


@dp.callback_query_handler(lambda c: c.data == "confirm_booking", state=BookingFlow.Confirm)
async def confirm_booking_cb(cq: types.CallbackQuery, state: FSMContext):
    user = cq.from_user
    data = await state.get_data()

    svc = await get_service_db(int(data['service_id']))
    if not svc:
        await state.finish()
        await cq.message.edit_text("Помилка: послуга не знайдена. Спробуйте ще раз.")
        await cq.answer()
        return

    chosen_date = datetime.strptime(data['date'], "%Y-%m-%d").date()
    hh, mm = map(int, data['time'].split(":"))
    start_local = datetime.combine(chosen_date, dtime(hh, mm)).replace(tzinfo=TZ)
    end_local = start_local + timedelta(minutes=svc[2])
    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    if start_local <= datetime.now(TZ):
        await state.finish()
        await cq.message.edit_text("😔 На жаль цей час вже минув. Оберіть, будь ласка, інший.")
        await cq.answer()
        return

    loop = asyncio.get_event_loop()
    free = await loop.run_in_executor(None, lambda: is_slot_free(start_utc, end_utc))
    if not free:
        slots = await _get_available_times_for_date(chosen_date, svc[2])
        if slots:
            await BookingFlow.WaitingTime.set()
            await cq.message.edit_text("😔 На жаль, цей час вже зайнятий. Оберіть, будь ласка, інший:", reply_markup=time_slots_ikb(slots))
        else:
            items = await _gen_available_dates_items(duration_min=svc[2])
            await BookingFlow.WaitingDate.set()
            await cq.message.edit_text("😔 На жаль на цю дату вільних варіантів не залишилось. Оберіть, будь ласка, іншу дату:", reply_markup=dates_ikb(items))
        await cq.answer()
        return

    phone = data.get('phone')
    await upsert_client(
        tg_id=user.id,
        username=user.username or None,
        first_name=user.first_name or None,
        last_name=user.last_name or None,
        phone=phone
    )
    client = await get_client_by_tg(user.id)

    full_name = " ".join(x for x in [user.first_name, user.last_name] if x)
    contact_line = []
    if user.username:
        contact_line.append(f"@{user.username}")
    if phone:
        contact_line.append(f"Телефон: {phone}")
    contacts = ", ".join(contact_line) if contact_line else "—"

    description_lines = [
        f"Ім'я: {full_name or '—'}",
        f"Контакти: {contacts}",
        f"tg_id: {user.id}",
        "created via Telegram bot",
    ]
    description = "\n".join(description_lines)

    event_id = await loop.run_in_executor(
        None, lambda: create_event(svc[1], description, start_utc, end_utc)
    )

    await create_booking(
        client_id=client[0],
        service_id=svc[0],
        start_utc=start_utc.isoformat(),
        end_utc=end_utc.isoformat(),
        event_id=event_id
    )

    await state.finish()
    when_str = start_local.strftime('%H:%M %d.%m.%Y')
    await cq.message.edit_text(f"✅ Готово! Запис створено на {when_str} — {svc[1]} Гарного дня 🌷")
    await cq.answer()


@dp.message_handler(Text(equals="📅 Мої записи"), state='*')
async def my_bookings(m: types.Message, state: FSMContext = None):
    if state:
        await state.finish()
    client = await get_client_by_tg(m.from_user.id)
    if not client:
        await upsert_client(m.from_user.id, m.from_user.username or None, m.from_user.first_name or None, m.from_user.last_name or None)
        client = await get_client_by_tg(m.from_user.id)
    items = await list_future_active_bookings_by_client(client[0])
    if not items:
        return await m.answer("У Вас немає майбутніх записів.")
    await m.answer("Ваші записи. Натисніть щоб змінити:", reply_markup=bookings_ikb(items))


@dp.callback_query_handler(lambda c: c.data.startswith("bk_"))
async def booking_detail(cq: types.CallbackQuery):
    booking_id = int(cq.data.split("_")[1])
    b = await get_booking(booking_id)
    if not b:
        return await cq.answer("Не знайдено", show_alert=True)
    svc = await get_service_db(b[2])
    start_local = datetime.fromisoformat(b[3]).replace(tzinfo=UTC).astimezone(TZ)
    text = (
        f"Послуга: {svc[1]}\n"
        f"Початок: {start_local.strftime('%H:%M %d.%m.%Y')}\n"
        f"Статус: {b[6]}"
    )
    await cq.message.edit_text(text, reply_markup=cancel_confirm_ikb(booking_id))
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("cancel_"))
async def cancel_booking_cb(cq: types.CallbackQuery):
    try:
        booking_id = int(cq.data.split("_")[1])
    except Exception:
        await cq.answer("Помилка ідентифікатора", show_alert=True)
        return

    b = await get_booking(booking_id)
    if not b or b[6] != 'active':
        await cq.answer("Нема чого скасовувати", show_alert=True)
        return

    # Переконаємось, що запис належить цьому користувачу
    client = await get_client_by_tg(cq.from_user.id)
    if not client or client[0] != b[1]:
        await cq.answer("Цей запис Вам не належить.", show_alert=True)
        return

    # Видалити подію з календаря (не критично, якщо не вдасться)
    try:
        await asyncio.get_event_loop().run_in_executor(None, lambda: delete_event(b[5]))
    except Exception:
        pass

    # Позначити в БД як скасований
    await cancel_booking(booking_id)

    # Відповідь юзеру
    await cq.message.edit_text("Запис скасовано. Чекаємо Вас у зручний час! 🫶")
    await cq.answer("Скасовано")

@dp.callback_query_handler(Text(equals="back_to_list"))
async def back_to_list(cq: types.CallbackQuery):
    client = await get_client_by_tg(cq.from_user.id)
    if not client:
        return await cq.answer("Спробуйте ще раз через меню", show_alert=True)
    items = await list_future_active_bookings_by_client(client[0])
    if not items:
        await cq.message.edit_text("У Вас немає майбутніх записів.")
    else:
        await cq.message.edit_text("Ваші записи. Натисніть щоб змінити:", reply_markup=bookings_ikb(items))
    await cq.answer()


async def on_startup(dp: Dispatcher):
    await init_db()
    # синхронізація послуг замість старого seed
    await sync_services_with_seed(SERVICES_SEED)
    setup_scheduler(dp.bot)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, timeout=30)