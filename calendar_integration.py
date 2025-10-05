from __future__ import annotations
import datetime as dt
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_service = None


def get_service():
    """Повертає кешований клієнт Google Calendar API."""
    global _service
    if _service is not None:
        return _service
    creds = Credentials.from_authorized_user_file(settings.GTOKEN_PATH, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    # Вимикаємо discovery-кеш, щоб не було зайвого лог-повідомлення
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