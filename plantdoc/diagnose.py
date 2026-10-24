"""PlantDoc core: plant photo -> structured health report.

Two interchangeable backends serve the same open-weight model family:
  * "gemini" - Gemma 4 through the Gemini API (needs GEMINI_API_KEY)
  * "ollama" - a local Gemma 4 build served by Ollama (works offline)

The model is asked for JSON only, and the reply is validated with pydantic so
the UI never has to deal with free-form text.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Callable, Literal

import requests
from PIL import Image
from pydantic import BaseModel, Field, ValidationError, field_validator

MAX_SIDE = 1024  # px; larger photos are downscaled before sending
GEMINI_MODEL = os.getenv("GEMMA_MODEL", "gemma-4-31b-it")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

PROMPT = """You are an experienced plant pathologist and horticulturist.
Look carefully at the attached photo and assess the plant's health.

Reply with ONE JSON object and nothing else (no markdown, no commentary).
Use exactly these keys:

{{
  "is_plant": true or false,
  "plant_name": "best guess of the species, or 'Unknown'",
  "status": "healthy" | "stressed" | "diseased" | "unknown",
  "health_score": integer 0-100 (100 = perfectly healthy; keep it consistent with status),
  "summary": "2-3 sentences describing what you see",
  "issues": [
    {{
      "name": "specific problem, e.g. 'Powdery mildew'",
      "kind": "disease" | "pest" | "nutrient" | "water" | "light" | "heat" | "other",
      "confidence": number between 0 and 1,
      "severity": "low" | "medium" | "high",
      "evidence": "the visible signs that support this (spots, colour, texture, location on the plant)"
    }}
  ],
  "care_steps": ["practical, low-cost actions in priority order"],
  "see_expert_if": "when the person should ask a local agronomist or nursery",
  "photo_tips": "how to take a better photo, only if this one limits your confidence, else empty"
}}

Rules:
- Base every issue on signs that are visible in the photo. Never invent symptoms.
- List at most 3 issues, most likely first. If the plant looks healthy, return an empty list.
- If the image is not a plant, set "is_plant" to false and leave the rest minimal.
- Be honest about uncertainty: lower the confidence when the photo is blurry, dark or too far away.
- Write all text values in {language}. Keep the JSON keys and the enum values in English.
{plant_hint}{weather}"""


class DiagnosisError(RuntimeError):
    """Raised when no valid report could be produced."""


class Issue(BaseModel):
    name: str
    kind: Literal["disease", "pest", "nutrient", "water", "light", "heat", "other"] = "other"
    confidence: float = Field(default=0.5, ge=0, le=1)
    severity: Literal["low", "medium", "high"] = "low"
    evidence: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _percent_to_fraction(cls, v):
        # Some models answer 85 or "85%" instead of 0.85.
        if isinstance(v, str):
            v = float(v.strip().rstrip("%") or 0)
        if v is not None and v > 1:
            v = v / 100
        return max(0.0, min(1.0, v))

    @field_validator("kind", "severity", mode="before")
    @classmethod
    def _lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class Report(BaseModel):
    is_plant: bool = True
    plant_name: str = "Unknown"
    status: Literal["healthy", "stressed", "diseased", "unknown"] = "unknown"
    health_score: int = Field(default=50, ge=0, le=100)
    summary: str = ""
    issues: list[Issue] = Field(default_factory=list)
    care_steps: list[str] = Field(default_factory=list)
    see_expert_if: str = ""
    photo_tips: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _lower_status(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("health_score", mode="before")
    @classmethod
    def _clamp_score(cls, v):
        return max(0, min(100, round(float(v))))


# --------------------------------------------------------------------------- #
# Image + parsing helpers
# --------------------------------------------------------------------------- #
def prepare_image(img: Image.Image) -> bytes:
    """Downscale and re-encode as JPEG so uploads stay small and fast."""
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles ``` fences)."""
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model reply")
    return json.loads(text[start : end + 1])


def parse_report(text: str) -> Report:
    try:
        return Report.model_validate(extract_json(text))
    except (ValueError, ValidationError, TypeError) as exc:
        raise ValueError(f"invalid report: {exc}") from exc


