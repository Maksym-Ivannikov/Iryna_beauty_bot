from dataclasses import dataclass
import os

@dataclass
class Settings:
    # Telegram
    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    
    # Google Calendar
    GCAL_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    GCRED_PATH: str = os.getenv("GOOGLE_OAUTH_CREDENTIALS_PATH", "./credentials.json")
    GTOKEN_PATH: str = os.getenv("GOOGLE_OAUTH_TOKEN_PATH", "./token.json")

    # JSON із креденшалами (для Railway)
    GCRED_JSON: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    GTOKEN_JSON: str = os.getenv("GOOGLE_TOKEN_JSON", "")

    # Інше
    TZ: str = os.getenv("TIMEZONE", "Europe/Bucharest")
    BOOKING_HORIZON_DAYS: int = int(os.getenv("BOOKING_HORIZON_DAYS", "30"))

    # База даних (Volume)
    DB_PATH: str = os.getenv("DB_PATH", "/data/beauty.db")

settings = Settings()
