from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional
import aiosqlite

from config import settings

TZ = ZoneInfo(settings.TZ)
UTC = ZoneInfo("UTC")

scheduler: Optional[AsyncIOScheduler] = None


async def _send_evening_reminders(bot, *, target: str = "tomorrow") -> None:
    """
    Розсилка нагадувань:
      target="tomorrow" — як у проді: нагадуємо про ЗАВТРАшні записи (надсилаємо сьогодні о 20:00).
      target="today"    — зручно для тесту: шукаємо СЬОГОДНІшні записи (для щохвилинного тригера).
    """
    now_local = datetime.now(TZ)
    if target == "today":
        target_date = now_local.date()
    else:
        target_date = now_local.date() + timedelta(days=1)

    start_local = datetime.combine(target_date, dtime(0, 0)).replace(tzinfo=TZ)
    end_local = datetime.combine(target_date, dtime(23, 59, 59)).replace(tzinfo=TZ)

    start_utc = start_local.astimezone(UTC).isoformat()
    end_utc = end_local.astimezone(UTC).isoformat()

    async with aiosqlite.connect("beauty.db") as db:
        cur = await db.execute(
            """
            SELECT b.id, b.client_id, b.start_utc, s.name
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            WHERE b.status = 'active' AND b.start_utc BETWEEN ? AND ?
            ORDER BY b.start_utc
            """,
            (start_utc, end_utc),
        )
        rows = await cur.fetchall()

        for _, client_id, start_utc_iso, service_name in rows:
            cur2 = await db.execute(
                "SELECT tg_id, first_name, username FROM clients WHERE id = ?",
                (client_id,),
            )
            c = await cur2.fetchone()
            if not c:
                continue
            tg_id, first_name, username = c

            try:
                dt_utc = datetime.fromisoformat(start_utc_iso)
                time_str = dt_utc.astimezone(TZ).strftime("%H:%M")
            except Exception:
                time_str = "--:--"

            msg = (
                "Добрий вечір!🫶🏻\n"
                f"Чекаю завтра о {time_str}.\n\n"
                "За адресою:\n"
                "Strada Ion Bogdan 18,\n"
                "Верхній домофон 6\n"
                "https://maps.app.goo.gl/7AJXbvq1o9aeDUHR7?g_st=ipc"
            )

            try:
                await bot.send_message(tg_id, msg)
            except Exception:
                # ігноруємо разові помилки відправки, щоб не зупиняти цикл
                pass


def setup_scheduler(bot) -> None:
    """
    Реєструє джоби в AsyncIOScheduler.
    ВАЖЛИВО: add_job приймає корутину напряму — без lambda.
    """
    global scheduler
    if scheduler is not None:
        return

    scheduler = AsyncIOScheduler(timezone=TZ)

    # ✅ ПРОД: щодня о 20:00 — нагадування на ЗАВТРА
    scheduler.add_job(
        _send_evening_reminders,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot],
        kwargs={"target": "tomorrow"},
        id="evening_reminders_prod",
        replace_existing=True,
    )

    # 🧪 ТЕСТ: раз на хвилину — шукаємо СЬОГОДНІшні записи (увімкни за потреби, потім вимкни)
    #scheduler.add_job(
    #    _send_evening_reminders,
    #    trigger=CronTrigger(minute="*/1"),
    #    args=[bot],
    #    kwargs={"target": "today"},
    #    id="evening_reminders_test",
    #    replace_existing=True,
    #)

    scheduler.start()
