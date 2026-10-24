# PlantVillage Benchmark Sample

Ground-truth data for measuring how well the LLM (Gemini) diagnosis reports
compare against known labels — the "at least five varied test photos" roadmap
requirement, at benchmark scale.

## What is here

| Path | Contents |
|---|---|
| `plantvillage_ground_truth.json` | 76 labeled items: id, row_index, class_label, host, disease, is_healthy, plant_category_expected, image info |
| `images/` | 76 JPEGs (256×256), named `<class_idx>_<row_index>.jpg` |
| `fetch_plantvillage.py` | Reproducible fetch script (HF datasets-server API, resumable, 429-aware) |

## Source

[geraldmc/plantvillage-full](https://huggingface.co/datasets/geraldmc/plantvillage-full)
— 54,304 rows, 38 classes, 14 crop hosts, 21 disease labels. Labels come from
the dataset, **not** from any model. Sampling is stratified: 2 images per class,
taken at 1/4 and 3/4 depth of each class block, so coverage is even rather than
Tomato-dominated like the raw dataset.

Covered: 24 healthy / 52 diseased · 34 fruit / 42 vegetable crops.

## Running the benchmark later

```bash
cd benchmark
python run_benchmark.py               # 10 blind diagnoses + scored summary
python run_benchmark.py --limit 3     # quick smoke run
python run_benchmark.py --mock        # schema/pipeline test, no API key needed
```

- Selection: 4 healthy / 6 diseased, distinct classes & hosts, seed=42 (deterministic).
- Diagnosis is **blind** — no host, symptom, or region hints; `plant_hint=""`.
- Every raw report is saved to `results/report_<id>.json`; reruns reuse them
  (resume-safe), so a crashed/partial run costs nothing on retry.
- Output: `results/summary_<timestamp>.json` with per-item scores +
  aggregates (verdict accuracy, host ID, top-3 cause hit, category, calibration).

**Quota warning (free tier):** gemini-3.8-flash allows only **20 requests/day**.
A full 10-image run needs ~10-15 requests with retries. If you see
`429 ... per day limit exceeded`, wait for the reset (~midnight Pacific) and
rerun — completed items are cached. Use `--limit` to spread runs across days.

