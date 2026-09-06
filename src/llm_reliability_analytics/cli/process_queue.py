import argparse
import os
import time

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process queued evaluation jobs through FastAPI (no local DB access).")
    parser.add_argument("--api-base-url", default=os.getenv("LLM_RELIABILITY_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--request-timeout-seconds", type=float,
                        default=float(os.getenv("LLM_RELIABILITY_API_ACTION_TIMEOUT_SECONDS", "3600")),
                        help="HTTP timeout for synchronous processing; timeout does not cancel backend work.")
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
    parser = build_parser()
    args = parser.parse_args()
    max_jobs = max(1, int(args.max_jobs))
    if max_jobs > 500:
        parser.error("--max-jobs must be at most 500 (FastAPI limit)")
    if args.request_timeout_seconds <= 0:
        parser.error("--request-timeout-seconds must be positive")
    poll_seconds = float(args.poll_interval_seconds)
    iterations = max(1, int(args.iterations))

    iterations = iterations if poll_seconds > 0 else 1
    for index in range(iterations):
        try:
            result = _request(args, "POST", "/evaluation-jobs/process-queue", params={"max_jobs": max_jobs})
            stats = _request(args, "GET", "/evaluation-jobs/queue/stats")
            if poll_seconds <= 0:
                print(f"processed_count={result['processed_count']} "
                      f"requested_max_jobs={result['requested_max_jobs']} queue_total={stats['total']}")
            else:
                print(f"iteration={index + 1}/{iterations} processed_count={result['processed_count']} "
                      f"queue_total={stats['total']} queued={stats['by_status'].get('queued', 0)}")
        except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
            parser.exit(1, f"FastAPI queue request failed: {exc}. Check {args.api_base_url}. "
                        "Processing may still be running; inspect queue state before retrying.\n")
        if index < iterations - 1:
            time.sleep(poll_seconds)


def _request(args, method: str, path: str, params: dict | None = None) -> dict:
    response = httpx.request(method, args.api_base_url.rstrip("/") + path, params=params,
                            timeout=httpx.Timeout(args.request_timeout_seconds, connect=5.0))
    if not response.is_success:
        raise ValueError(f"HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


if __name__ == "__main__":
    main()
