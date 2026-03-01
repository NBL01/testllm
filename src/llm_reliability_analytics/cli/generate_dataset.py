import argparse
from pathlib import Path

from llm_reliability_analytics.datasets.generator import (
    DatasetGenerationConfig,
    DEFAULT_CATEGORIES,
    generate_dataset_records,
    save_dataset_files,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate structured LLM evaluation datasets.")
    parser.add_argument("--total-cases", type=int, default=300, help="Total number of cases to generate.")
    parser.add_argument(
        "--dataset-version",
        default="v2.0-demo",
        help="Dataset version tag to include in every test case.",
    )
    parser.add_argument(
        "--jsonl-path",
        default="data/raw/llm_eval_dataset_v2_300.jsonl",
        help="Output path for JSONL file.",
    )
    parser.add_argument(
        "--parquet-path",
        default="data/raw/llm_eval_dataset_v2_300.parquet",
        help="Output path for Parquet file.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = DatasetGenerationConfig(
        total_cases=args.total_cases,
        dataset_version=args.dataset_version,
        output_jsonl=Path(args.jsonl_path),
        output_parquet=Path(args.parquet_path),
    )

    records = generate_dataset_records(config)
    save_dataset_files(records, config.output_jsonl, config.output_parquet)

    print(f"Generated {len(records)} test cases")
    print(f"Categories: {', '.join(DEFAULT_CATEGORIES)}")
    print(f"JSONL: {config.output_jsonl}")
    print(f"Parquet: {config.output_parquet}")


if __name__ == "__main__":
    main()
