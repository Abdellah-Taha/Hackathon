"""PlantDoc - AI Plant Health Diagnosis Prototype

This module implements the core AI pipeline defined in plant_diag_plan.txt:
1. Image validation & preprocessing (PIL resize, format normalization)
2. Vision analysis via Google Gemini API (structured outputs with Pydantic)
3. Schema-validated PlantReport (observations, possible causes, recommendations)
4. Built-in mock mode and test runner for quick hackathon development
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Literal, Optional, Union

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, Field, ValidationError

# Ensure Windows PowerShell/cmd console handles Unicode/emojis cleanly
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# Load environment variables from .env if present
load_dotenv()
# Also check parent directory for .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ============================================================================
# 1. REPORT SCHEMA (Matches plant_diag_plan.txt Section 3)
# ============================================================================

class Observation(BaseModel):
    symptom: str = Field(description="Observable visible symptom (e.g. 'yellowing near leaf edges', 'brown necrotic spots')")
    location: str = Field(description="Where the symptom is visible on the plant (e.g. 'lower leaves', 'leaf veins', 'stem')")
    evidence: str = Field(description="Visual evidence visible in the image supporting this observation")


class PossibleCause(BaseModel):
    name: str = Field(description="Plausible disease, pest, or physiological stress (e.g. 'Early blight', 'Nitrogen deficiency')")
    confidence: Literal["low", "medium", "high"] = Field(description="Confidence level based on visual clarity and certainty")
    reason: str = Field(description="Explanation connecting the visible observations to this plausible cause")


class RecommendedAction(BaseModel):
    priority: int = Field(description="Priority order (1 = immediate low-risk action, 2 = secondary)")
    action: str = Field(description="Specific, practical, low-risk care step (e.g. 'Isolate infected foliage', 'Improve bottom airflow')")
    reason: str = Field(description="Why this action helps manage the issue")


class PlantReport(BaseModel):
    plant_name: str = Field(description="Best-supported identification of the plant or 'Unknown'")
    overall_status: Literal["healthy", "monitor", "concern", "urgent"] = Field(
        description="Overall health rating of the plant"
    )
    severity: Literal["low", "moderate", "high", "uncertain"] = Field(
        description="Severity of the detected issues"
    )
    observations: List[Observation] = Field(
        default_factory=list,
        description="List of raw visual observations grounded strictly in the image"
    )
    possible_causes: List[PossibleCause] = Field(
        default_factory=list,
        description="1 to 3 plausible explanations for the observed symptoms"
    )
    recommended_actions: List[RecommendedAction] = Field(
        default_factory=list,
        description="Prioritized, low-risk care recommendations"
    )
    seasonal_context: Optional[str] = Field(
        default=None,
        description="General seasonal advice relevant to the plant and region"
    )
    what_to_monitor: List[str] = Field(
        default_factory=list,
        description="Specific warning signs or changes the grower should watch for"
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Uncertainties or things that cannot be diagnosed from a single photo"
    )
    follow_up_questions: List[str] = Field(
        default_factory=list,
        description="Helpful questions or next steps to narrow down ambiguous symptoms"
    )


# ============================================================================
# 2. IMAGE PREPROCESSING & VALIDATION
# ============================================================================

def preprocess_image(image_input: Union[str, Path, Image.Image], max_side: int = 1024) -> Image.Image:
    """Load, validate, and resize image for optimal API transmission."""
    if isinstance(image_input, (str, Path)):
        path = Path(image_input)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found at: {path}")
        img = Image.open(path)
    elif isinstance(image_input, Image.Image):
        img = image_input
    else:
        raise TypeError(f"Expected file path or PIL Image, got {type(image_input)}")

    # Correct EXIF rotation if present
    img = ImageOps.exif_transpose(img)

    # Convert to RGB (handles RGBA, Palette, grayscale)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Downscale if larger than max_side to conserve bandwidth and reduce latency
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    return img


# ============================================================================
# 3. AI PROMPT & INVOCATION
# ============================================================================

PROMPT_SYSTEM = """You are an experienced plant pathologist and horticultural diagnostician.
Your goal is to inspect the attached plant photo and return an evidence-aware diagnosis report.

