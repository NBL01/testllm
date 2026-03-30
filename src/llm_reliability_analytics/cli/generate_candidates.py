from __future__ import annotations

import argparse
from pathlib import Path

from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.test_authoring.service import CandidateAuthoringService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate candidate test cases for human review.")
    parser.add_argument(
        "--categories",
        default="",
        help="Comma-separated categories. Empty means all default core categories.",
    )
    parser.add_argument(
        "--per-category",
        type=int,
        default=5,
        help="How many candidates to generate per category.",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "ollama", "none"],
        default="none",
        help="Optional LLM provider for prompt rewrite assistance.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name when provider is ollama/mock.",
    )
    parser.add_argument(
        "--output",
        default="data/candidates/generated_candidate_test_cases.jsonl",
        help="Output JSONL path.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    categories = [item.strip() for item in args.categories.split(",") if item.strip()]

    llm_client = None
    if args.provider != "none":
        model_name = args.model or ("mock-baseline" if args.provider == "mock" else None)
        llm_client = build_llm_client(
            provider=args.provider,
            run_mode="real_local" if args.provider == "ollama" else "mock",
            model_name=model_name,
            temperature=0.1,
            max_output_tokens=120,
            timeout_seconds=20.0,
        )

    service = CandidateAuthoringService(llm_client=llm_client)
    candidates = service.generate_candidates(categories=categories, per_category=max(1, args.per_category))
    output_path = Path(args.output)
    service.save_candidates(candidates, output_path=output_path)

    reviewed_count = sum(1 for candidate in candidates if not candidate.validation_errors)
    print(f"Generated candidates: {len(candidates)}")
    print(f"Validation-clean candidates: {reviewed_count}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
