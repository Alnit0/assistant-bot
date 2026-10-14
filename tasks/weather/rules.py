from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Weather: a forecast read into a few plain values, and those values in one or
# two lines. Pure, and no request to Claude: the words are a template.
#
#   🌤️ Weather · 14° to 20° · drizzle
#   61% rain after 1pm · wind 15 km/h N
# ---------------------------------------------------------------------------
UNAVAILABLE = "Weather unavailable"
DRY_UNDER = 5  # a chance of rain under this is "no rain"
WHEN_FROM = 30  # "after 2pm" is said only for a chance of at least this
MORNING = 7  # rain from this hour or before is "from the morning", not "after"

# What the sky is doing, by the WMO weather code the forecast gives
_SKY = (
    ((0,), "clear"), ((1,), "mostly clear"), ((2,), "partly cloudy"), ((3,), "cloudy"), ((45, 48), "fog"),
    ((51, 53, 55, 56, 57), "drizzle"), ((61, 63, 65, 66, 67), "rain"), ((71, 73, 75, 77), "snow"),
    ((80, 81, 82), "showers"), ((85, 86), "snow showers"), ((95, 96, 99), "thunderstorms"),
)
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class Forecast:
    low: int  # °C
    high: int
    rain: int  # the day's highest chance of rain, %
    rain_from: int | None  # the hour it first gets likely (0 to 23), if that can be said
    wind: int  # km/h, the day's strongest
    direction: str  # where it blows from: "SW"
    sky: str  # a word: "showers"


def sky(code) -> str:
    return next((word for codes, word in _SKY if code in codes), "")


