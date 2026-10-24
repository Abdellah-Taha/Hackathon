# PlantDoc JSON Report Contract

One shared schema for backend, CLI and frontend. Every diagnosis — live AI or
mock — validates against `PlantReport` in `plantdoc/main.py` (Pydantic).

## Top-level report

| Field | Type | Notes |
|---|---|---|
| `plant_name` | string | Best-supported identification, or `"Unknown"` |
| `plant_category` | enum | `vegetable` \| `fruit` \| `flower` \| `houseplant` \| `tree_shrub` \| `unknown` |
| `category_info` | object \| null | **Varies by category** (see below). Always `null` when `plant_category` is `unknown` |
| `overall_status` | enum | `healthy` \| `monitor` \| `concern` \| `urgent` |
| `severity` | enum | `low` \| `moderate` \| `high` \| `uncertain` |
| `observations[]` | array | `{symptom, location, evidence}` — strictly what is visible in the photo |
| `possible_causes[]` | array | 1–3 items `{name, confidence: low\|medium\|high, reason}` |
| `recommended_actions[]` | array | `{priority: 1..n, action, reason}` — low-risk steps first |
| `seasonal_context` | string \| null | General context, never fabricated weather |
| `what_to_monitor[]` | array of strings | Warning signs to watch |
| `limitations[]` | array of strings | What cannot be known from one photo |
| `follow_up_questions[]` | array of strings | Questions that would improve the assessment |

## `category_info` — different fields per plant type

Discriminated by the `info_type` tag, so the frontend can switch layouts safely.

### `vegetable_info`
`edible_part`, `planting_season`, `days_to_harvest` (int \| null), `harvest_window`,
`companion_plants[]`, `common_issues[]`, `watering_need`, `sunlight_need`

### `fruit_info`
`fruit_size_at_harvest`, `ripening_signs`, `time_to_first_fruit`, `pollination`,
`pruning_season`, `watering_need`, `sunlight_need`, `common_issues[]`

### `flower_info`
`bloom_season`, `bloom_cycle`, `deadheading`, `vase_life` (string \| null),
`fertilizer`, `watering_need`, `sunlight_need`, `common_pests[]`

### `houseplant_info`
`light_need`, `humidity`, `soil_mix`, `fertilizer`, `repotting`, `toxicity_to_pets`

### `tree_shrub_info`
`mature_height`, `mature_spread`, `hardiness`, `pruning_season`,
`watering_need`, `sunlight_need`, `common_issues[]`

### `other_info` (fallback for real plants that fit nowhere else)
`plant_type_guess`, `notes`

## Frontend rendering rules

- `category_info === null` → hide the profile card entirely (unknown plant).
- Read `category_info.info_type` to pick which fields to display.
- Treat every list field as possibly empty; never assume a fixed length.
- `plant_category` drives the card title/icon; unknown → generic leaf icon.

## Files

- `data.json` — real AI report for `plantdoc/images.jpg` (Monstera deliciosa).
- `examples/*.json` — one fixture per category; all validate against the schema.

## CLI

```bash
python main.py --image images.jpg              # formatted report
python main.py --image images.jpg --json       # raw JSON to stdout
python main.py --image images.jpg --out data.json   # save JSON to file
python main.py --mock                          # offline fixture (no API key)
```

The live call can fail transiently (503 "high demand"); running it again usually
works. On failure the CLI falls back to the mock report, so `--out` after a
failed call contains mock data — check the "Error calling live AI" line.
