import aiosqlite
from datetime import datetime

DB_PATH = "beauty.db"

INIT_SQL = """
PRAGMA foreign_keys = ON;
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
  duration_min INTEGER NOT NULL
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SQL)
        await db.commit()

async def upsert_client(tg_id: int, username: str, first_name: str, last_name: str, phone: str = None, birth_day: int = None, birth_month: int = None):
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
        cur = await db.execute("SELECT id, tg_id, username, first_name, last_name, phone, birth_day, birth_month FROM clients WHERE tg_id=?", (tg_id,))
        return await cur.fetchone()

async def list_services():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name, duration_min FROM services ORDER BY id")
        return await cur.fetchall()

async def add_service(name: str, duration_min: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO services(name, duration_min) VALUES(?,?)", (name, duration_min))
        await db.commit()

async def get_service(service_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, name, duration_min FROM services WHERE id=?", (service_id,))
        return await cur.fetchone()

async def create_booking(client_id: int, service_id: int, start_utc: str, end_utc: str, event_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO bookings(client_id, service_id, start_utc, end_utc, event_id, status, created_at) VALUES(?,?,?,?,?,'active',?)",
            (client_id, service_id, start_utc, end_utc, event_id, now)
        )
        await db.commit()

async def list_future_active_bookings_by_client(client_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT b.id, s.name, b.start_utc, b.end_utc, b.event_id FROM bookings b JOIN services s ON s.id=b.service_id WHERE b.client_id=? AND b.status='active' AND b.start_utc >= datetime('now') ORDER BY b.start_utc",
            (client_id,)
        )
        return await cur.fetchall()

async def get_booking(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, client_id, service_id, start_utc, end_utc, event_id, status FROM bookings WHERE id=?", (booking_id,))
        return await cur.fetchone()

async def cancel_booking(booking_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute("UPDATE bookings SET status='canceled', canceled_at=? WHERE id=?", (now, booking_id))
        await db.commit()