def compass(degrees: float) -> str:
    """Where the wind is from, to the nearest of eight points."""
    return _COMPASS[int((float(degrees) % 360 + 22.5) // 45) % 8]


def read(data: dict) -> Forecast:
    """A forecast as the source gives it (Open-Meteo's daily and hourly lists
    for one day) into the few values a line needs. Raises ValueError for one
    that can't be read: nothing is guessed."""
    try:
        daily = data["daily"]
        low, high = round(daily["temperature_2m_min"][0]), round(daily["temperature_2m_max"][0])
        rain = round(daily["precipitation_probability_max"][0] or 0)
        wind = round(daily["wind_speed_10m_max"][0])
        direction = compass(daily["wind_direction_10m_dominant"][0])
        word = sky(daily["weather_code"][0])
        hourly = [chance or 0 for chance in (data.get("hourly") or {}).get("precipitation_probability") or []]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(f"the forecast can't be read ({error!r})") from error
    start = None
    if rain >= WHEN_FROM and len(hourly) == 24:
        likely = max(WHEN_FROM, rain - 10)
        start = next((hour for hour, chance in enumerate(hourly) if chance >= likely), None)
    return Forecast(low, high, rain, start, wind, direction, word)


def hour_text(hour: int) -> str:
    """An hour of the day as a glance wants it: "2pm", "11am"."""
    return f"{hour % 12 or 12}{'am' if hour < 12 else 'pm'}"


def rain_text(forecast: Forecast) -> str:
    if forecast.rain < DRY_UNDER:
        return "no rain"
    said = f"{forecast.rain}% rain"
    if forecast.rain_from is None:
        return said
    return f"{said} from the morning" if forecast.rain_from <= MORNING else f"{said} after {hour_text(forecast.rain_from)}"


def glance(forecast: Forecast) -> str:
    """Beside the name: today's low and high, and a word for the sky."""
    return f"{forecast.low}° to {forecast.high}°" + (f" · {forecast.sky}" if forecast.sky else "")


def detail(forecast: Forecast) -> str:
    """The line under it: the chance of rain and roughly when, and the wind."""
    return f"{rain_text(forecast)} · wind {forecast.wind} km/h {forecast.direction}"


def later(start_hour: int, start_minute: int, every: int = 3, until: int = 20) -> list[tuple[int, int]]:
    """The times of day a forecast is refreshed again after the first refresh: every three hours, none at or after 8:00 pm."""
    found, hour = [], start_hour + every
    while hour < until:
        found.append((hour, start_minute))
        hour += every
    return found


# ---------------------------------------------------------------------------
# Questions (DAY_QUESTIONS): "will it rain?", "what's the weather this
# afternoon?". Answered from the forecast that was kept, in words from a
# template. A number is said only if the forecast has it: with no hours in
# it the day's own figures are said, as the day's.
# ---------------------------------------------------------------------------
MORNING_PART, AFTERNOON, EVENING, TONIGHT, TOMORROW = "morning", "afternoon", "evening", "tonight", "tomorrow"
PARTS = (MORNING_PART, AFTERNOON, EVENING, TONIGHT, TOMORROW)
# The hours of each part of the day: from, up to (not including)
HOURS = {MORNING_PART: (6, 12), AFTERNOON: (12, 18), EVENING: (18, 24), TONIGHT: (18, 24)}
SAID = {"": "for the rest of today", MORNING_PART: "this morning", AFTERNOON: "this afternoon", EVENING: "this evening", TONIGHT: "tonight"}
ONLY_TODAY = "I only have today's forecast."
NONE_YET = "I have no forecast for today yet."


def hours(data: dict, name: str) -> list:
    """One of the forecast's lists by the hour, if it has all 24 of them; else none."""
    found = (data.get("hourly") or {}).get(name) or []
    return list(found) if len(found) == 24 else []


def stretch(part: str, now_hour: int) -> tuple[int, int] | None:
    """The hours a question is about: what is still to come of today, or of
    the part of it that was named. None when that part is over."""
    first, last = HOURS.get(part, (0, 24))
    first = max(first, now_hour)
    return (first, last) if first < last else None


def rain_said(data: dict, forecast: Forecast, part: str, now_hour: int) -> str:
    """Whether it will rain, as a sentence: the highest chance in the hours
    asked about and roughly when. With no hours in the forecast, the day's
    own chance, said as today's."""
    by_hour = hours(data, "precipitation_probability")
    span = stretch(part, now_hour)
    if not by_hour or span is None:
        return f"{rain_text(forecast).capitalize()} today."
    chances = [chance or 0 for chance in by_hour[span[0] : span[1]]]
    top = round(max(chances))
    at = span[0] + chances.index(max(chances))
    when = SAID[part if part in SAID else ""]
    if top < DRY_UNDER:
        return f"No rain expected {when}."
    if top < WHEN_FROM:
        return f"Rain is unlikely {when}: {top}% at most, around {hour_text(at)}."
    likely = [span[0] + offset for offset, chance in enumerate(chances) if chance >= max(WHEN_FROM, top - 10)]
    around = f"between {hour_text(likely[0])} and {hour_text(likely[-1] + 1)}" if len(likely) > 1 else f"around {hour_text(at)}"
    return f"{top}% chance of rain {when}, most likely {around}."


def warmth(data: dict, span: tuple[int, int]) -> str:
    """How warm those hours are, if the forecast has the temperature by the hour: "16° to 19°"."""
    degrees = [each for each in hours(data, "temperature_2m")[span[0] : span[1]] if each is not None]
    if not degrees:
        return ""
    low, high = round(min(degrees)), round(max(degrees))
    return f"{low}°" if low == high else f"{low}° to {high}°"


def answer(data: dict, part: str, rain_only: bool, now_hour: int) -> list[str]:
    """The lines of an answer about today's weather: `part` is "" for the day
    or one of PARTS, `rain_only` when the question was about rain. Raises
    ValueError for a forecast that can't be read."""
    if part == TOMORROW:
        return [ONLY_TODAY]
    forecast = read(data)
    whole_day = [f"**Today** · {glance(forecast)}", detail(forecast)]
    span = stretch(part, now_hour)
    if span is None:
        return [f"{SAID[part].capitalize()} is over.", *whole_day]
    if rain_only:
        return [rain_said(data, forecast, part, now_hour)]
    if part not in HOURS:
        return whole_day
    warm = warmth(data, span)
    return [
        f"**{SAID[part].capitalize()}**" + (f" · {warm}" if warm else ""),
        rain_said(data, forecast, part, now_hour),
        small_wind(forecast),
    ]


def small_wind(forecast: Forecast) -> str:
    return f"wind up to {forecast.wind} km/h {forecast.direction} today"
