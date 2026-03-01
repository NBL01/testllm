import json
from pathlib import Path

from llm_reliability_analytics.models.domain import TestResult as DomainTestResult
from llm_reliability_analytics.storage.duckdb_store import (
    create_test_run,
    initialize_storage_schema,
    insert_batch_results,
)


def test_eda_notebook_executes_with_duckdb_source(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "notebook_eda.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    monkeypatch.setenv("MPLBACKEND", "Agg")

    initialize_storage_schema()
    run = create_test_run(name="notebook-demo", model_name="mock-llm")
    insert_batch_results(
        [
            DomainTestResult(
                run_id=run.id,
                test_case_id="n-1",
                category="math",
                actual_answer="4",
                is_correct=True,
                score=1.0,
                latency_ms=100.0,
                error_type=None,
            ),
            DomainTestResult(
                run_id=run.id,
                test_case_id="n-2",
                category="reasoning",
                actual_answer="wrong",
                is_correct=False,
                score=0.0,
                latency_ms=250.0,
                error_type="wrong_answer",
            ),
        ]
    )

    notebook_path = (
        Path(__file__).resolve().parents[1] / "notebooks" / "llm_test_results_eda.ipynb"
    )
    namespace = _execute_notebook_cells(notebook_path)

    assert "df" in namespace
    assert len(namespace["df"]) >= 2
    assert "category_accuracy" in namespace
    assert not namespace["category_accuracy"].empty
    assert "error_freq" in namespace
    assert not namespace["error_freq"].empty


def _execute_notebook_cells(notebook_path: Path) -> dict:
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    namespace: dict = {}

    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        # Remove notebook magics so cells can run in normal Python during tests.
        source = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("%")
        )
        if not source.strip():
            continue
        exec(compile(source, f"<notebook-cell-{index}>", "exec"), namespace)

    return namespace
