import asyncpg
from datetime import datetime
from typing import List, Tuple, Optional
from config import settings

# Повертаємо з функцій ті ж «кортежі», що й у SQLite-версії,
# щоб НЕ міняти решту коду (bot.py, keyboards.py тощо).

DDL = """
CREATE TABLE IF NOT EXISTS clients (
  id SERIAL PRIMARY KEY,
  tg_id BIGINT UNIQUE NOT NULL,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  phone TEXT,
  birth_day INT,
  birth_month INT
);

CREATE TABLE IF NOT EXISTS services (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  duration_min INT NOT NULL,
  active INT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bookings (
  id SERIAL PRIMARY KEY,
  client_id INT REFERENCES clients(id),
  service_id INT NOT NULL REFERENCES services(id),
  start_utc TIMESTAMPTZ NOT NULL,
  end_utc   TIMESTAMPTZ NOT NULL,
  event_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  canceled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bookings_client ON bookings(client_id);
CREATE INDEX IF NOT EXISTS idx_bookings_start ON bookings(start_utc);
"""

def _url() -> str:
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is empty. Set it in Railway Variables for the bot service.")
    return settings.DATABASE_URL

async def init_db():
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute(DDL)
    finally:
        await conn.close()

# ---- clients ---------------------------------------------------------------

async def upsert_client(
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
    phone: Optional[str] = None,
    birth_day: Optional[int] = None,
    birth_month: Optional[int] = None,
):
    sql = """
    INSERT INTO clients(tg_id, username, first_name, last_name, phone, birth_day, birth_month)
    VALUES($1,$2,$3,$4,$5,$6,$7)
    ON CONFLICT (tg_id) DO UPDATE SET
      username = EXCLUDED.username,
      first_name = EXCLUDED.first_name,
      last_name  = EXCLUDED.last_name,
      phone      = COALESCE(EXCLUDED.phone, clients.phone),
      birth_day  = COALESCE(EXCLUDED.birth_day, clients.birth_day),
      birth_month= COALESCE(EXCLUDED.birth_month, clients.birth_month);
    """
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute(sql, tg_id, username, first_name, last_name, phone, birth_day, birth_month)
    finally:
        await conn.close()

async def get_client_by_tg(tg_id: int):
    conn = await asyncpg.connect(_url())
    try:
        row = await conn.fetchrow(
            "SELECT id, tg_id, username, first_name, last_name, phone, birth_day, birth_month FROM clients WHERE tg_id=$1",
            tg_id
        )
        return tuple(row) if row else None
    finally:
        await conn.close()

# ---- services --------------------------------------------------------------

async def list_services(active_only: bool = True):
    conn = await asyncpg.connect(_url())
    try:
        if active_only:
            rows = await conn.fetch("SELECT id, name, duration_min FROM services WHERE active=1 ORDER BY id")
        else:
            rows = await conn.fetch("SELECT id, name, duration_min, active FROM services ORDER BY id")
        return [tuple(r) for r in rows]
    finally:
        await conn.close()

async def add_service(name: str, duration_min: int, active: int = 1):
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute(
            "INSERT INTO services(name, duration_min, active) VALUES($1,$2,$3) ON CONFLICT (name) DO NOTHING",
            name, duration_min, active
        )
    finally:
        await conn.close()

async def get_service(service_id: int):
    conn = await asyncpg.connect(_url())
    try:
        row = await conn.fetchrow("SELECT id, name, duration_min FROM services WHERE id=$1", service_id)
        return tuple(row) if row else None
    finally:
        await conn.close()

async def create_booking(client_id: int, service_id: int, start_utc: str, end_utc: str, event_id: str):
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute(
            "INSERT INTO bookings(client_id, service_id, start_utc, end_utc, event_id, status, created_at) "
            "VALUES($1,$2,$3::timestamptz,$4::timestamptz,$5,'active', NOW())",
            client_id, service_id, start_utc, end_utc, event_id
        )
    finally:
        await conn.close()

async def list_future_active_bookings_by_client(client_id: int):
    conn = await asyncpg.connect(_url())
    try:
        rows = await conn.fetch(
            "SELECT b.id, s.name, b.start_utc, b.end_utc, b.event_id "
            "FROM bookings b JOIN services s ON s.id=b.service_id "
            "WHERE b.client_id=$1 AND b.status='active' AND b.start_utc >= NOW() "
            "ORDER BY b.start_utc",
            client_id
        )
        # Повертаємо ISO-строки, як у SQLite-версії
        out = []
        for r in rows:
            out.append((r["id"], r["name"], r["start_utc"].isoformat(), r["end_utc"].isoformat(), r["event_id"]))
        return out
    finally:
        await conn.close()

async def get_booking(booking_id: int):
    conn = await asyncpg.connect(_url())
    try:
        row = await conn.fetchrow(
            "SELECT id, client_id, service_id, start_utc, end_utc, event_id, status FROM bookings WHERE id=$1",
            booking_id
        )
        if not row:
            return None
        return (
            row["id"],
            row["client_id"],
            row["service_id"],
            row["start_utc"].isoformat(),
            row["end_utc"].isoformat(),
            row["event_id"],
            row["status"],
        )
    finally:
        await conn.close()

async def cancel_booking(booking_id: int):
    conn = await asyncpg.connect(_url())
    try:
        await conn.execute(
            "UPDATE bookings SET status='canceled', canceled_at=NOW() WHERE id=$1",
            booking_id
        )
    finally:
        await conn.close()

async def sync_services_with_seed(seed_services: list[tuple[str, int]]):
    conn = await asyncpg.connect(_url())
    try:
        # поточні
        rows = await conn.fetch("SELECT name, duration_min FROM services")
        current = {r["name"]: r["duration_min"] for r in rows}
        seed_names = [name for name, _ in seed_services]

        # додаємо/оновлюємо
        for name, dur in seed_services:
            if name not in current:
                await conn.execute(
                    "INSERT INTO services(name, duration_min, active) VALUES($1,$2,1)",
                    name, dur
                )
            else:
                await conn.execute(
                    "UPDATE services SET duration_min=$1, active=1 WHERE name=$2",
                    dur, name
                )

        # деактивація відсутніх у seed
        if seed_names:
            await conn.execute(
                "UPDATE services SET active=0 WHERE name <> ALL($1::text[]) AND active=1",
                seed_names
            )
        else:
            # якщо seed порожній — деактивуємо всі
            await conn.execute("UPDATE services SET active=0 WHERE active=1")
    finally:
        await conn.close()
