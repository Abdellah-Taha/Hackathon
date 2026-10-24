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
import re
import sys
from pathlib import Path
from typing import List, Literal, Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
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


# ----------------------------------------------------------------------------
# 1b. CATEGORY-SPECIFIC INFO BLOCKS (the fields vary per plant type)
# ----------------------------------------------------------------------------

class VegetableInfo(BaseModel):
    """Extra profile returned when plant_category == 'vegetable'."""
    info_type: Literal["vegetable_info"] = "vegetable_info"
    edible_part: str = Field(description="Which part is eaten, e.g. 'fruit (berries)', 'roots', 'leaves'")
    planting_season: str = Field(description="Typical sowing/planting season, or 'Unknown'")
    days_to_harvest: Optional[int] = Field(default=None, description="Approximate days from planting to first harvest, or null if unknown")
    harvest_window: str = Field(description="How to tell it is ready and how to harvest it")
    companion_plants: List[str] = Field(default_factory=list, description="Beneficial companion plants (empty if unsure)")
    common_issues: List[str] = Field(default_factory=list, description="Problems this vegetable is prone to, not necessarily visible in this photo")
    watering_need: str = Field(description="Typical watering need, e.g. '2.5-5 cm of water per week'")
    sunlight_need: str = Field(description="Typical sun exposure, e.g. 'full sun (6-8 h)'")


class FruitInfo(BaseModel):
    """Extra profile returned when plant_category == 'fruit'."""
    info_type: Literal["fruit_info"] = "fruit_info"
    fruit_size_at_harvest: str = Field(description="Expected fruit size at maturity, e.g. '2-3 cm berries'")
    ripening_signs: str = Field(description="Visible signs the fruit is ready to pick (colour, smell, ease of detachment)")
    time_to_first_fruit: str = Field(description="Typical time from planting to first harvest, or 'Unknown'")
    pollination: str = Field(description="Pollination needs: self-fertile, needs a partner, pollinators, etc.")
    pruning_season: str = Field(description="When and how to prune, or 'Unknown'")
    watering_need: str = Field(description="Typical watering need")
    sunlight_need: str = Field(description="Typical sun exposure")
    common_issues: List[str] = Field(default_factory=list, description="Problems this fruit plant is prone to, not necessarily visible here")


class FlowerInfo(BaseModel):
    """Extra profile returned when plant_category == 'flower'."""
    info_type: Literal["flower_info"] = "flower_info"
    bloom_season: str = Field(description="Main blooming season(s), or 'Unknown'")
    bloom_cycle: str = Field(description="One flush per year, repeat-blooming, continuous, etc.")
    deadheading: str = Field(description="Whether/how to remove spent blooms to encourage more flowers")
    vase_life: Optional[str] = Field(default=None, description="Approximate vase life if used as cut flower, else null")
    fertilizer: str = Field(description="Fertilizer advice for flowering, or 'Unknown'")
    watering_need: str = Field(description="Typical watering need")
    sunlight_need: str = Field(description="Typical sun exposure")
    common_pests: List[str] = Field(default_factory=list, description="Pests this flower often attracts")


class HouseplantInfo(BaseModel):
    """Extra profile returned when plant_category == 'houseplant'."""
    info_type: Literal["houseplant_info"] = "houseplant_info"
    light_need: str = Field(description="Indoor light need, e.g. 'bright indirect light; avoid direct midday sun'")
    humidity: str = Field(description="Preferred humidity level and whether misting/pebble trays help")
    soil_mix: str = Field(description="Recommended potting mix, e.g. 'airy mix with perlite and bark'")
    fertilizer: str = Field(description="Feeding schedule and dilution, or 'Unknown'")
    repotting: str = Field(description="When and how to repot, or 'Unknown'")
    toxicity_to_pets: str = Field(description="Toxicity to cats/dogs if known, e.g. 'toxic if ingested (calcium oxalates)'")


