import argparse
import time

from llm_reliability_analytics.workflow.evaluation_jobs import process_queued_jobs, queue_stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process queued evaluation jobs.")
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=10,
        help="Maximum queued jobs to process per iteration.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.0,
        help="If > 0, keep polling queue with this sleep interval.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="How many poll iterations to execute (ignored when poll interval = 0).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    max_jobs = max(1, int(args.max_jobs))
    poll_seconds = float(args.poll_interval_seconds)
    iterations = max(1, int(args.iterations))

    if poll_seconds <= 0:
        result = process_queued_jobs(max_jobs=max_jobs)
        stats = queue_stats()
        print(
            f"processed_count={result.processed_count} "
            f"requested_max_jobs={result.requested_max_jobs} "
            f"queue_total={stats.total}"
        )
        return

    for index in range(iterations):
        result = process_queued_jobs(max_jobs=max_jobs)
        stats = queue_stats()
        print(
            f"iteration={index + 1}/{iterations} "
            f"processed_count={result.processed_count} "
            f"queue_total={stats.total} "
            f"queued={stats.by_status.get('queued', 0)}"
        )
        if index < iterations - 1:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
