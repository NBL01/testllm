"""Complete attempt exports with RFC-style quoting and spreadsheet-safe text.

Every cell is quoted, quotes are doubled and records use CRLF. Risky text gets
a leading apostrophe (including whitespace/control-prefixed formula markers).
This deliberately changes exported text; stored evidence is never modified.
Consumers needing exact raw text should use the JSON evidence endpoint instead.
"""

from collections.abc import Iterable, Mapping
import csv
from io import StringIO
from typing import Any
import unicodedata

from pydantic import BaseModel

from llm_reliability_analytics.storage.db import get_connection, initialize_schema


FAILED_CASE_FIELDS = (
    "run_id", "test_case_id", "attempt_index", "category", "test_source", "oracle_type",
    "prompt", "expected_answer", "actual_answer", "raw_output", "normalized_output",
    "is_correct", "score", "error_type", "explanation", "latency_ms", "latency_source",
    "oracle_details_json",
)


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    # Some importers discard leading whitespace or invisible controls before
    # interpreting formulas. Check beyond them without deleting the evidence.
    start = 0
    while start < len(value) and (value[start].isspace() or unicodedata.category(value[start]).startswith("C")):
        start += 1
    probe = value[start:]
    if value.startswith(("\t", "\r", "\n")) or probe.startswith(("=", "+", "-", "@", "\uff1d", "\uff0b", "\uff0d", "\uff20")):
        return "'" + value
    return value


def render_failed_cases_csv(rows: Iterable[BaseModel | Mapping[str, Any]]) -> str:
    """Serialize all supplied attempts; no pagination or sampling is applied."""
    output = StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(FAILED_CASE_FIELDS)
    for row in rows:
        values = row.model_dump() if isinstance(row, BaseModel) else row
        writer.writerow([_safe_cell(values.get(field)) for field in FAILED_CASE_FIELDS])
    return output.getvalue()


def export_failed_cases_csv(run_id: str) -> str:
    """Export every failed result snapshot for a run, even if trace capture failed.

    Callers must validate/authorize the job/run and return text/csv; an absent or
    empty run produces a header-only CSV. No mutable test_cases fallback is used.
    """
    initialize_schema()
    conn = get_connection()
    try:
        cursor = conn.execute(
            f"""SELECT {', '.join(FAILED_CASE_FIELDS)} FROM test_results
                WHERE run_id = ? AND is_correct = FALSE
                ORDER BY score, latency_ms, test_case_id, attempt_index;""",
            [run_id],
        )

        def rows() -> Iterable[dict[str, Any]]:
            while batch := cursor.fetchmany(1000):
                for row in batch:
                    yield dict(zip(FAILED_CASE_FIELDS, row))

        return render_failed_cases_csv(rows())
    finally:
        conn.close()
