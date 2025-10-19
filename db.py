import os
from pathlib import Path
from datetime import datetime
import aiosqlite

from config import settings

DB_PATH = settings.DB_PATH
DB_DIR = Path(DB_PATH).parent

INIT_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id INTEGER NOT NULL UNIQUE,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  phone TEXT,
  birth_day INTEGER,
  birth_month INTEGER
);

CREATE TABLE IF NOT EXISTS services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  duration_min INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL,
  service_id INTEGER NOT NULL,
  start_utc TEXT NOT NULL,
  end_utc TEXT NOT NULL,
  event_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  canceled_at TEXT,
  FOREIGN KEY(client_id) REFERENCES clients(id),
  FOREIGN KEY(service_id) REFERENCES services(id)
);

CREATE INDEX IF NOT EXISTS idx_bookings_client ON bookings(client_id);
CREATE INDEX IF NOT EXISTS idx_bookings_start ON bookings(start_utc);
"""

async def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SQL)
        await db.commit()

async def upsert_client(tg_id: int, username: str, first_name: str, last_name: str,
                        phone: str = None, birth_day: int = None, birth_month: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO clients(tg_id, username, first_name, last_name, phone, birth_day, birth_month)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(tg_id) DO UPDATE SET
              username=excluded.username,
              first_name=excluded.first_name,
              last_name=excluded.last_name,
              phone=COALESCE(excluded.phone, clients.phone),
              birth_day=COALESCE(excluded.birth_day, clients.birth_day),
              birth_month=COALESCE(excluded.birth_month, clients.birth_month)
            """,
            (tg_id, username, first_name, last_name, phone, birth_day, birth_month)
        )
        await db.commit()

async def get_client_by_tg(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, tg_id, username, first_name, last_name, phone, birth_day, birth_month FROM clients WHERE tg_id=?",
            (tg_id,))
        return await cur.fetchone()

async def list_services(active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        if active_only:
            cur = await db.execute("SELECT id, name, duration_min FROM services WHERE active=1 ORDER BY id")
        else:
            cur = await db.execute("SELECT id, name, duration_min, active FROM services ORDER BY id")
        return await cur.fetchall()

async def add_service(name: str, duration_min: int, active: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO services(name, duration_min, active) VALUES(?,?,?)",
            (name, duration_min, active))
        await db.commit()

async def get_service(service_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name, duration_min FROM services WHERE id=?",
            (service_id,))
        return await cur.fetchone()

async def update_service_duration(name: str, duration_min: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE services SET duration_min=?, active=1 WHERE name=?",
            (duration_min, name)
        )
        await db.commit()

async def deactivate_missing_services(active_names: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders = ",".join("?" * len(active_names)) or "''"
        await db.execute(
            f"UPDATE services SET active=0 WHERE name NOT IN ({placeholders})",
            active_names
        )
        await db.commit()

async def create_booking(client_id: int, service_id: int, start_utc: str, end_utc: str, event_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO bookings(client_id, service_id, start_utc, end_utc, event_id, status, created_at) "
            "VALUES(?,?,?,?,?,'active',?)",
            (client_id, service_id, start_utc, end_utc, event_id, now)
        )
        await db.commit()

async def list_future_active_bookings_by_client(client_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT b.id, s.name, b.start_utc, b.end_utc, b.event_id "
            "FROM bookings b JOIN services s ON s.id=b.service_id "
            "WHERE b.client_id=? AND b.status='active' AND b.start_utc >= datetime('now') "
            "ORDER BY b.start_utc",
            (client_id,))
        return await cur.fetchall()

async def get_booking(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, client_id, service_id, start_utc, end_utc, event_id, status "
            "FROM bookings WHERE id=?", (booking_id,))
        return await cur.fetchone()

async def cancel_booking(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "UPDATE bookings SET status='canceled', canceled_at=? WHERE id=?",
            (now, booking_id))
        await db.commit()

async def sync_services_with_seed(seed_services: list[tuple[str, int]]):
    """
    Синхронізація БД з SERVICES_SEED:
    - додає нові
    - оновлює тривалість існуючих
    - деактивує ті, яких немає в seed
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # поточні
        cur = await db.execute("SELECT name, duration_min FROM services")
        current = {name: dur for name, dur in await cur.fetchall()}

        seed_names = [name for name, _ in seed_services]

        # додаємо або оновлюємо
        for name, dur in seed_services:
            if name not in current:
                await db.execute(
                    "INSERT INTO services(name, duration_min, active) VALUES(?,?,1)",
                    (name, dur)
                )
            else:
                await db.execute(
                    "UPDATE services SET duration_min=?, active=1 WHERE name=?",
                    (dur, name)
                )

        # деактивуємо ті, яких нема у seed
        placeholders = ",".join("?" * len(seed_names)) or "''"
        await db.execute(
            f"UPDATE services SET active=0 WHERE name NOT IN ({placeholders})",
            seed_names
        )
        await db.commit()
