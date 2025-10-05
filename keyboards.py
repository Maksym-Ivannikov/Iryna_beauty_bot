from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    # одна кнопка в рядок, щоб текст не обрізався
    kb.row(KeyboardButton("🧚 Записатися"))
    kb.row(KeyboardButton("📅 Мої записи"))
    kb.row(KeyboardButton("ℹ️ Контакти"))
    return kb


def services_ikb(services):
    ikb = InlineKeyboardMarkup(row_width=1)
    for s in services:
        # s: (id, name, duration_min)
        ikb.add(InlineKeyboardButton(f"{s[1]} — {s[2]} хв", callback_data=f"srv_{s[0]}"))
    ikb.add(InlineKeyboardButton("❌ Скасувати", callback_data="cancel_flow"))
    return ikb


def dates_ikb(date_items):
    """date_items: list of (iso_date, label)"""
    ikb = InlineKeyboardMarkup(row_width=5)
    for iso, label in date_items:
        ikb.insert(InlineKeyboardButton(label, callback_data=f"date_{iso}"))
    ikb.add(InlineKeyboardButton("❌ Скасувати", callback_data="cancel_flow"))
    return ikb


def time_slots_ikb(slots):
    ikb = InlineKeyboardMarkup(row_width=4)
    for t in slots:
        ikb.insert(InlineKeyboardButton(t, callback_data=f"time_{t}"))
    ikb.add(InlineKeyboardButton("❌ Скасувати", callback_data="cancel_flow"))
    return ikb


def bookings_ikb(bookings):
    """
    bookings: list of tuples (id, service_name, start_utc, end_utc, event_id)
    Виводимо: "Послуга • HH:MM DD.MM.YYYY" (без внутрішнього ID)
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from config import settings

    TZ = ZoneInfo(settings.TZ)
    UTC = ZoneInfo("UTC")

    ikb = InlineKeyboardMarkup(row_width=1)
    for b in bookings:
        try:
            start_local = datetime.fromisoformat(b[2]).replace(tzinfo=UTC).astimezone(TZ)
            label = f"{b[1]} • {start_local.strftime('%H:%M %d.%m.%Y')}"
        except Exception:
            label = f"{b[1]}"
        ikb.add(InlineKeyboardButton(label, callback_data=f"bk_{b[0]}"))
    return ikb


def cancel_confirm_ikb(booking_id: int):
    # ОДИН стовпець, кожна кнопка на окремому рядку → текст не обрізається
    ikb = InlineKeyboardMarkup(row_width=1)
    ikb.add(InlineKeyboardButton("🚫 Скасувати запис", callback_data=f"cancel_{booking_id}"))
    ikb.add(InlineKeyboardButton("↩️ Назад", callback_data="back_to_list"))
    return ikb


def confirm_ikb():
    ikb = InlineKeyboardMarkup(row_width=2)
    ikb.add(
        InlineKeyboardButton("✅ Підтвердити", callback_data="confirm_booking"),
        InlineKeyboardButton("❌ Скасувати", callback_data="cancel_flow"),
    )
    return ikb


def phone_request_kb():
    """Reply-клавіатура для запиту номера телефону або ручного вводу."""
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("📱 Поділитися контактом", request_contact=True))
    kb.add(KeyboardButton("Введу номер вручну"))
    return kb