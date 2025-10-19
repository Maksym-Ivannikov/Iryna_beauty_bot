from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional
import logging
import asyncpg

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

    start_utc_iso = start_local.astimezone(UTC).isoformat()
    end_utc_iso   = end_local.astimezone(UTC).isoformat()

    db_url = settings.DATABASE_URL
    if not db_url:
        logging.warning("[reminders] DATABASE_URL is empty — skipping job")
        return

    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(
            """
            SELECT b.id, b.client_id, b.start_utc, s.name
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            WHERE b.status = 'active' AND b.start_utc BETWEEN $1::timestamptz AND $2::timestamptz
            ORDER BY b.start_utc
            """,
            start_utc_iso, end_utc_iso
        )

        logging.info(f"[reminders] target={target} rows={len(rows)} window={start_utc_iso}..{end_utc_iso}")

        for r in rows:
            client_id = r["client_id"]
            start_dt = r["start_utc"]
            service_name = r["name"]

            c = await conn.fetchrow(
                "SELECT tg_id, first_name, username FROM clients WHERE id=$1",
                client_id
            )
            if not c:
                continue
            tg_id = c["tg_id"]

            try:
                time_str = start_dt.astimezone(TZ).strftime("%H:%M")
            except Exception:
                time_str = "--:--"

            msg = (
                "Добрий вечір!🫶🏻\n"
                f"Чекаю завтра о {time_str} — {service_name}.\n\n"
                "За адресою:\n"
                "Strada Ion Bogdan 18,\n"
                "Верхній домофон 6\n"
                "https://maps.app.goo.gl/7AJXbvq1o9aeDUHR7?g_st=ipc"
            )

            try:
                await bot.send_message(tg_id, msg)
            except Exception as e:
                logging.warning(f"[reminders] send failed to {tg_id}: {e}")
    finally:
        await conn.close()

def setup_scheduler(bot) -> None:
    """Реєструє джоби в AsyncIOScheduler (без catch-up після рестартів)."""
    global scheduler
    if scheduler is not None:
        return

    scheduler = AsyncIOScheduler(
        timezone=TZ,
        job_defaults={"misfire_grace_time": 1, "coalesce": True},
    )

    scheduler.add_job(
        _send_evening_reminders,
        trigger=CronTrigger(hour=20, minute=0, timezone=TZ),
        args=[bot],
        kwargs={"target": "tomorrow"},
        id="evening_reminders_prod",
        replace_existing=True,
        misfire_grace_time=1,
    )

    # Тест-джоба (вимкнена)
    # scheduler.add_job(
    #     _send_evening_reminders,
    #     trigger=CronTrigger(minute="*/1", timezone=TZ),
    #     args=[bot],
    #     kwargs={"target": "today"},
    #     id="evening_reminders_test",
    #     replace_existing=True,
    #     misfire_grace_time=1,
    # )

    scheduler.start()
