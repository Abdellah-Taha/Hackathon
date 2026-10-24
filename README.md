This project is made by: (PlantCare Team) Abdellah-Taha Zirari, Bilal errabia, naser eddine ibouttane, aymane errabou
PlantCare AI
PlantCare AI is a hackathon prototype that turns a plant photo into an evidence-aware health report. It identifies visible symptoms, lists up to three plausible causes with uncertainty, and suggests low-risk care actions.

The project has three usable parts:

A FastAPI backend in plantdoc/main.py.
A browser interface in front/, served by the backend.
A command-line interface and a PlantVillage benchmark.
This is decision support, not a certified plant pathology diagnosis. A single photo cannot reveal root health, soil conditions, pests hidden from view, or confirm a disease in a laboratory.

What happens during a diagnosis
The user supplies a JPG, PNG, or HEIC image.
The backend corrects EXIF rotation, converts the image to RGB, and resizes its longest side to 1024 pixels.
The image and optional context are sent to a vision-capable model through the Zenmux OpenAI-compatible API.
The model must return JSON matching the Pydantic PlantReport schema.
Pydantic validates the report before the API returns it.
The browser converts the validated report into the cards shown in the UI.
Requirements
Linux, macOS, or Windows
Python 3.13 or newer
uv
An API key for live diagnosis, unless using mock mode
Install and run the web app
From the repository root:

uv sync
uv run uvicorn plantdoc.main:app --reload
Open http://127.0.0.1:8000/. Upload a clear photo of a leaf, stem, whole plant, or affected area, then select Diagnose my plant.

Other useful URLs:

Swagger API documentation: http://127.0.0.1:8000/docs
Alternative API schema: http://127.0.0.1:8000/redoc
The frontend is static vanilla JavaScript. It is normally served by FastAPI; you do not need a separate frontend build or Node.js install.

Configure live AI access
Create a .env file in the repository root:

ZENMUX_API_KEY=your_provider_key
ZENMUX_MODEL=z-ai/glm-5.3-flash
ZENMUX_BASE_URL=https://zenmux.ai/api/v1
Despite the historical variable name GEMINI_API_KEY, the implementation uses the OpenAI Python SDK with ZENMUX_BASE_URL. The key must be valid for the configured provider and model.

The backend tries GEMINI_MODEL first, then fallback model names when the provider reports a transient 429, 500, or 503-style failure. Model availability, pricing, quotas, and exact names are controlled by the provider.

Mock mode
Mock mode returns a deterministic tomato report without making an AI request. Use it to test the interface, API wiring, or report rendering without a key or quota:

PLANTDOC_MOCK=1 uv run uvicorn plantdoc.main:app --reload
You can also send mock=true as a form field to the API. The CLI has an explicit --mock option. In mock mode, the uploaded image is not analyzed.

Command-line usage
Run a live diagnosis:

uv run python plantdoc/main.py --image path/to/leaf.jpg
Run offline with the built-in sample report:

uv run python plantdoc/main.py --mock
The CLI creates a synthetic leaf image when --image is omitted. Add context with --plant and --region:

uv run python plantdoc/main.py \
  --image path/to/leaf.jpg \
  --plant Tomato \
  --region Mediterranean
Output JSON to the terminal or save it to a file:

uv run python plantdoc/main.py --mock --json
uv run python plantdoc/main.py --mock --json --out report.json
If the live CLI call fails, the current implementation prints the error and falls back to the mock report. Check the terminal output before treating a saved report as a live model result.

API usage
The implemented endpoint is POST /api/plant. It accepts multipart/form-data:

Field	Required	Description
image	Yes	Plant image file
plantName	No	Known or suspected plant name
climate	No	Region or climate context
stage	No	Growth stage
symptoms	No	Symptoms noticed by the user
notes	No	Additional context
mock	No	true to return a sample report without calling the model
Example live request:

curl -X POST http://127.0.0.1:8000/api/plant \
  -F image=@path/to/leaf.jpg \
  -F plantName=Tomato \
  -F climate=Mediterranean \
  -F stage=fruiting \
  -F symptoms="brown spots on lower leaves"
Example mock request:

curl -X POST http://127.0.0.1:8000/api/plant \
  -F image=@path/to/leaf.jpg \
  -F mock=true
The endpoint returns the frontend shape:

{
  "plant": {"name": "Tomato", "commonName": "", "family": ""},
  "status": "healthy | concern | critical",
  "certainty": 0,
  "severity": "Mild | Moderate | Severe | Uncertain",
  "reversibility": "...",
  "observations": [{"title": "...", "detail": "..."}],
  "causes": [{"name": "...", "confidence": 0, "description": "..."}],
  "actions": [{"title": "...", "detail": "..."}],
  "monitor": ["..."],
  "disclaimer": "..."
}
The CLI and the core Python function use the full PlantReport shape instead. Its fields and category-specific profile objects are documented in [plantdoc/SCHEMA.md](plantdoc/SCHEMA.md). The frontend can also load a saved full-schema JSON report from its Load result.json control.

Benchmark
The benchmark evaluates blind diagnoses against a small, locally stored sample from the PlantVillage dataset. It measures healthy/diseased verdict accuracy, host identification, top-three cause hits, category accuracy, latency, and confidence calibration.

The repository already contains the sample images and labels. To refresh them from Hugging Face:

uv run python benchmark/fetch_plantvillage.py
Run a no-cost pipeline check:

uv run python benchmark/run_benchmark.py --mock --limit 3
Run live scoring:

uv run python benchmark/run_benchmark.py
Useful options:

uv run python benchmark/run_benchmark.py --limit 3
uv run python benchmark/run_benchmark.py --model gemini-2.5-flash
Raw reports and timestamped summaries are written under benchmark/results/. Live reports are cached per image, so rerunning does not repeat completed items. The default run uses 10 images: 4 healthy and 6 diseased. Live runs can consume provider quota and may pause for retries; use --mock for a fast schema test. See [benchmark/README.md](benchmark/README.md) for the dataset and scoring details.

Project layout
plantdoc/main.py                 Backend, schema, model call, mock mode, CLI
front/index.html                 Browser page
front/app.js                     Upload flow and report rendering
front/styles.css                 Small custom frontend styles
plantdoc/SCHEMA.md               Full PlantReport contract
benchmark/                       Dataset sample, downloader, scorer, results
data.json                        Example full-schema report
plant_diag_plan.txt              Original product and implementation plan
plant_diagnosis_project_roadmap.txt  Original roadmap and demo plan
pyproject.toml                   Python dependencies and uv project config
Current limitations
The browser currently exposes the image upload flow; optional context fields are supported by the API and CLI but are not all present as browser inputs.
The report is generated from one image and should be treated as uncertain when the photo is blurry, distant, or missing the affected area.
There is no database, login, diagnosis history, weather integration, PDF export, or working follow-up chat yet.
Uploaded images are sent to the configured external model provider for live analysis. Review that provider's privacy and retention terms before using sensitive images.
Benchmark scores measure this sample and matching heuristics; they are not a clinical or agricultural validation study.
Development notes
The main Python entry point is importable as plantdoc.main:app. After changing backend code, a quick smoke test is:

uv run python plantdoc/main.py --mock --json --out /tmp/plantcare-report.json
uv run python benchmark/run_benchmark.py --mock --limit 1
Do not confuse a mock report, a CLI fallback report, and a live model report when evaluating the system.3