"""Optional weather module (Open-Meteo: free, no API key).

Leave the city box empty in the app and none of this runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherError(RuntimeError):
    """Raised when the city is unknown or the weather service is unreachable."""


@dataclass
class Weather:
    city: str
    temp_c: float
    humidity: float  # %
    rain_next_3d_mm: float
    temp_max_c: float  # hottest day in the next 3 days
    temp_min_c: float  # coldest night in the next 3 days


class _HasIssues(Protocol):
    issues: list


def fetch_weather(city: str, timeout: float = 8.0) -> Weather:
    try:
        geo = requests.get(
            GEOCODE_URL, params={"name": city, "count": 1}, timeout=timeout
        )
        geo.raise_for_status()
        results = geo.json().get("results")
        if not results:
            raise WeatherError(f"city '{city}' not found")
        place = results[0]

        wx = requests.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m",
                "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min",
                "forecast_days": 3,
                "timezone": "auto",
            },
            timeout=timeout,
        )
        wx.raise_for_status()
        data = wx.json()
        daily = data["daily"]
        return Weather(
            city=place.get("name", city),
            temp_c=data["current"]["temperature_2m"],
            humidity=data["current"]["relative_humidity_2m"],
            rain_next_3d_mm=sum(x or 0 for x in daily["precipitation_sum"]),
            temp_max_c=max(daily["temperature_2m_max"]),
            temp_min_c=min(daily["temperature_2m_min"]),
        )
    except WeatherError:
        raise
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise WeatherError(f"weather service unavailable ({exc})") from exc


def summarize(w: Weather) -> str:
    return (
        f"{w.city}: {w.temp_c:.0f}°C now, humidity {w.humidity:.0f}%, "
        f"{w.rain_next_3d_mm:.0f} mm rain expected over 3 days, "
        f"highs up to {w.temp_max_c:.0f}°C and lows down to {w.temp_min_c:.0f}°C."
    )


def weather_tips(report: _HasIssues, w: Weather) -> list[str]:
    """Simple, transparent rules that combine the diagnosis with the forecast."""
    kinds = {i.kind for i in report.issues}
    tips: list[str] = []

    if w.humidity >= 75 and "disease" in kinds:
        tips.append(
            "High humidity helps fungal diseases spread: water the soil (not the leaves) "
            "in the morning and improve airflow between plants."
        )
    if w.rain_next_3d_mm >= 5:
        tips.append(
            f"About {w.rain_next_3d_mm:.0f} mm of rain is forecast: skip watering "
            "and check that the pot or bed drains well."
        )
    elif w.rain_next_3d_mm < 1 and ("water" in kinds or w.humidity < 40):
        tips.append(
            "A dry spell is ahead: water deeply but less often, and add mulch to hold moisture."
        )
    if w.temp_max_c >= 35:
        tips.append(
            f"Heat up to {w.temp_max_c:.0f}°C is coming: water early morning or evening "
            "and shade young or stressed plants at midday."
        )
    if w.temp_min_c <= 3:
        tips.append("Frost risk: cover the plant or bring it indoors overnight.")
    return tips
