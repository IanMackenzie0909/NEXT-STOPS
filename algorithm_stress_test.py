from __future__ import annotations

import os
from pathlib import Path
from statistics import mean
from typing import List

import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/next-stops-matplotlib")

import matplotlib.pyplot as plt

from algorithm import (
    Place,
    SCENARIO_CONFIGS,
    count_output_constraint_violations,
    generate_candidates,
    make_user_state,
    recommend,
)


# ============================================================
# Stress test
# ============================================================

def run_stress_test(
    candidates: List[Place],
    n_per_scenario: int = 180,
) -> pd.DataFrame:
    """
    Run deterministic stress test across all user-state categories.
    """

    rows = []

    for scenario_name, config in SCENARIO_CONFIGS.items():
        for _ in range(n_per_scenario):
            user = make_user_state(scenario_name, config)

            recommendations, filtered_reasons = recommend(
                candidates=candidates,
                user=user,
                k=5,
            )

            scores = [item.score for item in recommendations]
            uncertainties = [item.uncertainty for item in recommendations]
            categories = [item.place.category for item in recommendations]
            qualities = [item.place.quality for item in recommendations]
            constraint_violations = count_output_constraint_violations(
                recommendations=recommendations,
                user=user,
            )

            rows.append(
                {
                    "scenario": scenario_name,
                    "valid_recommendation_count": len(recommendations),
                    "has_3plus": len(recommendations) >= 3,
                    "avg_top5_score": mean(scores) if scores else 0.0,
                    "top1_score": scores[0] if scores else 0.0,
                    "avg_uncertainty": mean(uncertainties) if uncertainties else 0.0,
                    "avg_quality": mean(qualities) if qualities else 0.0,
                    "diversity_top5": len(set(categories)) / 5 if categories else 0.0,
                    "fallback_used": int(any(item.fallback for item in recommendations)),
                    "output_constraint_violations": constraint_violations,
                }
            )

    return pd.DataFrame(rows)


def summarize_results(test_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate stress test results by scenario."""

    summary = (
        test_df
        .groupby("scenario")
        .agg(
            pass_rate=("has_3plus", "mean"),
            avg_top5_score=("avg_top5_score", "mean"),
            avg_uncertainty=("avg_uncertainty", "mean"),
            avg_quality=("avg_quality", "mean"),
            diversity_top5=("diversity_top5", "mean"),
            fallback_rate=("fallback_used", "mean"),
            output_constraint_violations=("output_constraint_violations", "sum"),
        )
        .reset_index()
    )

    # Composite simulation stability index.
    # This is not a recommendation accuracy metric. It is only a practical
    # evaluation index for comparing scenario-level stability during development.
    violation_penalty = (
        summary["output_constraint_violations"]
        / test_df.groupby("scenario").size().reindex(summary["scenario"]).values
    ).clip(0, 1)

    summary["stability_index"] = (
        0.30 * summary["pass_rate"]
        + 0.25 * summary["avg_top5_score"]
        + 0.20 * summary["diversity_top5"]
        + 0.15 * summary["avg_quality"]
        + 0.10 * (1 - summary["avg_uncertainty"].clip(0, 1))
        - 0.25 * violation_penalty
        - 0.10 * summary["fallback_rate"]
    ).clip(0, 1)

    summary = summary.sort_values("stability_index", ascending=False)

    return summary


def save_chart(summary: pd.DataFrame, output_path: Path) -> None:
    """Save simulation stability chart."""

    plt.figure(figsize=(13, 7))
    plt.bar(summary["scenario"], summary["stability_index"])
    plt.xticks(rotation=55, ha="right")
    plt.ylim(0, 1)
    plt.ylabel("Simulation Stability Index")
    plt.title("NEXT STOPS Algorithm Stress Test: Stability by User-State Category")
    plt.tight_layout()
    plt.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close()


# ============================================================
# Main entry
# ============================================================

def main() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    candidates = generate_candidates(n=360)

    test_df = run_stress_test(
        candidates=candidates,
        n_per_scenario=180,
    )

    summary = summarize_results(test_df)

    summary_csv = output_dir / "next_stops_algorithm_simulation_summary.csv"
    detail_csv = output_dir / "next_stops_algorithm_simulation_detail.csv"
    chart_png = output_dir / "next_stops_algorithm_stress_test_chart.png"

    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    test_df.to_csv(detail_csv, index=False, encoding="utf-8-sig")
    save_chart(summary, chart_png)

    print("NEXT STOPS algorithm stress test completed.")
    print(f"Summary CSV: {summary_csv}")
    print(f"Detail CSV: {detail_csv}")
    print(f"Chart PNG: {chart_png}")
    print()
    print(summary)


if __name__ == "__main__":
    main()
