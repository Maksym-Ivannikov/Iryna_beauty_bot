from dataclasses import dataclass
import os

@dataclass
class Settings:
    # Telegram
    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

    # Google Calendar (через сервісний акаунт)
    GCAL_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    GCREDS_JSON: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    GCREDS_PATH: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "/data/service_account.json")

    # Інше
    TZ: str = os.getenv("TIMEZONE", "Europe/Bucharest")
    BOOKING_HORIZON_DAYS: int = int(os.getenv("BOOKING_HORIZON_DAYS", "30"))

    # База даних
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

settings = Settings()