class TreeShrubInfo(BaseModel):
    """Extra profile returned when plant_category == 'tree_shrub'."""
    info_type: Literal["tree_shrub_info"] = "tree_shrub_info"
    mature_height: str = Field(description="Typical mature height, or 'Unknown'")
    mature_spread: str = Field(description="Typical mature canopy/branch spread, or 'Unknown'")
    hardiness: str = Field(description="Climate hardiness, e.g. 'USDA zones 9-11, frost sensitive'")
    pruning_season: str = Field(description="When and how to prune, or 'Unknown'")
    watering_need: str = Field(description="Typical watering need, including drought tolerance")
    sunlight_need: str = Field(description="Typical sun exposure")
    common_issues: List[str] = Field(default_factory=list, description="Issues this tree/shrub is prone to")


class OtherInfo(BaseModel):
    """Fallback profile for plants that are real but fit no category above."""
    info_type: Literal["other_info"] = "other_info"
    plant_type_guess: str = Field(description="Best short description of the plant type, e.g. 'succulent', 'fern', 'herb'")
    notes: str = Field(description="Any care information worth knowing for this type of plant")


CategoryInfo = Union[
    VegetableInfo,
    FruitInfo,
    FlowerInfo,
    HouseplantInfo,
    TreeShrubInfo,
    OtherInfo,
]


class RecommendedAction(BaseModel):
    priority: int = Field(description="Priority order (1 = immediate low-risk action, 2 = secondary)")
    action: str = Field(description="Specific, practical, low-risk care step (e.g. 'Isolate infected foliage', 'Improve bottom airflow')")
    reason: str = Field(description="Why this action helps manage the issue")


class PlantReport(BaseModel):
    plant_name: str = Field(description="Best-supported identification of the plant or 'Unknown'")
    plant_category: Literal[
        "vegetable", "fruit", "flower", "houseplant", "tree_shrub", "unknown"
    ] = Field(
        description="Category of the plant in the photo; use 'unknown' when unsure"
    )
    category_info: Optional[CategoryInfo] = Field(
        default=None,
        description=(
            "Type-specific profile: VegetableInfo for vegetables, FruitInfo for fruits, "
            "FlowerInfo for flowers, HouseplantInfo for houseplants, TreeShrubInfo for "
            "trees/shrubs, OtherInfo as fallback. REQUIRED unless plant_category is 'unknown'."
        ),
    )
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

PROMPT_SYSTEM = """You are a panel of plant pathologist, horticulturist and botanist experts.
Inspect the attached plant photo and return an evidence-aware diagnosis report.

CRITICAL RULES:
1. Observe before diagnosing: List specific, visible symptoms (spots, yellowing, wilting, lesions, pests) with their locations.
2. Distinguish observations from inferences: Yellowing is an observation; nitrogen deficiency or overwatering is a possible cause.
3. Be honest about uncertainty: If the image is blurry, distant, or symptoms are ambiguous, explain this in 'limitations' and assign 'low' confidence.
4. Avoid dangerous recommendations: Do not recommend toxic pesticides or drastic irreversible cuts based on a single photo. Prioritize safe, practical, low-risk cultural care.
5. Provide 1 to 3 plausible causes ranked by likelihood.
6. Set 'plant_category' to vegetable, fruit, flower, houseplant, tree_shrub, or unknown, then fill 'category_info' with the matching block: vegetable -> VegetableInfo, fruit -> FruitInfo, flower -> FlowerInfo, houseplant -> HouseplantInfo, tree_shrub -> TreeShrubInfo, any other real plant -> OtherInfo. If plant_category is 'unknown', omit 'category_info' entirely.
7. 'category_info' carries general knowledge about that kind of plant (harvest, bloom, pollination, light, water...), NOT the photo-specific diagnosis. Base every 'observation' strictly on the image; never invent symptoms.
"""

# ============================================================================
# 3b. FASTAPI BRIDGE (frontend <-> Gemini pipeline)
# ============================================================================