# --------------------------------------------------------------------------- #
# Backends: each takes (prompt, jpeg_bytes) and returns the raw model text
# --------------------------------------------------------------------------- #
def _call_gemini(prompt: str, jpeg: bytes) -> str:
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (get a free key in Google AI Studio).")
    client = genai.Client(api_key=key)
    # Everything goes in the user turn: no system instruction or JSON mode is
    # assumed, so this also works if the Gemma endpoint doesn't offer them.
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(temperature=0.2),
    )
    return resp.text or ""


def _call_ollama(prompt: str, jpeg: bytes) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(jpeg).decode()],
            }
        ],
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


BACKENDS: dict[str, Callable[[str, bytes], str]] = {
    "gemini": _call_gemini,
    "ollama": _call_ollama,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def build_prompt(language: str = "English", plant_hint: str = "", weather_summary: str = "") -> str:
    hint = f"- The user says this plant is: {plant_hint.strip()}.\n" if plant_hint.strip() else ""
    wx = (
        f"- Local weather (use it to tailor the care steps): {weather_summary.strip()}\n"
        if weather_summary.strip()
        else ""
    )
    return PROMPT.format(language=language, plant_hint=hint, weather=wx)


def diagnose(
    image: Image.Image,
    backend: str = "gemini",
    language: str = "English",
    plant_hint: str = "",
    weather_summary: str = "",
    retries: int = 1,
) -> Report:
    """Diagnose a plant photo. Raises DiagnosisError on failure."""
    if backend not in BACKENDS:
        raise DiagnosisError(f"unknown backend '{backend}' (choose from {', '.join(BACKENDS)})")
    call = BACKENDS[backend]
    jpeg = prepare_image(image)
    prompt = build_prompt(language, plant_hint, weather_summary)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        p = prompt
        if attempt:
            p += "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
        try:
            return parse_report(call(p, jpeg))
        except ValueError as exc:  # malformed JSON: worth one more try
            last_error = exc
        except Exception as exc:  # network, auth, quota...: retrying won't help
            raise DiagnosisError(f"{backend} backend failed: {exc}") from exc
    raise DiagnosisError(f"the model did not return a usable report ({last_error})")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
_STATUS_ICON = {"healthy": "🟢", "stressed": "🟡", "diseased": "🔴", "unknown": "⚪"}
_SEV_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}


def to_markdown(report: Report, extra_tips: list[str] | None = None) -> str:
    if not report.is_plant:
        return (
            "### No plant detected\n"
            "Try a closer, well-lit photo of a leaf or the whole plant.\n"
            + (f"\n_{report.summary}_" if report.summary else "")
        )

    filled = round(report.health_score / 10)
    bar = "█" * filled + "░" * (10 - filled)
    out = [
        f"## {report.plant_name}",
        f"{_STATUS_ICON[report.status]} **{report.status.capitalize()}**  ·  "
        f"Health score **{report.health_score}/100**  `{bar}`",
        "",
        report.summary,
    ]

    if report.issues:
        out += ["", "### Possible issues"]
        for i in report.issues:
            out.append(
                f"- {_SEV_ICON[i.severity]} **{i.name}** ({i.kind}, {i.severity} severity, "
                f"{round(i.confidence * 100)}% confidence)"
                + (f"  \n  _Seen:_ {i.evidence}" if i.evidence else "")
            )
        if max(i.confidence for i in report.issues) < 0.5:
            out.append("\n> ⚠️ Confidence is low. Treat this as a hint, not a conclusion.")
    else:
        out += ["", "No visible problems detected."]

    if report.care_steps:
        out += ["", "### What to do"] + [f"{n}. {s}" for n, s in enumerate(report.care_steps, 1)]
    if extra_tips:
        out += ["", "### Weather-aware tips"] + [f"- {t}" for t in extra_tips]
    if report.see_expert_if:
        out += ["", f"**Ask an expert if:** {report.see_expert_if}"]
    if report.photo_tips:
        out += ["", f"📷 **Better photo:** {report.photo_tips}"]

    out += ["", "---", "_AI-generated guidance from a photo. It is not a lab diagnosis._"]
    return "\n".join(out)
