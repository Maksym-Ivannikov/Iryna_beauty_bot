from __future__ import annotations
import datetime as dt
import json
import os
from typing import Optional
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_service = None


def get_service():
    """Повертає кешований клієнт Google Calendar API (через сервісний акаунт)."""
    global _service
    if _service is not None:
        return _service

    creds = None

    # 1️⃣ Якщо існує файл у volume (/data/service_account.json)
    if os.path.exists(settings.GCREDS_PATH):
        creds = Credentials.from_service_account_file(settings.GCREDS_PATH, scopes=SCOPES)

    # 2️⃣ Якщо ні — пробуємо з ENV
    elif settings.GCREDS_JSON:
        try:
            creds_dict = json.loads(settings.GCREDS_JSON)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except Exception as e:
            raise RuntimeError(f"❌ Invalid GOOGLE_CREDENTIALS_JSON: {e}")

    if not creds:
        raise RuntimeError("❌ No Google service account credentials provided")

    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def is_slot_free(start_utc: dt.datetime, end_utc: dt.datetime) -> bool:
    service = get_service()
    body = {
        "timeMin": start_utc.isoformat().replace("+00:00", "Z"),
        "timeMax": end_utc.isoformat().replace("+00:00", "Z"),
        "items": [{"id": settings.GCAL_ID}],
    }
    fb = service.freebusy().query(body=body).execute()
    busy = fb["calendars"][settings.GCAL_ID]["busy"]
    return len(busy) == 0


def create_event(summary: str, description: str, start_utc: dt.datetime, end_utc: dt.datetime) -> str:
    service = get_service()
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_utc.isoformat().replace("+00:00", "Z"), "timeZone": "UTC"},
        "end":   {"dateTime": end_utc.isoformat().replace("+00:00", "Z"), "timeZone": "UTC"},
    }
    created = service.events().insert(calendarId=settings.GCAL_ID, body=event_body).execute()
    return created["id"]


def delete_event(event_id: str) -> None:
    service = get_service()
    service.events().delete(calendarId=settings.GCAL_ID, eventId=event_id).execute()