CRITICAL RULES:
1. Observe before diagnosing: List specific, visible symptoms (spots, yellowing, wilting, lesions, pests) with their locations.
2. Distinguish observations from inferences: Yellowing is an observation; nitrogen deficiency or overwatering is a possible cause.
3. Be honest about uncertainty: If the image is blurry, distant, or symptoms are ambiguous, explain this in 'limitations' and assign 'low' confidence.
4. Avoid dangerous recommendations: Do not recommend toxic pesticides or drastic irreversible cuts based on a single photo. Prioritize safe, practical, low-risk cultural care.
5. Provide 1 to 3 plausible causes ranked by likelihood.
"""


def diagnose_plant_image(
    image_input: Union[str, Path, Image.Image],
    plant_hint: str = "",
    region: str = "",
    growth_stage: str = "",
    user_symptoms: str = "",
    api_key: Optional[str] = None,
    model_name: str = "gemini-2.5-flash",
) -> PlantReport:
    """Send plant image and context to Google Gemini with structured Pydantic output."""
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set it in your environment or .env file, "
            "or run with --mock to test the schema and pipeline without an API key."
        )

    # Lazy import so prototype can still load mock mode even without google-genai
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError(
            "The 'google-genai' library is required. Install it using:\n"
            "python -m pip install google-genai"
        )

    # Preprocess image
    image = preprocess_image(image_input)

    # Assemble contextual instructions
    context_lines = []
    if plant_hint:
        context_lines.append(f"- Suspected Plant Name: {plant_hint}")
    if region:
        context_lines.append(f"- Grower Region/Location: {region}")
    if growth_stage:
        context_lines.append(f"- Growth Stage: {growth_stage}")
    if user_symptoms:
        context_lines.append(f"- User-reported symptoms: {user_symptoms}")

    context_str = ""
    if context_lines:
        context_str = "\nADDITIONAL USER CONTEXT:\n" + "\n".join(context_lines)

    user_prompt = f"""{PROMPT_SYSTEM}
{context_str}

Analyze this plant photo and return a structured report adhering strictly to the schema."""

    # Initialize client
    client = genai.Client(api_key=api_key)

    # Configure structured output matching our Pydantic schema
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=PlantReport,
        temperature=0.2,  # Low temperature for objective diagnosis
    )

    # Call Gemini Multimodal
    response = client.models.generate_content(
        model=model_name,
        contents=[image, user_prompt],
        config=config,
    )

    if not response.text:
        raise RuntimeError("Model returned an empty response.")

    # Validate and return Pydantic model
    return PlantReport.model_validate_json(response.text)


# ============================================================================
# 4. MOCK GENERATOR (For instant frontend/backend integration testing)
# ============================================================================

def create_mock_report(plant_hint: str = "Tomato") -> PlantReport:
    """Return a realistic mock PlantReport conforming to the schema."""
    return PlantReport(
        plant_name=plant_hint or "Tomato (Solanum lycopersicum)",
        overall_status="concern",
        severity="moderate",
        observations=[
            Observation(
                symptom="Concentric brown target-like spots with yellow halo",
                location="Lower older foliage",
                evidence="Multiple 3-5mm necrotic lesions visible on the leaf surface"
            ),
            Observation(
                symptom="Mild chlorosis (yellowing)",
                location="Leaf margins around necrotic lesions",
                evidence="Discoloration spreading outward from the lesions towards the edge"
            )
        ],
        possible_causes=[
            PossibleCause(
                name="Early Blight (Alternaria solani)",
                confidence="medium",
                reason="Concentric ring lesions on lower leaves are characteristic of early blight fungal infection"
            ),
            PossibleCause(
                name="Septoria Leaf Spot",
                confidence="low",
                reason="Smaller circular spots are also common in warm humid conditions"
            )
        ],
        recommended_actions=[
            RecommendedAction(
                priority=1,
                action="Prune and safely discard heavily spotted lower leaves (do not compost)",
                reason="Stops fungal spores from splashing up to healthy upper foliage"
            ),
            RecommendedAction(
                priority=2,
                action="Water strictly at the soil base in the morning, avoiding wet leaves",
                reason="Reduces prolonged leaf moisture required for fungal germination"
            ),
            RecommendedAction(
                priority=3,
                action="Ensure adequate spacing between plants to enhance air circulation",
                reason="Helps foliage dry quickly after morning dew"
            )
        ],
        seasonal_context="Warm, humid mid-summer conditions frequently trigger fungal leaf spots in nightshades.",
        what_to_monitor=[
            "Watch whether new spots appear on higher leaves or fruit stems",
            "Check neighboring plants for similar leaf spotting"
        ],
        limitations=[
            "Single leaf photo cannot inspect root health, soil moisture, or whole-stem lesions.",
            "Microscopic spore analysis is necessary for definitive fungal species confirmation."
        ],
        follow_up_questions=[
            "Are spots also visible on the tomato stems or green fruit?",
            "Has the plant been exposed to heavy overhead watering or frequent rain recently?"
        ]
    )


# ============================================================================
# 5. CLI & PROTOTYPE DEMO RUNNER
# ============================================================================

def create_sample_leaf_image(output_path: Path) -> Path:
    """Generate a synthetic leaf test image if the user doesn't have an image file yet."""
    img = Image.new("RGB", (400, 400), color=(240, 245, 240))
    draw = ImageDraw.Draw(img)

    # Draw stem
    draw.line([(200, 380), (200, 150)], fill=(70, 110, 50), width=6)
    # Draw leaf blade (oval)
    draw.ellipse([(120, 100), (280, 320)], fill=(85, 160, 65), outline=(50, 120, 40), width=3)
    # Draw leaf veins
    draw.line([(200, 150), (160, 190)], fill=(50, 120, 40), width=2)
    draw.line([(200, 180), (240, 220)], fill=(50, 120, 40), width=2)
    draw.line([(200, 220), (150, 260)], fill=(50, 120, 40), width=2)
    # Draw some "symptom" spots (yellow/brown lesions)
    draw.ellipse([(155, 175), (175, 195)], fill=(180, 130, 40), outline=(120, 80, 20), width=1)
    draw.ellipse([(220, 230), (245, 255)], fill=(190, 140, 50), outline=(130, 85, 30), width=1)

    img.save(output_path)
    return output_path


