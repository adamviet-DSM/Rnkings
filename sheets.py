"""Google Sheets integration with in-memory caching."""

import json
import os
from datetime import datetime, timedelta

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CACHE_TTL = timedelta(minutes=5)
_cache: dict[str, tuple[list, datetime]] = {}


def _get_client() -> gspread.Client:
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise EnvironmentError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set. "
            "See .env.example for setup instructions."
        )
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _fetch_with_cache(cache_key: str, fetch_fn) -> list[dict]:
    now = datetime.now()
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return data
    data = fetch_fn()
    _cache[cache_key] = (data, now)
    return data


def get_teams() -> list[dict]:
    """Fetch all rows from the Teams sheet."""
    def fetch():
        sheet_id = os.getenv("TEAMS_SHEET_ID")
        if not sheet_id:
            raise EnvironmentError("TEAMS_SHEET_ID is not set.")
        client = _get_client()
        ws = client.open_by_key(sheet_id).get_worksheet(0)
        return ws.get_all_records()

    return _fetch_with_cache("teams", fetch)


def get_games() -> list[dict]:
    """Fetch all rows from the Game Tracker sheet."""
    def fetch():
        sheet_id = os.getenv("GAMES_SHEET_ID")
        if not sheet_id:
            raise EnvironmentError("GAMES_SHEET_ID is not set.")
        client = _get_client()
        ws = client.open_by_key(sheet_id).get_worksheet(0)
        return ws.get_all_records()

    return _fetch_with_cache("games", fetch)


def invalidate_cache() -> None:
    """Clear the in-memory cache, forcing a fresh fetch on next request."""
    _cache.clear()
