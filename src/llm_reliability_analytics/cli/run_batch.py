import argparse
import json
from pathlib import Path

from llm_reliability_analytics.workflow.service import run_batch_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a test batch with the mock LLM client.")
    parser.add_argument(
        "--input",
        default="sample_test_cases.jsonl",
        help="Input file name/path (.jsonl or .csv). Relative names resolve from data/raw/.",
    )
    parser.add_argument(
        "--mode",
        choices=["deterministic", "semi_random"],
        default="deterministic",
        help="Mock LLM behavior mode.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed used by the mock LLM client.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of cases to run.",
    )
    parser.add_argument(
        "--run-name",
        default="cli-demo-run",
        help="Logical name for the run.",
    )
    parser.add_argument(
        "--model-name",
        default="mock-llm",
        help="Model label stored with the run.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to write full results JSON.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_batch_workflow(
        input_path=args.input,
        run_name=args.run_name,
        model_name=args.model_name,
        mode=args.mode,
        seed=args.seed,
        limit=args.limit,
    )

    print("Run summary")
    print(
        f"  run_id={result.run_id} "
        f"loaded_test_cases={result.loaded_test_cases} "
        f"executed_test_cases={result.executed_test_cases}"
    )
    print(
        f"  accuracy={result.report.accuracy:.3f} "
        f"average_latency_ms={result.report.average_latency_ms:.2f} "
        f"overall_reliability_score={result.report.overall_reliability_score:.3f}"
    )
    if result.report.error_distribution:
        print(f"  errors={result.report.error_distribution}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump(mode="json")
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote results to {output_path}")


if __name__ == "__main__":
    main()
