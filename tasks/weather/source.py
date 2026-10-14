import asyncio
import json
import urllib.parse
import urllib.request
from pathlib import Path

from core import config

# ---------------------------------------------------------------------------
# Where the forecast comes from: Open-Meteo (free, no key), for the place in
# .env (WEATHER_LAT, WEATHER_LON: never in anything committed, and never in a
# log). The one module that talks to the outside.
#
# With WEATHER_SOURCE set to a file, that recorded forecast is read instead
# and the network is never asked: the self-test's, and the tests'.
# ---------------------------------------------------------------------------
URL = "https://api.open-meteo.com/v1/forecast"
DAILY = "temperature_2m_min,temperature_2m_max,precipitation_probability_max,weather_code,wind_speed_10m_max,wind_direction_10m_dominant"
# By the hour: the chance of rain, and the temperature (for a question about a part of the day)
HOURLY = "precipitation_probability,temperature_2m"
TIMEOUT = 8


class NoPlace(Exception):
    """WEATHER_LAT and WEATHER_LON are not set: there is nowhere to ask about."""


def address() -> str:
    if config.WEATHER_LAT is None or config.WEATHER_LON is None:
        raise NoPlace("WEATHER_LAT and WEATHER_LON are not set in .env")
    asked = {
        "latitude": config.WEATHER_LAT, "longitude": config.WEATHER_LON, "daily": DAILY, "hourly": HOURLY,
        "timezone": getattr(config.TIMEZONE, "key", "Pacific/Auckland"), "forecast_days": 1, "wind_speed_unit": "kmh",
    }
    return f"{URL}?{urllib.parse.urlencode(asked)}"


def _get() -> bytes:
    if config.WEATHER_SOURCE:
        return Path(config.WEATHER_SOURCE).read_bytes()
    request = urllib.request.Request(address(), headers={"User-Agent": "assistant-bot (personal use)"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return answer.read()


async def fetch() -> dict:
    """Today's forecast, as the source gives it. Off the event loop. Raises on any failure."""
    return json.loads(await asyncio.to_thread(_get))