# Primary model: gemma-4-26b-a4b-it (Gemma 4 26B MoE — vision + PlantReport
# structured output verified; no per-day free-tier cap like the Gemini models).
# Quirk: it 500s on text-only calls but works with an image attached (we always
# send an image). Fallbacks below cover 429 quota, 503 demand spikes, and
# gemma's occasional 500 INTERNAL.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
MODEL_CANDIDATES = [
    MODEL_NAME,
    "gemma-4-26b-a4b-it",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
]
MODEL_CANDIDATES = list(dict.fromkeys(MODEL_CANDIDATES))

app = FastAPI(
    title="PlantCare AI",
    description="AI plant health diagnosis: upload a photo, get a structured report.",
    version="0.3.0",
)

CONF_TO_PCT = {"high": 88, "medium": 55, "low": 25}
SEVERITY_TO_REVERSIBILITY = {
    "low": "Likely reversible",
    "moderate": "Depends on cause",
    "high": "Act quickly to reverse",
    "uncertain": "Assess after 48h",
}


def report_to_frontend(report: PlantReport) -> dict:
    """Map our validated PlantReport to the JSON shape front/app.js renders.

    front/app.js (validateResult + renderReport) expects:
      plant: {name, commonName, family},          status: healthy|concern|critical,
      certainty: 0-100, severity: str, reversibility: str,
      observations: [{title, detail}], causes: [{name, confidence, description, note?}],
      actions: [{title, detail}], monitor: [str], disclaimer: str
    All arrays must be NON-EMPTY (validateResult rejects empty lists).
    """
    causes = [
        {
            "name": c.name,
            "confidence": CONF_TO_PCT.get(c.confidence, 30),
            "description": c.reason,
            **({"note": "Most likely driver of the observed symptoms"} if i == 0 else {}),
        }
        for i, c in enumerate(report.possible_causes)
    ] or [{"name": "Undetermined", "confidence": 20,
           "description": "No plausible cause could be identified from this photo.",
           "note": "Try a closer, well-lit photo of the affected area"}]
    actions = [
        {"title": a.action, "detail": a.reason}
        for a in sorted(report.recommended_actions, key=lambda a: a.priority)
    ] or [{"title": "Monitor the plant", "detail": "No intervention is required right now."}]
    observations = [
        {"title": o.symptom, "detail": f"{o.location} — {o.evidence}"}
        for o in report.observations
    ] or [{"title": "No clear symptoms", "detail": "Nothing conclusive is visible in this photo."}]
    monitor = report.what_to_monitor or \
        ["Watch for any change in the symptoms over the next 48–72 hours."]

    status_label = {
        "healthy": "healthy", "monitor": "concern",
        "concern": "concern", "urgent": "critical",
    }.get(report.overall_status, "concern")

    severity_label = {
        "low": "Mild", "moderate": "Moderate",
        "high": "Severe", "uncertain": "Uncertain",
    }.get(report.severity, "Uncertain")

    # Scientific name looks like "Tomato (Solanum lycopersicum)" -> split it
    plant_name, common_name, family = report.plant_name, "", ""
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", report.plant_name)
    if m:
        plant_name = m.group(1).strip()
        parts = [p.strip() for p in m.group(2).split(",")]
        common_name, family = parts[0], (parts[1] if len(parts) > 1 else "")

    disclaimer_parts = list(report.limitations or [])
    if report.seasonal_context:
        disclaimer_parts.append(f"Seasonal note: {report.seasonal_context}")
    disclaimer = (" ".join(disclaimer_parts)).strip() or \
        "A single photo can't confirm a diagnosis. When unsure, ask a local plant expert."

    return {
        "plant": {"name": plant_name, "commonName": common_name, "family": family},
        "status": status_label,
        "certainty": CONF_TO_PCT.get(
            report.possible_causes[0].confidence if report.possible_causes else None,
            90 if report.overall_status == "healthy" else 40,
        ),
        "severity": severity_label,
        "reversibility": SEVERITY_TO_REVERSIBILITY.get(report.severity, "Unknown"),
        "observations": observations,
        "causes": causes,
        "actions": actions,
        "monitor": monitor,
        "disclaimer": disclaimer,
    }


