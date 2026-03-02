"""Frontend helper actions for trace promotion workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def mark_trace_candidate(
    trace_payload: dict[str, Any],
    target_source: str,
    project_root: Path,
) -> Path:
    candidate_dir = project_root / "data" / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    file_path = candidate_dir / f"{target_source}_candidates.jsonl"
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace_payload, ensure_ascii=True) + "\n")
    return file_path
