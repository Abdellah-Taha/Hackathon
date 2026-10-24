import json

import pytest
from PIL import Image

import diagnose as d
import weather as w

GOOD = {
    "is_plant": True,
    "plant_name": "Tomato",
    "status": "diseased",
    "health_score": 42,
    "summary": "Brown spots with yellow halos on lower leaves.",
    "issues": [
        {
            "name": "Early blight",
            "kind": "disease",
            "confidence": 0.8,
            "severity": "medium",
            "evidence": "concentric rings on lower leaves",
        }
    ],
    "care_steps": ["Remove affected leaves", "Water at the base"],
    "see_expert_if": "spots reach the fruit",
    "photo_tips": "",
}


def img(size=(2000, 1000)):
    return Image.new("RGBA", size, (30, 140, 40, 255))


# ------------------------------ parsing ------------------------------------ #
def test_extract_json_handles_fences_and_chatter():
    raw = "Sure!\n```json\n" + json.dumps(GOOD) + "\n```\nHope it helps."
    assert d.extract_json(raw)["plant_name"] == "Tomato"


def test_extract_json_rejects_text_without_json():
    with pytest.raises(ValueError):
        d.extract_json("I cannot help with that.")


def test_percent_confidence_and_case_are_normalised():
    bad = dict(GOOD, status="Diseased", health_score=42.6)
    bad["issues"] = [dict(GOOD["issues"][0], confidence="85%", kind="Disease", severity="MEDIUM")]
    r = d.parse_report(json.dumps(bad))
    assert r.status == "diseased"
    assert r.health_score == 43
    assert r.issues[0].confidence == pytest.approx(0.85)
    assert r.issues[0].kind == "disease"


def test_score_is_clamped():
    assert d.parse_report(json.dumps(dict(GOOD, health_score=250))).health_score == 100


def test_invalid_enum_raises_value_error():
    with pytest.raises(ValueError):
        d.parse_report(json.dumps(dict(GOOD, status="dying")))


# ------------------------------ images ------------------------------------- #
def test_prepare_image_downscales_and_returns_jpeg():
    data = d.prepare_image(img())
    assert data[:2] == b"\xff\xd8"
    import io

    out = Image.open(io.BytesIO(data))
    assert max(out.size) <= d.MAX_SIDE


# ------------------------------ diagnose() --------------------------------- #
def test_diagnose_retries_once_on_malformed_json(monkeypatch):
    calls = []

    def fake(prompt, jpeg):
        calls.append(prompt)
        return "not json" if len(calls) == 1 else json.dumps(GOOD)

    monkeypatch.setitem(d.BACKENDS, "fake", fake)
    report = d.diagnose(img(), backend="fake")
    assert report.plant_name == "Tomato"
    assert len(calls) == 2
    assert "not valid JSON" in calls[1]


def test_diagnose_gives_up_after_retries(monkeypatch):
    monkeypatch.setitem(d.BACKENDS, "fake", lambda p, j: "nope")
    with pytest.raises(d.DiagnosisError):
        d.diagnose(img(), backend="fake")


def test_backend_error_is_not_retried(monkeypatch):
    calls = []

    def boom(p, j):
        calls.append(1)
        raise RuntimeError("quota exceeded")

    monkeypatch.setitem(d.BACKENDS, "fake", boom)
    with pytest.raises(d.DiagnosisError, match="quota exceeded"):
        d.diagnose(img(), backend="fake")
    assert len(calls) == 1


def test_unknown_backend():
    with pytest.raises(d.DiagnosisError):
        d.diagnose(img(), backend="nope")


def test_prompt_includes_language_hint_and_weather():
    p = d.build_prompt("Français", "menthe", "Rabat: 25°C")
    assert "Français" in p and "menthe" in p and "Rabat: 25°C" in p
    assert "{" in p and "{language}" not in p  # template fully formatted


# ------------------------------ rendering ---------------------------------- #
def test_markdown_for_diagnosed_plant():
    md = d.to_markdown(d.Report.model_validate(GOOD), ["Skip watering"])
    assert "Early blight" in md and "42/100" in md and "Skip watering" in md
    assert "not a lab diagnosis" in md


def test_markdown_for_non_plant():
    md = d.to_markdown(d.Report(is_plant=False))
    assert "No plant detected" in md


def test_markdown_warns_on_low_confidence():
    low = dict(GOOD)
    low["issues"] = [dict(GOOD["issues"][0], confidence=0.3)]
    assert "Confidence is low" in d.to_markdown(d.Report.model_validate(low))


# ------------------------------ weather ------------------------------------ #
def wx(**kw):
    base = dict(city="Rabat", temp_c=22, humidity=60, rain_next_3d_mm=0, temp_max_c=26, temp_min_c=14)
    base.update(kw)
    return w.Weather(**base)


def test_weather_tips_rules():
    disease = d.Report.model_validate(GOOD)
    healthy = d.Report(issues=[])
    assert any("fungal" in t for t in w.weather_tips(disease, wx(humidity=85)))
    assert any("skip watering" in t for t in w.weather_tips(healthy, wx(rain_next_3d_mm=12)))
    assert any("Heat" in t for t in w.weather_tips(healthy, wx(temp_max_c=39)))
    assert any("Frost" in t for t in w.weather_tips(healthy, wx(temp_min_c=1)))
    assert any("dry spell" in t.lower() for t in w.weather_tips(healthy, wx(humidity=30)))
    assert w.weather_tips(healthy, wx()) == []


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_fetch_weather_parses_open_meteo(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if "geocoding" in url:
            return FakeResp({"results": [{"name": "Rabat", "latitude": 34.0, "longitude": -6.8}]})
        return FakeResp(
            {
                "current": {"temperature_2m": 21.5, "relative_humidity_2m": 70},
                "daily": {
                    "precipitation_sum": [0.0, 2.5, None],
                    "temperature_2m_max": [24, 27, 25],
                    "temperature_2m_min": [13, 12, 15],
                },
            }
        )

    monkeypatch.setattr(w.requests, "get", fake_get)
    got = w.fetch_weather("Rabat")
    assert got.rain_next_3d_mm == pytest.approx(2.5)
    assert got.temp_max_c == 27 and got.temp_min_c == 12
    assert "Rabat" in w.summarize(got)


def test_fetch_weather_unknown_city(monkeypatch):
    monkeypatch.setattr(w.requests, "get", lambda *a, **k: FakeResp({}))
    with pytest.raises(w.WeatherError, match="not found"):
        w.fetch_weather("Atlantis")


def test_fetch_weather_network_failure(monkeypatch):
    def down(*a, **k):
        raise w.requests.ConnectionError("offline")

    monkeypatch.setattr(w.requests, "get", down)
    with pytest.raises(w.WeatherError, match="unavailable"):
        w.fetch_weather("Rabat")
