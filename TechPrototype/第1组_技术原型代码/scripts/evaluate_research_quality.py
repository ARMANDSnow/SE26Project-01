#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.research_quality_evaluation import (
    EvaluationError,
    generate_predictions,
    load_gold_cases,
    load_predictions,
    score_predictions,
    write_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and score the versioned research Citation gold set."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--predictions", type=Path)
    source.add_argument("--use-llm", action="store_true")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.90)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        cases = load_gold_cases(args.dataset)
        predictions = None
        model_identifier = "not-run"
        evaluation_mode = "validation"
        judge_json_mode = None
        if args.predictions is not None:
            predictions = load_predictions(args.predictions, cases)
            model_identifier = "external-predictions"
            evaluation_mode = "prediction_file"
        elif args.use_llm:
            predictions, model_identifier, judge_json_mode = generate_predictions(cases)
            evaluation_mode = "llm_judge"
        report = score_predictions(
            cases,
            predictions,
            threshold=args.threshold,
            model_identifier=model_identifier,
            evaluation_mode=evaluation_mode,
            judge_json_mode=judge_json_mode,
        )
        write_report(report, json_path=args.output_json, markdown_path=args.output_markdown)
    except EvaluationError as exc:
        print(f"research quality evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(report.status_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