def diagnose_plant_image(
    image_input: Union[str, Path, Image.Image],
    plant_hint: str = "",
    region: str = "",
    growth_stage: str = "",
    user_symptoms: str = "",
    notes: str = "",
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
) -> PlantReport:
    """Core pipeline: image + context -> Gemini -> validated PlantReport.

    Automatically iterates through candidate models if one encounters quota limits (429) or spikes (503).
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Set it in .env, or use mock mode."
        )

    image = preprocess_image(image_input)

    context_lines = []
    if plant_hint:
        context_lines.append(f"- Suspected Plant Name: {plant_hint}")
    if region:
        context_lines.append(f"- Grower Region/Location: {region}")
    if growth_stage:
        context_lines.append(f"- Growth Stage: {growth_stage}")
    if user_symptoms:
        context_lines.append(f"- User-reported symptoms: {user_symptoms}")
    if notes:
        context_lines.append(f"- Extra notes from the grower: {notes}")

    context_str = ""
    if context_lines:
        context_str = "\nADDITIONAL USER CONTEXT:\n" + "\n".join(context_lines)

    user_prompt = f"""{PROMPT_SYSTEM}
{context_str}

Analyze this plant photo and return a structured report adhering strictly to the schema."""

    # Lazy import so the module (and mock mode/CLI) work without google-genai
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError(
            "The 'google-genai' library is required. Install it using:\n"
            "python -m pip install google-genai"
        )

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=PlantReport,
        temperature=0.2,  # Low temperature for objective diagnosis
    )

    models_to_try = [model_name] if model_name else list(MODEL_CANDIDATES)
    last_error = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=[image, user_prompt],
                config=config,
            )
            if not response.text:
                raise RuntimeError(f"Model {m} returned an empty response.")
            return PlantReport.model_validate_json(response.text)
        except Exception as exc:
            last_error = exc
            err_str = str(exc)
            # If rate limit (429), high demand (503), or gemma's sporadic
            # internal error (500), try the next candidate model
            if ("429" in err_str or "503" in err_str or "500" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str or "UNAVAILABLE" in err_str
                    or "INTERNAL" in err_str):
                print(f"Warning: Model {m} hit rate limit / busy ({err_str[:60]}), trying next candidate model...")
                continue
            raise

    if last_error:
        raise last_error


@app.post("/api/plant")
async def api_diagnose_plant(
    image: UploadFile = File(...),
    plant_hint: str = Form("", alias="plantName"),
    region: str = Form("", alias="climate"),
    growth_stage: str = Form("", alias="stage"),
    user_symptoms: str = Form("", alias="symptoms"),
    notes: str = Form(""),
    mock: bool = Form(False),
) -> dict:
    """Bridge endpoint: multipart form from front/app.js -> Gemini -> frontend JSON.

    Send mock=true (form field) to get a valid sample report without any AI call —
    lets the frontend team build/test while the quota is out or the model is down.
    """
    # Mock fast-path: no API key or quota needed
    if mock or os.getenv("PLANTDOC_MOCK", "").lower() in ("1", "true", "yes"):
        return report_to_frontend(create_mock_report(plant_hint=plant_hint))

    try:
        image_input = Image.open(image.file).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file.")

    # Core pipeline (same one the CLI and benchmark use)
    try:
        report = diagnose_plant_image(
            image_input=image_input,
            plant_hint=plant_hint,
            region=region,
            growth_stage=growth_stage,
            user_symptoms=user_symptoms,
            notes=notes,
        )
    except ValueError as exc:  # missing API key
        raise HTTPException(status_code=500, detail=str(exc))
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ValidationError as exc:  # model output violated our schema
        raise HTTPException(status_code=502,
                            detail=f"AI response failed schema validation: {str(exc)[:200]}")
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            # Fall back to preview report if all candidate models have exhausted their free quota
            print("Notice: All Gemini models exhausted free-tier daily quota (429). Falling back to demo preview.")
            mock_rep = create_mock_report(plant_hint=plant_hint)
            res = report_to_frontend(mock_rep)
            res["disclaimer"] = "⚠️ Notice: Daily free-tier AI quota reached (429). Showing diagnostic preview mode. " + res["disclaimer"]
            return res
        if "503" in msg or "unavailable" in msg.lower():
            raise HTTPException(status_code=503,
                                detail="AI service temporarily experiencing high demand — please retry.")
        raise HTTPException(status_code=502, detail=f"AI request failed: {msg[:200]}")

    return report_to_frontend(report)



# Static frontend LAST so the catch-all mount cannot shadow /api/plant
FRONT_DIR = Path(__file__).resolve().parent.parent / "front"
app.mount("/", StaticFiles(directory=str(FRONT_DIR), html=True), name="front")


# ============================================================================
# 4. MOCK GENERATOR (For instant frontend/backend integration testing)
# ============================================================================

def create_mock_report(plant_hint: str = "Tomato") -> PlantReport:
    """Return a realistic mock PlantReport conforming to the schema."""
    return PlantReport(
        plant_name=plant_hint or "Tomato (Solanum lycopersicum)",
        plant_category="vegetable",
        category_info=VegetableInfo(
            edible_part="fruit (botanically a berry, eaten as a vegetable)",
            planting_season="sow indoors 6-8 weeks before last frost; transplant after soil reaches 15°C",
            days_to_harvest=80,
            harvest_window="pick when fully colored and slightly soft; twist off with the calyx for storage life",
            companion_plants=["Basil", "French marigold", "Chives", "Parsley"],
            common_issues=["Early blight", "Septoria leaf spot", "Blossom end rot", "Tomato hornworm"],
            watering_need="2.5-5 cm of water per week, consistently moist but never waterlogged",
            sunlight_need="full sun, 6-8 hours daily",
        ),
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


def _category_info_rows(info) -> List[tuple]:
    """Convert a category_info model to (label, value) rows for printing."""
    labels = {
        "info_type": None,  # hidden
        "edible_part": "Edible part",
        "planting_season": "Planting",
        "days_to_harvest": "Days to harvest",
        "harvest_window": "Harvest",
        "companion_plants": "Companions",
        "common_issues": "Common issues",
        "watering_need": "Water",
        "sunlight_need": "Sun",
        "fruit_size_at_harvest": "Fruit size",
        "ripening_signs": "Ripening signs",
        "time_to_first_fruit": "First fruit",
        "pollination": "Pollination",
        "pruning_season": "Pruning",
        "bloom_season": "Bloom season",
        "bloom_cycle": "Bloom cycle",
        "deadheading": "Deadheading",
        "vase_life": "Vase life",
        "fertilizer": "Fertilizer",
        "common_pests": "Common pests",
        "light_need": "Light",
        "humidity": "Humidity",
        "soil_mix": "Soil mix",
        "repotting": "Repotting",
        "toxicity_to_pets": "Pet safety",
        "mature_height": "Mature height",
        "mature_spread": "Mature spread",
        "hardiness": "Hardiness",
        "plant_type_guess": "Plant type",
        "notes": "Notes",
    }
    rows = []
    for field, value in info:
        label = labels.get(field, field.replace("_", " ").title())
        if label is None or value in (None, [], ""):
            continue
        rows.append((label, ", ".join(value) if isinstance(value, list) else str(value)))
    return rows


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
    print(f"Category       : {report.plant_category.replace('_', ' ').title()}")

    # Type-specific info block (varies by plant_category)
    info = report.category_info
    if info is not None:
        print(f"\n🌱 {report.plant_category.replace('_', ' ').upper()} PROFILE:")
        for label, value in _category_info_rows(info):
            print(f"  {label:<16}: {value}")

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
    parser.add_argument("--out", type=str, default="", help="Optional path to save the JSON report (e.g. data.json)")
    args = parser.parse_args()

    # Image selection or creation
    image_path = args.image
    if not image_path:
        sample_path = Path(__file__).resolve().parent / "images.jpg"
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
            print(f"Sending image to Gemini Vision AI (model: {MODEL_NAME})...")
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

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"JSON report saved to: {out_path}")

    if args.json:
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