def print_report(report: PlantReport):
    """Pretty-print the structured report to the terminal."""
    status_emoji = {
        "healthy": "🟢 Healthy",
        "monitor": "🟡 Monitor",
        "concern": "🟠 Concern",
        "urgent": "🔴 Urgent",
    }.get(report.overall_status, report.overall_status)

    print("\n" + "=" * 65)
    print(f"🌿 PLANT HEALTH REPORT: {report.plant_name}")
    print("=" * 65)
    print(f"Overall Status : {status_emoji}")
    print(f"Severity       : {report.severity.upper()}")
    if report.seasonal_context:
        print(f"Season Context : {report.seasonal_context}")

    print("\n🔍 VISUAL OBSERVATIONS:")
    for i, obs in enumerate(report.observations, 1):
        print(f"  {i}. [{obs.location}] {obs.symptom}")
        print(f"     Evidence: {obs.evidence}")

    print("\n🩺 PLAUSIBLE CAUSES:")
    for i, cause in enumerate(report.possible_causes, 1):
        print(f"  {i}. {cause.name} (Confidence: {cause.confidence.upper()})")
        print(f"     Reason: {cause.reason}")

    print("\n🛠️ RECOMMENDED ACTIONS:")
    for act in sorted(report.recommended_actions, key=lambda a: a.priority):
        print(f"  Priority {act.priority}: {act.action}")
        print(f"     Why: {act.reason}")

    if report.what_to_monitor:
        print("\n👀 WHAT TO MONITOR:")
        for item in report.what_to_monitor:
            print(f"  - {item}")

    if report.limitations:
        print("\n⚠️ LIMITATIONS & UNCERTAINTIES:")
        for lim in report.limitations:
            print(f"  - {lim}")

    if report.follow_up_questions:
        print("\n❓ SUGGESTED FOLLOW-UP QUESTIONS:")
        for q in report.follow_up_questions:
            print(f"  - {q}")

    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="PlantDoc - AI Plant Diagnosis Prototype")
    parser.add_argument("--image", type=str, help="Path to plant image file")
    parser.add_argument("--plant", type=str, default="", help="Optional plant species hint (e.g. Tomato)")
    parser.add_argument("--region", type=str, default="", help="Optional grower region (e.g. Mediterranean)")
    parser.add_argument("--mock", action="store_true", help="Run with mock AI response (no API key required)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    args = parser.parse_args()

    # Image selection or creation
    image_path = args.image
    if not image_path:
        sample_path = Path(__file__).resolve().parent / "sample_leaf.jpg"
        if not sample_path.exists():
            create_sample_leaf_image(sample_path)
            print(f"Generated sample synthetic leaf image: {sample_path}")
        image_path = sample_path
        print(f"No --image provided. Using sample image: {image_path}")

    # Diagnosis execution
    if args.mock:
        print("Running in MOCK mode...")
        report = create_mock_report(plant_hint=args.plant or "Tomato")
    else:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("\nNotice: GEMINI_API_KEY not found in environment or .env.")
            print("Switching automatically to --mock mode to demonstrate output structure.")
            print("Set GEMINI_API_KEY in .env to use live Gemini AI models.\n")
            report = create_mock_report(plant_hint=args.plant or "Tomato")
        else:
            print(f"Sending image to Gemini Vision AI (model: gemini-2.5-flash)...")
            try:
                report = diagnose_plant_image(
                    image_input=image_path,
                    plant_hint=args.plant,
                    region=args.region,
                )
            except Exception as e:
                print(f"Error calling live AI: {e}")
                print("Falling back to mock response for testing:")
                report = create_mock_report(plant_hint=args.plant or "Tomato")

    if args.json:
        print(json.dumps(report.model_dump(), indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
