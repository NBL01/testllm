"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { compareRuns, listJobs } from "@/lib/api";
import { ApiClientError } from "@/lib/apiClient";
import { formatDate, formatMs, formatPercent } from "@/lib/format";
import { useRemoteResource } from "@/lib/useRemoteResource";
import type { CaseChange, EvaluationJob, MetricsReport, RunComparison } from "@/lib/types";

const ISSUE_TEXT: Record<string, string> = {
  dataset_sha256: "The frozen dataset contents differ.",
  dataset_version: "The dataset version differs.",
  evaluation_mode: "The evaluation mode differs.",
  "test case coverage/evidence": "The runs cover different test cases or expected answers.",
  input_config: "The oracle configuration differs for at least one case.",
  "incomplete attempt coverage/evidence": "A run is missing attempts for some cases.",
  repeat_count: "The repeat count differs.",
  temperature: "The temperature differs.",
  max_output_tokens: "The max output tokens differ.",
  timeout_seconds: "The timeout differs.",
  provider: "One run is a mock simulation and the other a real model.",
  mode: "One run is a mock simulation and the other a real model.",
  model_version: "The same model name ran with different versions.",
  "only completed runs can be compared": "Only completed runs can be compared."
};

function describeIssue(issue: string): string {
  if (issue.startsWith("unknown ")) return `An older run did not record ${issue.slice(8)}.`;
  if (issue.startsWith("no stored evidence")) return "A run has no stored results.";
  return ISSUE_TEXT[issue] ?? "Settings differ.";
}

type Outcome = { comparable: true; data: RunComparison } | { comparable: false; issues: string[] };

type MetricRow = { label: string; value: (report: MetricsReport) => number | null | undefined; kind: "rate" | "ms" | "score"; higherIsBetter: boolean };

const METRICS: MetricRow[] = [
  { label: "Pass rate", value: report => report.accuracy, kind: "rate", higherIsBetter: true },
  { label: "pass^k (all attempts pass)", value: report => report.pass_hat_k, kind: "rate", higherIsBetter: true },
  { label: "pass@k (any attempt passes)", value: report => report.pass_at_k, kind: "rate", higherIsBetter: true },
  { label: "Schema pass rate", value: report => report.schema_pass_rate, kind: "rate", higherIsBetter: true },
  { label: "Latency p50", value: report => report.p50_latency_ms, kind: "ms", higherIsBetter: false },
  { label: "Latency p95", value: report => report.p95_latency_ms, kind: "ms", higherIsBetter: false },
  { label: "Legacy composite (legacy-v1)", value: report => report.overall_reliability_score, kind: "score", higherIsBetter: true }
];

function show(value: number | null | undefined, kind: MetricRow["kind"]): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  return kind === "rate" ? formatPercent(value, 1) : kind === "ms" ? formatMs(value) : value.toFixed(3);
}

function Delta({ before, after, kind, higherIsBetter }: { before?: number | null; after?: number | null; kind: MetricRow["kind"]; higherIsBetter: boolean }) {
  if (before == null || after == null) return <span className="meta">—</span>;
  const diff = after - before;
  // Below the displayed precision a change is noise, not a regression.
  const precision = kind === "rate" ? 0.0005 : kind === "ms" ? 0.5 : 0.0005;
  if (Math.abs(diff) < precision) return <span className="meta">no change</span>;
  const text = kind === "rate" ? `${diff > 0 ? "+" : ""}${(diff * 100).toFixed(1)} pts` : kind === "ms" ? `${diff > 0 ? "+" : ""}${diff.toFixed(0)} ms` : `${diff > 0 ? "+" : ""}${diff.toFixed(3)}`;
  return <span className={(diff > 0) === higherIsBetter ? "delta-good" : "delta-bad"}>{text}</span>;
}

function jobLabel(job: EvaluationJob): string {
  return `${job.project_name || `Job ${job.job_id.slice(0, 8)}`} · ${job.model_name} · ${formatDate(job.created_at)}`;
}

async function loadComparison(baseline: EvaluationJob, candidate: EvaluationJob): Promise<Outcome> {
  try {
    return { comparable: true, data: await compareRuns(baseline.linked_run_id!, candidate.linked_run_id!) };
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 409) {
      const detail = (error.responseBody as { detail?: { issues?: unknown } } | undefined)?.detail;
      return { comparable: false, issues: Array.isArray(detail?.issues) ? detail.issues.map(String) : [error.detail] };
    }
    throw error;
  }
}

function CaseList({ title, items, empty }: { title: string; items: CaseChange[]; empty: string }) {
  return (
    <div>
      <h3 className="section-title">{title} ({items.length})</h3>
      {items.length ? <ul className="case-list">{items.map(item => (
        <li key={item.test_case_id}>
          <strong>{item.test_case_id}</strong> <span className="meta">{item.category}</span>
          <span className="case-move">{item.baseline_passed}/{item.attempts} → {item.candidate_passed}/{item.attempts}</span>
        </li>
      ))}</ul> : <p className="meta">{empty}</p>}
    </div>
  );
}

export default function ComparePage() {
  return <Suspense fallback={<main className="page"><p className="meta">Loading comparison...</p></main>}><Compare /></Suspense>;
}

