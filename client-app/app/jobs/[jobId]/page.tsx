"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  cancelJob, duplicateJob, getJob, getJobClientReport, getJobFailedCases, getJobFailedCasesCsv,
  getJobReport, getJobSummary, getJobTraces, queueJob, retryJob, runJob
} from "@/lib/api";
import { saveDownload } from "@/lib/apiClient";
import { useRemoteResource } from "@/lib/useRemoteResource";
import { formatDate, formatMs, formatPercent } from "@/lib/format";
import { Meter, PageHeader, Pager, StatusPill } from "@/app/ui";
import type { TraceRecord } from "@/lib/types";

function asNumber(value: number | undefined, digits = 3): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not measured";
}

const asDate = formatDate;

function Bars({ rows, neutral = false }: { rows: { label: string; rate: number; detail: string }[]; neutral?: boolean }) {
  return <div className="bars">{rows.map(row => <div className="bar-row" key={row.label}>
    <span>{row.label}</span>
    <Meter rate={row.rate} tone={neutral ? "neutral" : "auto"} />
    <span className="bar-value">{row.detail}</span>
  </div>)}</div>;
}

function Kpi({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return <div className="kpi"><div className="kpi-label">{label}</div><div className="kpi-value">{value}</div>{sub && <div className="kpi-sub">{sub}</div>}</div>;
}

function asDuration(start: string | null, end: string | null): string {
  if (!start || !end) return "n/a";
  const seconds = Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  return Number.isFinite(seconds) && seconds >= 0 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : "n/a";
}

function PanelError({ label, error }: { label: string; error: string }) {
  return error ? <p className="error" role="alert">{label}: {error} Use Refresh to retry. Previously loaded data, if shown, may be stale.</p> : null;
}

function Evidence({ trace }: { trace: TraceRecord }) {
  return (
    <details className="evidence">
      <summary>
        <strong>{trace.test_case_id}</strong><span className="meta">attempt {trace.attempt_index}</span>
        <StatusPill status={trace.is_correct ? "completed" : "failed"} label={trace.is_correct ? "passed" : "failed"} />
        <span className="meta">{trace.oracle_type || "Oracle unavailable"} · score {asNumber(trace.score)}</span>
      </summary>
      <p className="meta">Trace: <code>{trace.trace_id}</code> | Run: <code>{trace.run_id}</code><br />
        Category: {trace.category ?? "n/a"} | Source: {trace.test_source ?? "n/a"} | {asDate(trace.created_at)}</p>
      <div className="form-grid">
        <div><strong>Expected answer</strong><pre>{trace.expected_answer ?? "Unavailable in this evidence record; do not infer from model output."}</pre></div>
        <div><strong>Actual / raw output</strong><pre>{trace.raw_output ?? "No output recorded"}</pre></div>
      </div>
      <strong>Normalized output</strong><pre>{trace.normalized_output ?? "Not recorded"}</pre>
      <strong>Prompt</strong><pre>{trace.prompt ?? "Not recorded"}</pre>
      <p><strong>Oracle:</strong> {trace.oracle_type ?? "Not recorded"} | <strong>Score:</strong> {asNumber(trace.score)}</p>
      <p><strong>Error:</strong> {trace.error_type ?? "None recorded"}</p>
      <p><strong>Explanation:</strong> {trace.explanation ?? "Not recorded"}</p>
      <div className="form-grid">
        <div><strong>Effective oracle configuration</strong><pre>{trace.oracle_config == null ? "Not recorded" : JSON.stringify(trace.oracle_config, null, 2)}</pre></div>
        <div><strong>Oracle details</strong><pre>{trace.oracle_details == null ? "Not recorded" : JSON.stringify(trace.oracle_details, null, 2)}</pre></div>
      </div>
    </details>
  );
}

export default function JobDetailPage() {
  const params = useParams<{ jobId: string }>();
  // A route change owns fresh action locks, filters, and async lifetimes.
  return <JobDetail key={params.jobId} jobId={params.jobId} />;
}

function JobDetail({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [refresh, setRefresh] = useState(0);
  const [failedOffset, setFailedOffset] = useState(0);
  const [altProvider, setAltProvider] = useState("ollama");
  const [altModel, setAltModel] = useState("");
  const [failedFilter, setFailedFilter] = useState<{ kind: "errorType" | "category"; value: string } | null>(null);
  const [tracesOffset, setTracesOffset] = useState(0);
  const [traceCaseInput, setTraceCaseInput] = useState("");
  const [traceCaseFilter, setTraceCaseFilter] = useState("");
  const [onlyFailedTraces, setOnlyFailedTraces] = useState(true);
  const [action, setAction] = useState("");
  const [actionError, setActionError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  const actionLock = useRef(false);
  const exportLock = useRef(false);
  const mounted = useRef(true);
  const [poll, setPoll] = useState(false);
  const pageSize = 20;

  const jobResource = useRemoteResource(jobId, () => getJob(jobId), refresh, action || poll ? 3000 : 0);
  const job = jobResource.data;
  // Results are written when a run ends, so there is no evidence to fetch while it executes.
  const reviewKey = job?.linked_run_id && !["queued", "running"].includes(job.status) ? `${jobId}:${job.linked_run_id}` : null;
  const reviewPoll = action || poll ? 3000 : 0;
  const reviewRevision = `${reviewKey}:${job?.status}`;
  const summaryResource = useRemoteResource(reviewKey ? `${reviewRevision}:summary` : null, () => getJobSummary(jobId), refresh, reviewPoll);
  const failedResource = useRemoteResource(reviewKey ? `${reviewRevision}:failed:${failedOffset}:${failedFilter?.kind}:${failedFilter?.value}` : null,
    () => getJobFailedCases(jobId, { limit: pageSize, offset: failedOffset, [failedFilter?.kind ?? "errorType"]: failedFilter?.value }), refresh, reviewPoll);
  const tracesResource = useRemoteResource(reviewKey ? JSON.stringify([reviewRevision, tracesOffset, onlyFailedTraces, traceCaseFilter]) : null,
    () => getJobTraces(jobId, { limit: pageSize, offset: tracesOffset, onlyFailed: onlyFailedTraces, testCaseId: traceCaseFilter }), refresh, reviewPoll);
  const reportResource = useRemoteResource(reviewKey ? `${reviewRevision}:report` : null, () => getJobReport(jobId), refresh, reviewPoll);
  const summary = summaryResource.data;
  const failedCases = failedResource.data?.items || [];
  const failedTotal = failedResource.data?.total || 0;
  const traces = tracesResource.data?.items || [];
  const tracesTotal = tracesResource.data?.total || 0;
  const report = reportResource.data;
  const canRun = !!job && ["draft", "queued"].includes(job.status) && !job.linked_run_id;
  const canQueue = job?.status === "draft" && !job.linked_run_id;
  const canRetry = !!job && ["failed", "canceled", "completed"].includes(job.status);
  const canStop = job?.status === "running" && !!job.progress_total && !job.stop_requested;
  const busy = !!action || !job || !!jobResource.error || jobResource.loading;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => { setPoll(!!job && ["queued", "running"].includes(job.status)); }, [job?.status]);

  function refreshAll() { setRefresh(value => value + 1); }

  async function performAction(label: string, execute: () => Promise<unknown>, navigate = false) {
    if (actionLock.current || busy) return;
    actionLock.current = true;
    setAction(label);
    setActionError("");
    let navigating = false;
    try {
      const result = await execute();
      if (mounted.current && navigate) {
        router.push(`/jobs/${(result as { job_id: string }).job_id}`);
        navigating = true;
      }
    } catch (error) {
      if (mounted.current) setActionError(error instanceof Error ? error.message : `${label} failed.`);
    } finally {
      // Even a rejected POST can have changed persisted state.
      if (mounted.current) { refreshAll(); if (!navigating) setAction(""); }
      if (!navigating) actionLock.current = false;
    }
  }

  function handleCancel() {
    if (actionLock.current || busy || !(canRun || canStop)) return;
    const reason = canStop ? window.prompt("Optional reason for stopping this run", "Stopped by user.")
      : window.prompt("Optional cancel reason", "Canceled by user.");
    if (reason === null) return;
    void performAction(canStop ? "Stopping" : "Canceling", () => cancelJob(jobId, reason));
  }

  async function exportFile(execute: () => Promise<void>) {
    if (exportLock.current) return;
    exportLock.current = true;
    setExporting(true);
    setExportError("");
    setCopied(false);
    try { await execute(); }
    catch (error) {
      if (mounted.current) setExportError(`${error instanceof Error ? error.message : "Export failed"}. You can retry the download or select the report text below.`);
    } finally {
      exportLock.current = false;
      if (mounted.current) setExporting(false);
    }
  }

  const emptyEvidence = job?.status === "draft" ? "This draft has not run; no evidence has been measured."
    : job?.status === "queued" ? "This job is queued and has not produced evidence yet."
    : job?.status === "running" || action === "Running" ? "Evaluation is in progress. Evidence may be partial; this view refreshes automatically."
    : job?.status === "failed" ? "The evaluation failed. No evidence is available in this view; see the persisted failure reason above."
    : job?.status === "canceled" ? "The job was canceled before evaluation."
    : "No matching evidence was recorded.";

  return (
    <main className="page">
      <PageHeader title={job?.project_name || "Evaluation Job"} subtitle={<>Job ID: <code>{jobId}</code></>}>
          <button className="btn btn-secondary" onClick={refreshAll} type="button">Refresh</button>
          <button className="btn btn-secondary" disabled={busy || job?.status === "running"} onClick={() => void performAction("Duplicating", () => duplicateJob(jobId), true)} type="button">Duplicate Job</button>
          {canRetry && <button className="btn btn-secondary" disabled={busy} onClick={() => void performAction("Retrying", () => retryJob(jobId, true), true)} type="button">Retry + Queue New Job</button>}
          {canRun && <button className="btn btn-primary" disabled={busy} onClick={() => void performAction("Running", () => runJob(jobId))} type="button">{job?.status === "queued" ? "Run This Queued Job" : "Run Evaluation"}</button>}
          {canQueue && <button className="btn btn-secondary" disabled={busy} onClick={() => void performAction("Queueing", () => queueJob(jobId))} type="button">Queue Job</button>}
          {canRun && <button className="btn btn-secondary" disabled={busy} onClick={handleCancel} type="button">Cancel Job</button>}
          {canStop && <button className="btn btn-danger" disabled={busy} onClick={handleCancel} type="button">Stop Run</button>}
          {job?.status === "completed" && job.source_job_id && <Link className="btn btn-secondary" href={`/compare?baseline=${job.source_job_id}&candidate=${jobId}`}>Compare with Source</Link>}
          {job?.status === "completed" && <Link className="btn btn-secondary" href={`/compare?baseline=${jobId}`}>Compare</Link>}
          <Link className="btn btn-secondary" href="/jobs">Back to Jobs</Link>
      </PageHeader>
      {action && <p className="meta" role="status">{action}... Conflicting actions are locked; persisted status continues refreshing.</p>}
      {jobResource.loading && <p className="meta" role="status">{job ? "Refreshing job status..." : "Loading job detail..."}</p>}
      <PanelError label="Job" error={jobResource.error} />
      {actionError && <p className="error" role="alert">{actionError}</p>}
      {job && <div className="grid">
        <section className="panel grid">
          <h2>Job Overview</h2>
          <div className="btn-row">
            <StatusPill status={job.status} />
            {job.linked_run_id && <span className="pill">run: {job.linked_run_id}</span>}
            {(poll || action) && <span className="pill">auto-refresh 3s</span>}
          </div>
          {job.status === "running" && !!job.progress_total && <div>
            <p className="meta progress-label">
              {job.stop_requested ? "Stopping after the current attempt. " : ""}
              {job.progress_done ?? 0} of {job.progress_total} attempts ({formatPercent((job.progress_done ?? 0) / job.progress_total)})
            </p>
            <Meter tone="brand" rate={(job.progress_done ?? 0) / job.progress_total}
              progress={{ label: "Run progress", now: job.progress_done ?? 0, max: job.progress_total }} />
          </div>}
          <div className="form-grid">
            <div><strong>Provider / model</strong><div className="meta">{job.provider} / <code>{job.model_name}</code></div></div>
            <div><strong>Dataset / mode</strong><div className="meta"><code>{job.input_path}</code><br />{job.dataset_version || "dataset-defined"} / {job.evaluation_mode}</div></div>
            <div><strong>Run settings</strong><div className="meta">{job.repeat_count}x repeat · temp {job.temperature} · {job.max_output_tokens} tokens{job.limit ? ` · first ${job.limit} cases` : ""}</div></div>
            <div><strong>Owner</strong><div className="meta">{[job.submitted_by, job.team_name, job.client_name].filter(Boolean).join(" · ") || "Not recorded"}</div></div>
          </div>
          <p className="meta">Submitted {asDate(job.created_at)}{job.queued_at && ` · queued ${asDate(job.queued_at)}`}{job.started_at && ` · started ${asDate(job.started_at)}`}{job.completed_at && ` · finished ${asDate(job.completed_at)} (${asDuration(job.started_at, job.completed_at)})`}. Oracle profile <code>{job.oracle_profile}</code> is a label; scoring is dataset-defined.</p>
          {job.source_job_id && <p className="meta">Source job: <Link href={`/jobs/${job.source_job_id}`}><u>{job.source_job_id}</u></Link></p>}
          {job.dataset_sha256 && <p className="meta">Frozen dataset SHA-256: <code>{job.dataset_sha256}</code></p>}
          {job.failure_reason && <p className="error" role="alert">Failure reason: {job.failure_reason}</p>}
          {job.notes && <p className="meta">Notes: {job.notes}</p>}
          <details className="notes">
            <summary>Run the same evaluation with another model</summary>
            <div className="toolbar">
              <label>Provider
                <select value={altProvider} onChange={event => setAltProvider(event.target.value)}>
                  {["mock", "ollama", "openai_compatible"].map(provider => <option key={provider} value={provider}>{provider}</option>)}
                </select>
              </label>
              <label className="search">Model
                <input className="input" value={altModel} placeholder={altProvider === "mock" ? "mock-baseline, mock-noisy or mock-failing" : "e.g. llama3.2:1b"}
                  onChange={event => setAltModel(event.target.value)} />
              </label>
              <button className="btn btn-secondary" type="button" disabled={busy || !altModel.trim()}
                onClick={() => void performAction("Duplicating", () => duplicateJob(jobId, { provider: altProvider, model_name: altModel.trim() }), true)}>
                Create Comparable Draft
              </button>
            </div>
            <p className="meta">Copies the frozen dataset snapshot and every setting; only the model changes, so the two runs stay comparable. Run it, then use Compare with Source.</p>
          </details>
        </section>

        <section className="panel">
          <h2>Summary Metrics</h2>
          <PanelError label="Summary" error={summaryResource.error} />
          {summary ? <>
            <div className="kpi-grid">
              <Kpi label="Pass rate" value={`${asNumber(summary.report.accuracy * 100, 1)}%`} sub={`${summary.report.passed} of ${summary.report.total_test_cases} attempts`} />
              <Kpi label={summary.report.repeat_k ? `pass^${summary.report.repeat_k}` : "pass^k"}
                value={summary.report.pass_hat_k == null ? "N/A" : formatPercent(summary.report.pass_hat_k, 1)}
                sub={summary.report.pass_hat_k == null ? "needs 2+ attempts per case" : "cases passing every attempt"} />
              <Kpi label={summary.report.repeat_k ? `pass@${summary.report.repeat_k}` : "pass@k"}
                value={summary.report.pass_at_k == null ? "N/A" : formatPercent(summary.report.pass_at_k, 1)}
                sub={summary.report.pass_at_k == null ? "needs 2+ attempts per case" : "cases passing at least once"} />
              {summary.report.schema_pass_rate != null && <Kpi label="Schema pass rate" value={formatPercent(summary.report.schema_pass_rate, 1)} sub={`${summary.report.schema_attempt_count ?? 0} json_schema attempts`} />}
              <Kpi label="Unique cases" value={summary.report.unique_test_cases ?? "Not reported"} sub={`${summary.report.total_test_cases} attempts`} />
              <Kpi label="Latency p50" value={formatMs(summary.report.p50_latency_ms)}
                sub={`p95 ${formatMs(summary.report.p95_latency_ms)} · ${job.provider === "mock" ? "simulated (mock)" : `mean ${formatMs(summary.report.average_latency_ms)}`}`} />
            </div>
            {!!summary.report.category_reports?.length && <>
              <h3 className="section-title">Pass Rate by Category</h3>
              <Bars rows={[...summary.report.category_reports].sort((a, b) => a.accuracy - b.accuracy).map(item => ({
                label: item.category, rate: item.accuracy, detail: `${formatPercent(item.accuracy)} · ${item.passed}/${item.total_test_cases}`
              }))} />
            </>}
            {!!Object.keys(summary.report.error_distribution ?? {}).length && <>
              <h3 className="section-title">Failure Types</h3>
              <Bars neutral rows={Object.entries(summary.report.error_distribution ?? {}).sort((a, b) => b[1] - a[1]).map(([type, count]) => ({
                label: type, rate: summary.report.failed ? count / summary.report.failed : 0, detail: `${count} attempt${count === 1 ? "" : "s"}`
              }))} />
            </>}
            <details className="notes">
              <summary>How these metrics are computed</summary>
              <p className="meta">pass^k counts cases whose every one of k attempts passed (production consistency); pass@k counts cases with at least one pass (capability ceiling). Both are N/A unless every case has the same k of 2 or more attempts.</p>
              <p className="meta">Latency sources: {Object.entries(summary.report.latency_sources ?? {}).map(([source, count]) => `${source}: ${count}`).join(", ") || "not reported"} (attempt counts).</p>
              {!!summary.report.measurement_notes?.length && <ul className="meta">{summary.report.measurement_notes.map((note, index) => <li key={index}>{note}</li>)}</ul>}
            </details>
            {job.status !== "completed" && <p className="meta">Partial evaluation: these metrics are not a completed-run result.</p>}
          </> : !summaryResource.error && <p className="meta">{summaryResource.loading ? "Loading summary..." : emptyEvidence}</p>}
        </section>

        <section className="panel">
          <h2>Failed Attempts ({failedTotal})</h2>
          <PanelError label="Failed attempts" error={failedResource.error} />
          {summary && (() => {
            const options = [
              ...Object.entries(summary.report.error_distribution ?? {}).map(([value, count]) => ({ kind: "errorType" as const, value, count })),
              ...(summary.report.category_reports ?? []).filter(item => item.failed > 0)
                .map(item => ({ kind: "category" as const, value: item.category, count: item.failed }))
            ];
            const pick = (next: typeof failedFilter) => { setFailedFilter(next); setFailedOffset(0); };
            return options.length > 1 && <div className="chips" role="group" aria-label="Filter failed attempts">
              <button className="chip" type="button" aria-pressed={!failedFilter} onClick={() => pick(null)}>All<span className="chip-count">{summary.report.failed}</span></button>
              {options.map(option => {
                const active = failedFilter?.kind === option.kind && failedFilter.value === option.value;
                return <button key={`${option.kind}:${option.value}`} className="chip" type="button" aria-pressed={active}
                  onClick={() => pick(active ? null : { kind: option.kind, value: option.value })}>
                  {option.kind === "category" ? `category: ${option.value}` : option.value}<span className="chip-count">{option.count}</span>
                </button>;
              })}
            </div>;
          })()}
          {!failedCases.length ? !failedResource.error && <p className="meta">{failedResource.loading ? "Loading failed attempts..." : job.status === "completed" && failedResource.data ? "No failed attempts on this page." : emptyEvidence}</p> :
            <div className="evidence-list">{failedCases.map(item => <details className="evidence" key={`${item.test_case_id}:${item.attempt_index}`}>
              <summary><strong>{item.test_case_id}</strong><span className="meta">attempt {item.attempt_index} · {item.category ?? "uncategorized"}</span>
                <StatusPill status="failed" label={item.error_type ?? "Incorrect answer"} /><span className="meta">score {asNumber(item.score)}</span></summary>
              <p className="meta">Category: {item.category ?? "n/a"} | Source: {item.test_source ?? "n/a"} | Oracle: {item.oracle_type ?? "n/a"} | Latency: {asNumber(item.latency_ms, 2)} ms</p>
              <div className="form-grid">
                <div><strong>Expected answer</strong><pre>{item.expected_answer ?? "Not recorded"}</pre></div>
                <div><strong>Actual answer</strong><pre>{item.actual_answer ?? "No output recorded"}</pre></div>
              </div>
              <p><strong>Explanation:</strong> {item.explanation ?? "Not recorded"}</p>
              <a className="btn btn-secondary" href="#oracle-traces" onClick={() => {
                setTraceCaseInput(item.test_case_id); setTraceCaseFilter(item.test_case_id); setTracesOffset(0); setOnlyFailedTraces(false);
              }}>View Case Traces (attempt {item.attempt_index})</a>
            </details>)}</div>}
          <Pager offset={failedOffset} count={failedCases.length} total={failedTotal} pageSize={pageSize} loading={failedResource.loading} onPage={setFailedOffset} />
        </section>

        <section className="panel" id="oracle-traces">
          <h2>Oracle Traces ({tracesTotal})</h2>
          <div className="btn-row">
            <label>Filter case<input className="input" placeholder="test_case_id" value={traceCaseInput} onChange={event => setTraceCaseInput(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { setTraceCaseFilter(traceCaseInput.trim()); setTracesOffset(0); } }} /></label>
            <label className="checkbox-label"><input type="checkbox" checked={onlyFailedTraces} onChange={event => { setOnlyFailedTraces(event.target.checked); setTracesOffset(0); }} />Failed only</label>
            <button className="btn btn-secondary" onClick={() => { setTraceCaseFilter(traceCaseInput.trim()); setTracesOffset(0); }} type="button">Apply Filter</button>
            <button className="btn btn-secondary" onClick={() => { setTraceCaseInput(""); setTraceCaseFilter(""); setTracesOffset(0); }} type="button">Clear Filter</button>
          </div>
          <PanelError label="Traces" error={tracesResource.error} />
          {traceCaseFilter && <p className="meta">Active case: <code>{traceCaseFilter}</code>. Match the attempt index to the failed attempt above.</p>}
          {!traces.length ? !tracesResource.error && <p className="meta">{tracesResource.loading ? "Loading traces..." : tracesResource.data && job.status === "completed" ? "No traces match this filter or page." : emptyEvidence}</p> :
            <div className="evidence-list">{traces.map(trace => <Evidence key={trace.trace_id} trace={trace} />)}</div>}
          <Pager offset={tracesOffset} count={traces.length} total={tracesTotal} pageSize={pageSize} loading={tracesResource.loading} onPage={setTracesOffset} />
        </section>

        <section className="panel">
          <h2>Reports and Exports</h2>
          <PanelError label="Markdown report" error={reportResource.error} />
          {exportError && <p className="error" role="alert">{exportError}</p>}
          {copied && <p className="success" role="status">Markdown copied.</p>}
          <div className="btn-row">
            <button className="btn btn-primary" disabled={exporting || !report?.markdown_report} onClick={() => void exportFile(async () => {
              if (!report) return;
              await navigator.clipboard.writeText(report.markdown_report);
              if (mounted.current) setCopied(true);
            })} type="button">Copy Markdown Report</button>
            <button className="btn btn-secondary" disabled={exporting || !report?.markdown_report} onClick={() => void exportFile(async () => {
              if (report) saveDownload(new Blob([report.markdown_report], { type: "text/markdown;charset=utf-8" }), `evaluation-report-${jobId}.md`);
            })} type="button">Download .md</button>
            <button className="btn btn-secondary" disabled={exporting || !reviewKey} onClick={() => void exportFile(async () => {
              const payload = await getJobClientReport(jobId, 25);
              if (mounted.current) saveDownload(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" }), `evaluation-client-report-${jobId}.json`);
            })} type="button">Download Client .json (sample)</button>
            <button className="btn btn-secondary" disabled={exporting || !reviewKey} onClick={() => void exportFile(async () => {
              const blob = await getJobFailedCasesCsv(jobId);
              if (mounted.current) saveDownload(blob, `evaluation-failed-cases-${jobId}.csv`);
            })} type="button">Download All Failed Attempts .csv</button>
          </div>
          <p className="meta">CSV is the complete backend export. JSON includes a labeled sample of up to 25 failed attempts and the total count. Running evaluations can only export evidence recorded so far.</p>
          {exporting && <p className="meta" role="status">Preparing export...</p>}
          {report?.markdown_report ? <details className="notes"><summary>Preview Markdown report</summary><pre>{report.markdown_report}</pre></details> : !reportResource.error && <p className="meta">{reportResource.loading ? "Loading report..." : emptyEvidence}</p>}
        </section>
      </div>}
    </main>
  );
}
