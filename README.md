# PlantCare AI 🌿

AI plant health diagnosis: upload a photo, get observations, likely causes, and
a care plan. Hackathon prototype — Gemini structured output behind a FastAPI
bridge, served with a vanilla JS frontend.

## Quick start

```bash
uv sync                                        # install deps into .venv
uv run uvicorn plantdoc.main:app --reload      # http://127.0.0.1:8000
```

- Frontend: `http://127.0.0.1:8000/` (served from `front/`)
- API: `POST http://127.0.0.1:8000/api/plant` (multipart: `image` required;
  optional `plantName`, `climate`, `stage`, `symptoms`, `notes`, `mock`)
- Docs: `http://127.0.0.1:8000/docs`

`.env` needs a `GEMINI_API_KEY`. The primary model is `gemma-4-26b-a4b-it`
(env: `GEMINI_MODEL`), with an automatic fallback chain to the gemini-3.x flash
models on 429/503/500 errors. For UI work without burning quota, add form field
`mock=true` (or set `PLANTDOC_MOCK=1`) to get a valid sample report with no AI
call.

## CLI

```bash
uv run python plantdoc/main.py --image path/to/leaf.jpg          # live diagnosis
uv run python plantdoc/main.py --mock                            # no API needed
uv run python plantdoc/main.py --mock --json --out out.json      # save JSON
```

## Benchmark (ground truth vs LLM)

```bash
cd benchmark
uv run python fetch_plantvillage.py   # fetch labeled PlantVillage sample
uv run python run_benchmark.py        # 10 blind diagnoses + scoring
```

See `benchmark/README.md`.
