"""Fetch a stratified ground-truth sample from the PlantVillage dataset on Hugging Face.

Dataset: https://huggingface.co/datasets/geraldmc/plantvillage-full  (54,304 rows, 38 classes)

Uses the Hugging Face datasets-server API (the same backend the web viewer uses),
so nothing needs to be downloaded from git or the datasets library.

For every one of the 38 classes we keep 2 images (a quarter-depth row and a
three-quarter-depth row of that class block) for visual variety, download them
into images/, and write plantvillage_ground_truth.json with the labels that the
LLM reports will later be compared against.

Usage:  python fetch_plantvillage.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DATASET = "geraldmc/plantvillage-full"
CONFIG, SPLIT = "default", "train"
API = "https://datasets-server.huggingface.co"
OUT_DIR = Path(__file__).resolve().parent
IMG_DIR = OUT_DIR / "images"
PER_CLASS = 2

# Expected plant_category in our report schema, mapped from the dataset host.
CATEGORY_BY_HOST = {
    "Apple": "fruit", "Blueberry": "fruit", "Cherry (including sour)": "fruit",
    "Grape": "fruit", "Orange": "fruit", "Peach": "fruit", "Raspberry": "fruit",
    "Strawberry": "fruit",
    "Corn (maize)": "vegetable", "Pepper, bell": "vegetable", "Potato": "vegetable",
    "Soybean": "vegetable", "Squash": "vegetable", "Tomato": "vegetable",
}


def api_get(session: requests.Session, url: str, params: dict, timeout: int = 30) -> dict:
    """GET with 429-aware exponential backoff (datasets-server rate limits)."""
    for attempt in range(8):
        r = session.get(url, params=params, timeout=timeout)
        if r.status_code == 429:
            wait = min(90, 15 * (2 ** attempt))
            print(f"    429 rate limited; waiting {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"rate limit not cleared after retries: {url}")


def main() -> None:
    IMG_DIR.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "plantdoc-benchmark/0.1"

    # 1. Class distribution + ordered offsets ---------------------------------
    stats = api_get(session, f"{API}/statistics",
                    {"dataset": DATASET, "config": CONFIG, "split": SPLIT})["statistics"]
    freq = next(c for c in stats if c["column_name"] == "class_label")[
        "column_statistics"
    ]["frequencies"]
    classes = sorted(freq)  # class_idx order == alphabetical class_label order
    assert len(classes) == 38, f"expected 38 classes, got {len(classes)}"

    offsets, cursor = {}, 0
    for cls in classes:
        offsets[cls] = cursor
        cursor += freq[cls]
    total = cursor

    # 2. Sample rows + download images ----------------------------------------
    items, done = [], 0
    for idx, cls in enumerate(classes):
        start, count = offsets[cls], freq[cls]
        picks = sorted({start + count // 4, start + 3 * count // 4})[:PER_CLASS]
        for pick in picks:
            fname = f"{idx:02d}_{pick}.jpg"
            cached = IMG_DIR / fname
            if cached.exists() and cached.stat().st_size > 1000:
                print(f"[skip] {cls:<45} row {pick} (cached)")
                items.append({"_pending": True, "id": f"pv_{len(items):04d}",
                              "row_index": pick, "class_idx": idx,
                              "class_label": cls, "_fname": fname})
                continue
            row = api_get(session, f"{API}/rows",
                          {"dataset": DATASET, "config": CONFIG, "split": SPLIT,
                           "offset": pick, "length": 1})["rows"][0]["row"]
            assert row["class_idx"] == idx and row["class_label"] == cls, (
                f"row order mismatch at offset {pick}: {row['class_label']}"
            )
            time.sleep(0.4)

            # sanity-check labels derived from class_label against the dataset row
            host_raw, _, disease_raw = cls.partition("___")
            assert host_raw.replace("_", " ") == row["host"], f"host mismatch at {pick}"
            assert disease_raw.replace("_", " ").strip() == row["disease"], (
                f"disease mismatch at {pick}"
            )

            img_resp = session.get(row["image"]["src"], timeout=60)
            img_resp.raise_for_status()
            (IMG_DIR / fname).write_bytes(img_resp.content)
            time.sleep(0.4)
            done += 1
            print(f"[{done:>2}/{len(classes) * PER_CLASS}] {cls:<45} row {pick}")
            items.append({"_pending": True, "row_index": pick, "class_idx": idx,
                          "class_label": cls, "_fname": fname})

    # 3. Normalize items (also resolves cached skips from a previous run) ------
    normalized = []
    for it in items:
        cls = it["class_label"]
        host_raw, _, disease_raw = cls.partition("___")
        host = host_raw.replace("_", " ")
        disease = disease_raw.replace("_", " ").strip()
        fname = it.get("_fname") or f"{it['class_idx']:02d}_{it['row_index']}.jpg"
        normalized.append({
            "id": f"pv_{len(normalized):04d}",
            "row_index": it["row_index"],
            "class_idx": it["class_idx"],
            "class_label": cls,
            "host": host,
            "disease": disease,
            "is_healthy": disease.lower() == "healthy",
            "plant_category_expected": CATEGORY_BY_HOST[host],
            "image": {
                "local_path": f"images/{fname}",
                "bytes": (IMG_DIR / fname).stat().st_size,
                "source_row_url": (
                    f"{API}/rows?dataset={DATASET}&config={CONFIG}"
                    f"&split={SPLIT}&offset={it['row_index']}&length=1"
                ),
            },
        })
    items = normalized

    # 4. Write the ground-truth file ------------------------------------------
    hosts = sorted({i["host"] for i in items})
    payload = {
        "source": {
            "dataset": DATASET,
            "dataset_url": f"https://huggingface.co/datasets/{DATASET}",
            "viewer_url": f"https://huggingface.co/datasets/{DATASET}/viewer/{CONFIG}/{SPLIT}",
            "api": API,
            "config": CONFIG,
            "split": SPLIT,
            "total_rows_in_dataset": total,
            "num_classes": len(classes),
            "sampled_items": len(items),
            "sampling": f"{PER_CLASS} images per class at 1/4 and 3/4 depth of each class block",
            "images_downloaded_to": "images/",
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": (
                "Ground truth for benchmarking the LLM diagnosis reports. Labels come "
                "from the dataset, not from any model. plant_category_expected is our "
                "own mapping (fruit vs vegetable crops); the dataset has no such field."
            ),
        },
        "class_distribution": freq,
        "hosts_covered": hosts,
        "items": items,
    }
    out = OUT_DIR / "plantvillage_ground_truth.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out.name}: {len(items)} items, {len(hosts)} hosts, "
          f"{sum(i['is_healthy'] for i in items)} healthy / "
          f"{sum(not i['is_healthy'] for i in items)} diseased")


if __name__ == "__main__":
    main()
