from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional
import aiosqlite
import logging

from config import settings

TZ = ZoneInfo(settings.TZ)
UTC = ZoneInfo("UTC")

scheduler: Optional[AsyncIOScheduler] = None


async def _send_evening_reminders(bot, *, target: str = "tomorrow") -> None:
    """
    target="tomorrow" — прод: нагадуємо про завтрашні записи (шлемо сьогодні ввечері).
    target="today"    — тест: шукаємо сьогоднішні записи.
    """
    now_local = datetime.now(TZ)
    target_date = now_local.date() if target == "today" else (now_local + timedelta(days=1)).date()

    start_local = datetime.combine(target_date, dtime(0, 0, tzinfo=TZ))
    end_local   = datetime.combine(target_date, dtime(23, 59, 59, tzinfo=TZ))

    start_utc = start_local.astimezone(UTC).isoformat()
    end_utc   = end_local.astimezone(UTC).isoformat()

    db_path = settings.DB_PATH

    async with aiosqlite.connect(db_path) as db:
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

        logging.info(f"[reminders] target={target} rows={len(rows)} window={start_utc}..{end_utc} db={db_path}")

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
            except Exception as e:
                logging.warning(f"[reminders] send failed to {tg_id}: {e}")


def setup_scheduler(bot) -> None:
    """Реєструє джоби в AsyncIOScheduler (без catch-up після рестартів)."""
    global scheduler
    if scheduler is not None:
        return

    scheduler = AsyncIOScheduler(
        timezone=TZ,
        job_defaults={
            "misfire_grace_time": 0,  # якщо пропустили час запуску — не наздоганяємо
            "coalesce": True
        },
    )

    # ТЕСТ: щодня о 20:55 за локальною TZ — нагадування на завтра
    scheduler.add_job(
        _send_evening_reminders,
        trigger=CronTrigger(hour=20, minute=57, timezone=TZ),
        args=[bot],
        kwargs={"target": "tomorrow"},
        id="evening_reminders_prod",
        replace_existing=True,
        misfire_grace_time=0,  # додаткова гарантія, що catch-up не буде
    )

    # (за потреби вмикай тест-щохвилини — але зараз вимкнено)
    # scheduler.add_job(
    #     _send_evening_reminders,
    #     trigger=CronTrigger(minute="*/1", timezone=TZ),
    #     args=[bot],
    #     kwargs={"target": "today"},
    #     id="evening_reminders_test",
    #     replace_existing=True,
    #     misfire_grace_time=0,
    # )

    scheduler.start()
