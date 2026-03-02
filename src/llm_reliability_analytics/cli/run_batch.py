import argparse
import json
from pathlib import Path

from llm_reliability_analytics.runner.llm_client import DEFAULT_LOCAL_MODEL
from llm_reliability_analytics.workflow.service import run_batch_workflow, run_trace_replay_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a test batch for LLM reliability analytics.")
    parser.add_argument(
        "--input",
        default="sample_test_cases.jsonl",
        help="Input file name/path (.jsonl or .csv). Relative names resolve from data/raw/.",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Alias for --input (dataset file name/path).",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "ollama"],
        default="mock",
        help="Execution provider: mock or local Ollama.",
    )
    parser.add_argument(
        "--model",
        dest="model_name",
        default=None,
        help="Model name. Example: llama3.2:1b, qwen2.5:1.5b, mock-baseline.",
    )
    parser.add_argument(
        "--model-name",
        dest="model_name_alias",
        default=None,
        help="Alias for --model.",
    )
    parser.add_argument(
        "--mock-mode",
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
        "--run-label",
        default=None,
        help="Optional human-readable run label shown in dashboards.",
    )
    parser.add_argument(
        "--model-version",
        default="n/a",
        help="Model version label for traceability.",
    )
    parser.add_argument(
        "--dataset-version",
        default=None,
        help="Optional dataset version tag for this run.",
    )
    parser.add_argument(
        "--evaluation-mode",
        choices=["regression", "exploratory", "adversarial", "trace_replay"],
        default="regression",
        help="Evaluation mode label for grouping and coverage analytics.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature used in the run metadata.",
    )
    parser.add_argument(
        "--run-mode",
        choices=["mock", "real_local"],
        default=None,
        help="Override execution mode metadata. By default inferred from provider.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=128,
        help="Maximum output tokens/length requested from provider.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds for local model calls.",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional notes stored with the run.",
    )
    parser.add_argument(
        "--run-group-id",
        default=None,
        help="Optional run group id for repeated experiments.",
    )
    parser.add_argument(
        "--repeat-count",
        type=int,
        default=1,
        help="How many times to execute each test case in the run.",
    )
    parser.add_argument(
        "--repeats-per-case",
        type=int,
        default=None,
        help="Backward-compatible alias for --repeat-count.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to write full results JSON.",
    )
    parser.add_argument(
        "--trace-replay-run-id",
        default=None,
        help="If provided, run in trace replay mode using traces from this run_id.",
    )
    parser.add_argument(
        "--trace-replay-only-failed",
        action="store_true",
        help="For trace replay, use only failed traces.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dataset_input = args.dataset if args.dataset else args.input
    resolved_model = args.model_name_alias or args.model_name
    if not resolved_model:
        resolved_model = DEFAULT_LOCAL_MODEL if args.provider == "ollama" else "mock-baseline"

    run_mode = args.run_mode or ("real_local" if args.provider == "ollama" else "mock")
    repeats_per_case = args.repeats_per_case if args.repeats_per_case is not None else args.repeat_count

    if args.trace_replay_run_id:
        result = run_trace_replay_workflow(
            source_run_id=args.trace_replay_run_id,
            run_name=args.run_name,
            run_label=args.run_label,
            model_name=resolved_model,
            dataset_version=args.dataset_version or "trace_replay_v1",
            provider=args.provider,
            notes=args.notes,
            only_failed=bool(args.trace_replay_only_failed),
            max_cases=args.limit or 200,
            repeats_per_case=repeats_per_case,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout,
            run_mode=run_mode,
            mock_mode=args.mock_mode,
            seed=args.seed,
        )
    else:
        result = run_batch_workflow(
            input_path=dataset_input,
            run_name=args.run_name,
            run_label=args.run_label,
            model_name=resolved_model,
            provider=args.provider,
            model_version=args.model_version,
            dataset_version=args.dataset_version,
            evaluation_mode=args.evaluation_mode,
            temperature=args.temperature,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout,
            run_mode=run_mode,
            notes=args.notes,
            run_group_id=args.run_group_id,
            mock_mode=args.mock_mode,
            seed=args.seed,
            limit=args.limit,
            repeats_per_case=repeats_per_case,
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
