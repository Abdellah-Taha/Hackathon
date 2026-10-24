"""Benchmark: send 10 PlantVillage images to the LLM and score its reports.

Reads the ground truth fetched from geraldmc/plantvillage-full
(benchmark/plantvillage_ground_truth.json), picks 10 items -- 4 healthy /
6 diseased, all with distinct class labels -- sends each image to
plantdoc.main.diagnose_plant_image with NO hints (blind test), saves every
raw report, then compares:

  - healthy-vs-diseased verdict (overall_status + severity)
  - host (plant species) identification, incl. fuzzy match
  - top-3 possible_causes hit rate against the dataset disease label
  - plant_category prediction
  - confidence calibration (does "high" confidence correlate with being right?)

Results land in benchmark/results/: one JSON per image + a scored summary.

Usage:
  python run_benchmark.py                # live LLM calls (needs GEMINI_API_KEY)
  python run_benchmark.py --limit 3      # quick smoke run
  python run_benchmark.py --mock         # schema/pipeline test without API key
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
ROOT = BENCH_DIR.parent
sys.path.insert(0, str(ROOT))

from plantdoc.main import PlantReport, create_mock_report, diagnose_plant_image  # noqa: E402

GT_FILE = BENCH_DIR / "plantvillage_ground_truth.json"
RESULTS_DIR = BENCH_DIR / "results"
N_ITEMS = 10
N_HEALTHY = 4  # 4 healthy + 6 diseased
API_SLEEP = 3  # seconds between LLM calls (free-tier friendliness)
RETRY_503 = 4  # gemini-3.8-flash intermittently returns 503; retries succeed

# Words that make a cause name a match for the dataset's disease label, beyond
# plain fuzzy matching (dataset label -> LLM vocabulary).
SYNONYMS = {
    "haunglongbing (citrus greening)": ["citrus greening", "huanglongbing", "hlb", "greening"],
    "spider mites two-spotted spider mite": ["spider mite"],
    "common rust": ["rust"],
    "cercospora leaf spot gray leaf spot": ["gray leaf spot", "grey leaf spot", "cercospora"],
}


# ---------------------------------------------------------------------------
# Item selection
# ---------------------------------------------------------------------------
def select_items(gt: dict, limit: int, seed: int = 42) -> list[dict]:
    """Deterministically pick `limit` items: first N_HEALTHY healthy, rest diseased."""
    items = gt["items"]
    healthy = [i for i in items if i["is_healthy"]]
    diseased = [i for i in items if not i["is_healthy"]]

    def spread(pool: list[dict], k: int) -> list[dict]:
        """Greedy pick maximizing distinct classes, then distinct hosts."""
        picked: list[dict] = []
        while pool and len(picked) < k:
            pool.sort(key=lambda i: (
                i["class_label"] in {p["class_label"] for p in picked},
                i["host"] in {p["host"] for p in picked},
                i["id"],
            ))
            picked.append(pool.pop(0))
        return picked

    rng = random.Random(seed)
    h = spread(rng.sample(healthy, len(healthy)), min(N_HEALTHY, limit))
    d = spread(rng.sample(diseased, len(diseased)), max(0, limit - len(h)))
    return sorted(h + d, key=lambda i: i["id"])


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------
def fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def tokens(s: str) -> list[str]:
    """Lowercase word tokens, punctuation dropped, dataset stop-words removed."""
    stop = {"including", "sour", "maize"}
    return [t for t in re.findall(r"[a-z]+", s.lower()) if t not in stop]


def status_is_healthy(report: PlantReport) -> bool:
    """Overall status 'healthy', or low-severity 'monitor' with no concrete causes."""
    if report.overall_status == "healthy":
        return True
    return (
        report.overall_status == "monitor"
        and report.severity == "low"
        and len(report.possible_causes) == 0
    )


def host_matches(report: PlantReport, host: str) -> tuple[bool, float, str]:
    """Match reported plant name against the dataset host.

    Token-based so punctuation/word-order variants match: "Pepper, bell" vs
    "Bell pepper", "Corn (maize)" vs "Maize corn", "Cherry (including sour)"
    vs "Sour cherry".
    """
    reported, target = tokens(report.plant_name), tokens(host)
    if not reported or not target:
        return False, 0.0, report.plant_name
    contained = set(target) <= set(reported) or set(reported) <= set(target)
    overlap = bool(set(target) & set(reported))
    score = round(SequenceMatcher(
        None, " ".join(reported), " ".join(target)).ratio(), 2)
    return (contained or overlap), score, report.plant_name


def cause_matches(report: PlantReport, disease: str) -> tuple[bool, str | None, float]:
    """True if any of the top-3 possible_causes matches the dataset disease."""
    names = [c.name for c in report.possible_causes[:3]]
    target = disease.lower().strip()
    best_name, best_score = None, 0.0

    for name in names:
        low = name.lower().strip()
        if low in SYNONYMS.get(target, []):
            return True, name, 1.0
        for syn in SYNONYMS.get(target, []):
            if syn in low or fuzzy(low, syn) >= 0.75:
                return True, name, 1.0
        # "healthy" ground truth matches causes like "no disease / environmental"
        if target == "healthy" and any(w in low for w in
                                       ("no disease", "no pathogen", "not a disease",
                                        "environmental", "nutrient", "physiolog")):
            return True, name, 1.0
        # substring either way (e.g. "early blight" in "tomato early blight")
        if target in low or low in target:
            return True, name, 1.0
        score = fuzzy(low, target)
        if score > best_score:
            best_name, best_score = name, score

    if best_score >= 0.70:
        return True, best_name, round(best_score, 2)
    return False, best_name, round(best_score, 2)


# ---------------------------------------------------------------------------
# Scoring one item
# ---------------------------------------------------------------------------
def score_item(item: dict, report: PlantReport, latency_s: float) -> dict:
    gt_healthy = item["is_healthy"]
    pred_healthy = status_is_healthy(report)

    host_ok, host_score, reported_name = host_matches(report, item["host"])
    cause_ok, cause_hit, cause_score = cause_matches(report, item["disease"])

    top_conf = report.possible_causes[0].confidence if report.possible_causes else None

    return {
        "id": item["id"],
        "class_label": item["class_label"],
        "image": item["image"]["local_path"],
        "latency_s": round(latency_s, 1),
        "ground_truth": {
            "host": item["host"],
            "disease": item["disease"],
            "is_healthy": gt_healthy,
            "plant_category_expected": item["plant_category_expected"],
        },
        "llm": {
            "plant_name": reported_name,
            "plant_category": report.plant_category,
            "overall_status": report.overall_status,
            "severity": report.severity,
            "top_causes": [
                {"name": c.name, "confidence": c.confidence}
                for c in report.possible_causes[:3]
            ],
            "top_confidence": top_conf,
        },
        "scores": {
            "verdict_correct": pred_healthy == gt_healthy,
            "healthy_when_healthy": pred_healthy and gt_healthy,
            "diseased_when_diseased": (not pred_healthy) and (not gt_healthy),
            "host_correct": host_ok,
            "host_similarity": host_score,
            "cause_hit_top3": cause_ok,
            "cause_best_match": cause_hit,
            "cause_similarity": cause_score,
            "category_correct": report.plant_category == item["plant_category_expected"],
            "severity_matches_gt": (
                report.severity == "low" if gt_healthy else report.severity in ("moderate", "high")
            ),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=N_ITEMS,
                    help=f"number of images to test (default {N_ITEMS})")
    ap.add_argument("--mock", action="store_true",
                    help="use create_mock_report() instead of live API calls")
    ap.add_argument("--model", default="gemini-3.8-flash")
    args = ap.parse_args()

    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    items = select_items(gt, args.limit)
    RESULTS_DIR.mkdir(exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "mock" if args.mock else f"live:{args.model}"
    print(f"Benchmark {mode} | {len(items)} items | "
          f"{sum(i['is_healthy'] for i in items)} healthy / "
          f"{sum(not i['is_healthy'] for i in items)} diseased\n")

    results: list[dict] = []
    for n, item in enumerate(items, 1):
        img = ROOT / "benchmark" / item["image"]["local_path"]
        print(f"[{n:>2}/{len(items)}] {item['class_label']:<45} ", end="", flush=True)
        out_file = RESULTS_DIR / f"report_{item['id']}.json"
        if not args.mock and out_file.exists() and out_file.stat().st_size > 100:
            try:
                cached_report = PlantReport.model_validate_json(
                    out_file.read_text(encoding="utf-8"))
            except Exception:
                cached_report = None
            if cached_report is not None:
                row = score_item(item, cached_report, 0.0)
                row["cached"] = True
                results.append(row)
                s = row["scores"]
                print(f"-> {cached_report.plant_name:<22} "
                      f"{'OK ' if s['verdict_correct'] else 'MISS'} "
                      f"host={s['host_correct']!s:<5} "
                      f"cause={s['cause_hit_top3']!s:<5} (cached)")
                continue
        t0 = time.time()
        try:
            if args.mock:
                report = create_mock_report(plant_hint="")
            else:
                report = None
                for attempt in range(RETRY_503):
                    try:
                        report = diagnose_plant_image(
                            image_input=img,
                            plant_hint="",  # BLIND: no host, no symptoms, no region
                            model_name=args.model,
                        )
                        break
                    except Exception as exc:
                        msg = str(exc)
                        # Daily quota (free tier: 20 req/day) is not retryable today
                        if "429" in msg and "per day" in msg.lower():
                            raise RuntimeError(
                                "DAILY FREE-TIER QUOTA EXHAUSTED for "
                                f"{args.model}; rerun after the quota reset "
                                "(~midnight Pacific). Completed items are cached."
                            )
                        transient = (
                            "503" in msg
                            or "unavailable" in msg.lower()
                            or ("429" in msg and "per minute" in msg.lower())
                        )
                        if transient and attempt < RETRY_503 - 1:
                            time.sleep(60 if "429" in msg else 10 * (attempt + 1))
                            continue
                        raise
            latency = time.time() - t0
        except Exception as exc:
            print(f"FAILED: {str(exc)[:80]}")
            results.append({
                "id": item["id"], "class_label": item["class_label"],
                "image": item["image"]["local_path"], "error": str(exc)[:300],
            })
            continue

        out_file = RESULTS_DIR / f"report_{item['id']}.json"
        if not args.mock:  # mock runs must not pollute the live-results cache
            out_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        row = score_item(item, report, latency)
        results.append(row)
        s = row["scores"]
        print(f"-> {report.plant_name:<22} {'OK ' if s['verdict_correct'] else 'MISS'} "
              f"host={s['host_correct']!s:<5} cause={s['cause_hit_top3']!s:<5} "
              f"({row['latency_s']}s)")
        if not args.mock:
            time.sleep(API_SLEEP)

    ok_rows = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    total = len(ok_rows)
    summary = {
        "run": {
            "mode": mode,
            "started_at_utc": stamp,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items_requested": len(items),
            "items_scored": total,
            "items_failed": len(failed),
            "ground_truth_file": str(GT_FILE.relative_to(ROOT)),
        },
        "aggregate": {},
        "calibration": {},
        "per_item": results,
    }

    if total:
        def rate(key: str) -> float:
            return round(100 * sum(1 for r in ok_rows if r["scores"][key]) / total, 1)

        hh = [r for r in ok_rows if r["ground_truth"]["is_healthy"]]
        dd = [r for r in ok_rows if not r["ground_truth"]["is_healthy"]]
        summary["aggregate"] = {
            "verdict_accuracy_pct": rate("verdict_correct"),
            "healthy_detected_pct": round(100 * sum(r["scores"]["healthy_when_healthy"] for r in hh) / len(hh), 1) if hh else None,
            "disease_detected_pct": round(100 * sum(r["scores"]["diseased_when_diseased"] for r in dd) / len(dd), 1) if dd else None,
            "host_identification_pct": rate("host_correct"),
            "cause_hit_top3_pct": rate("cause_hit_top3"),
            "category_accuracy_pct": rate("category_correct"),
            "avg_latency_s": round(sum(r["latency_s"] for r in ok_rows) / total, 1),
        }
        # calibration: top-cause confidence vs whether the cause was actually right
        calib = {}
        for level in ("high", "medium", "low"):
            grp = [r for r in ok_rows if r["llm"]["top_confidence"] == level]
            if grp:
                calib[level] = {
                    "n": len(grp),
                    "cause_hit_pct": round(100 * sum(r["scores"]["cause_hit_top3"] for r in grp) / len(grp), 1),
                }
        summary["calibration"] = calib

    out = RESULTS_DIR / f"summary_{stamp}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n==== RESULTS ({total} scored, {len(failed)} failed) " + "=" * 20)
    for k, v in summary["aggregate"].items():
        print(f"  {k:<28} {v}")
    print(f"  saved: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
