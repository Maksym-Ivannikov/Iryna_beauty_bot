from dataclasses import dataclass
import os

@dataclass
class Settings:
    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    GCAL_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    GCRED_PATH: str = os.getenv("GOOGLE_OAUTH_CREDENTIALS_PATH", "./credentials.json")
    GTOKEN_PATH: str = os.getenv("GOOGLE_OAUTH_TOKEN_PATH", "./token.json")
    TZ: str = os.getenv("TIMEZONE", "Europe/Bucharest")
    BOOKING_HORIZON_DAYS: int = int(os.getenv("BOOKING_HORIZON_DAYS", "30"))

settings = Settings()