function Compare() {
  const params = useSearchParams();
  const [baselineId, setBaselineId] = useState(params.get("baseline") ?? "");
  const [candidateId, setCandidateId] = useState(params.get("candidate") ?? "");
  const jobsResource = useRemoteResource("completed-jobs", () => listJobs({ status: "completed", limit: 200 }));
  const jobs = (jobsResource.data?.items ?? []).filter(job => job.linked_run_id);
  const baseline = jobs.find(job => job.job_id === baselineId);
  const candidate = jobs.find(job => job.job_id === candidateId);
  const ready = !!baseline && !!candidate && baseline.job_id !== candidate.job_id;
  const comparison = useRemoteResource(ready ? `${baselineId}:${candidateId}` : null, () => loadComparison(baseline!, candidate!));
  const outcome = comparison.data;
  const result = outcome?.comparable ? outcome.data : null;
  const categories = result ? [...new Set([...(result.baseline_report.category_reports ?? []), ...(result.candidate_report.category_reports ?? [])].map(item => item.category))].sort() : [];
  const categoryRate = (report: MetricsReport, category: string) => report.category_reports?.find(item => item.category === category)?.accuracy;

  const picker = (label: string, value: string, onChange: (id: string) => void) => (
    <label>
      {label}
      <select value={value} onChange={event => onChange(event.target.value)}>
        <option value="">Select a completed job</option>
        {jobs.map(job => <option key={job.job_id} value={job.job_id}>{jobLabel(job)}</option>)}
      </select>
    </label>
  );

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Compare Runs</h1>
          <p>Put two completed jobs side by side. Only runs with the same frozen dataset, oracle configuration and generation settings are compared.</p>
        </div>
      </section>

      <section className="panel grid">
        <div className="form-grid">
          {picker("Baseline", baselineId, setBaselineId)}
          {picker("Candidate", candidateId, setCandidateId)}
        </div>
        <div className="btn-row">
          <button className="btn btn-secondary" type="button" disabled={!baselineId && !candidateId}
            onClick={() => { setBaselineId(candidateId); setCandidateId(baselineId); }}>Swap</button>
          {baseline && <Link className="btn btn-secondary" href={`/jobs/${baseline.job_id}`}>Open baseline</Link>}
          {candidate && <Link className="btn btn-secondary" href={`/jobs/${candidate.job_id}`}>Open candidate</Link>}
        </div>
        {jobsResource.error && <p className="error" role="alert">Jobs: {jobsResource.error}</p>}
        {!jobsResource.loading && !jobs.length && !jobsResource.error && <p className="meta">No completed jobs yet. Run at least two jobs on the same dataset to compare them.</p>}
        {baselineId && baselineId === candidateId && <p className="meta">Choose two different jobs.</p>}
      </section>

      {ready && <section className="panel" aria-live="polite">
        {comparison.loading && !outcome && <p className="meta">Comparing...</p>}
        {comparison.error && <p className="error" role="alert">Comparison: {comparison.error}</p>}
        {outcome && !outcome.comparable && <div role="alert">
          <h2>Not comparable</h2>
          <p>These runs differ in ways that would make a side-by-side misleading. Re-run one of them with matching inputs:</p>
          <ul>{outcome.issues.map(issue => <li key={issue}>{describeIssue(issue)} <code className="meta">{issue}</code></li>)}</ul>
        </div>}
        {result && <>
          <div className="panel-head">
            <h2>Results</h2>
            <span className="pill status-completed">comparable</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Metric</th><th>Baseline<div className="meta">{baseline!.model_name}</div></th><th>Candidate<div className="meta">{candidate!.model_name}</div></th><th>Change</th></tr></thead>
              <tbody>{METRICS.map(metric => {
                const before = metric.value(result.baseline_report);
                const after = metric.value(result.candidate_report);
                return <tr key={metric.label}>
                  <td>{metric.label}</td><td>{show(before, metric.kind)}</td><td>{show(after, metric.kind)}</td>
                  <td><Delta before={before} after={after} kind={metric.kind} higherIsBetter={metric.higherIsBetter} /></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
          {(baseline!.provider === "mock" || candidate!.provider === "mock") && <p className="meta">Mock latency is simulated, not real model performance.</p>}

          {!!categories.length && <>
            <h3 className="section-title">Pass rate by category</h3>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Category</th><th>Baseline</th><th>Candidate</th><th>Change</th></tr></thead>
                <tbody>{categories.map(category => {
                  const before = categoryRate(result.baseline_report, category);
                  const after = categoryRate(result.candidate_report, category);
                  return <tr key={category}><td>{category}</td><td>{show(before, "rate")}</td><td>{show(after, "rate")}</td>
                    <td><Delta before={before} after={after} kind="rate" higherIsBetter /></td></tr>;
                })}</tbody>
              </table>
            </div>
          </>}

          <div className="compare-grid">
            <CaseList title="Regressions" items={result.case_changes.regressions} empty="No case passed fewer attempts." />
            <CaseList title="Improvements" items={result.case_changes.improvements} empty="No case passed more attempts." />
          </div>
        </>}
      </section>}
    </main>
  );
}
