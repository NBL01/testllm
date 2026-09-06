"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  cancelJob, duplicateJob, getJob, getJobClientReport, getJobFailedCases, getJobFailedCasesCsv,
  getJobReport, getJobSummary, getJobTraces, queueJob, retryJob, runJob
} from "@/lib/api";
import { saveDownload } from "@/lib/apiClient";
import { useRemoteResource } from "@/lib/useRemoteResource";
import type { TraceRecord } from "@/lib/types";

function asNumber(value: number | undefined, digits = 3): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not measured";
}

function asDate(value: string | null): string {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
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
        <strong>{trace.test_case_id}</strong> / attempt {trace.attempt_index}{" "}
        <span className={`pill status-${trace.is_correct ? "completed" : "failed"}`}>{trace.is_correct ? "passed" : "failed"}</span>
        {" | "}{trace.oracle_type || "Oracle unavailable"}{" | score "}{asNumber(trace.score)}
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
        <div><strong>Effective oracle configuration</strong><pre>{trace.oracle_config == null ? "Unavailable (legacy evidence)" : JSON.stringify(trace.oracle_config, null, 2)}</pre></div>
        <div><strong>Oracle details</strong><pre>{trace.oracle_details == null ? "Unavailable (legacy evidence)" : JSON.stringify(trace.oracle_details, null, 2)}</pre></div>
      </div>
    </details>
  );
}

export default function JobDetailPage({ params }: { params: { jobId: string } }) {
  // A route change owns fresh action locks, filters, and async lifetimes.
  return <JobDetail key={params.jobId} jobId={params.jobId} />;
}

function JobDetail({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [refresh, setRefresh] = useState(0);
  const [failedOffset, setFailedOffset] = useState(0);
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
  const reviewKey = job?.linked_run_id ? `${jobId}:${job.linked_run_id}` : null;
  const reviewPoll = action || poll ? 3000 : 0;
  const reviewRevision = `${reviewKey}:${job?.status}`;
  const summaryResource = useRemoteResource(reviewKey ? `${reviewRevision}:summary` : null, () => getJobSummary(jobId), refresh, reviewPoll);
  const failedResource = useRemoteResource(reviewKey ? `${reviewRevision}:failed:${failedOffset}` : null,
    () => getJobFailedCases(jobId, { limit: pageSize, offset: failedOffset }), refresh, reviewPoll);
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
    try {
      const result = await execute();
      if (mounted.current && navigate) router.push(`/jobs/${(result as { job_id: string }).job_id}`);
    } catch (error) {
      if (mounted.current) setActionError(error instanceof Error ? error.message : `${label} failed.`);
    } finally {
      // Even a rejected POST can have changed persisted state.
      if (mounted.current) { refreshAll(); setAction(""); }
      actionLock.current = false;
    }
  }

  function handleCancel() {
    if (actionLock.current || busy || !canRun) return;
    const reason = window.prompt("Optional cancel reason", "Canceled by user.");
    if (reason === null) return;
    void performAction("Canceling", () => cancelJob(jobId, reason));
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
      <section className="hero">
        <div><h1>Evaluation Job Detail</h1><p>Job ID: <code>{jobId}</code></p></div>
        <div className="btn-row">
          <button className="btn btn-secondary" onClick={refreshAll} type="button">Refresh</button>
          <button className="btn btn-secondary" disabled={busy || job?.status === "running"} onClick={() => void performAction("Duplicating", () => duplicateJob(jobId), true)} type="button">Duplicate Job</button>
          {canRetry && <button className="btn btn-secondary" disabled={busy} onClick={() => void performAction("Retrying", () => retryJob(jobId, true), true)} type="button">Retry + Queue New Job</button>}
          {canRun && <button className="btn btn-primary" disabled={busy} onClick={() => void performAction("Running", () => runJob(jobId))} type="button">{job?.status === "queued" ? "Run This Queued Job" : "Run Evaluation"}</button>}
          {canQueue && <button className="btn btn-secondary" disabled={busy} onClick={() => void performAction("Queueing", () => queueJob(jobId))} type="button">Queue Job</button>}
          {canRun && <button className="btn btn-secondary" disabled={busy} onClick={handleCancel} type="button">Cancel Job</button>}
          <Link className="btn btn-secondary" href="/jobs">Back to Jobs</Link>
        </div>
      </section>
      {action && <p className="meta" role="status">{action}... Conflicting actions are locked; persisted status continues refreshing.</p>}
      {jobResource.loading && <p className="meta" role="status">{job ? "Refreshing job status..." : "Loading job detail..."}</p>}
      <PanelError label="Job" error={jobResource.error} />
      {actionError && <p className="error" role="alert">{actionError}</p>}
      {job && <div className="grid">
        <section className="panel grid">
          <div className="btn-row">
            <span className={`pill status-${job.status}`}>{job.status}</span>
            {job.linked_run_id && <span className="pill">run: {job.linked_run_id}</span>}
            {(poll || action) && <span className="pill">auto-refresh 3s</span>}
          </div>
          <div className="form-grid">
            <div><strong>Provider / model</strong><div className="meta">{job.provider} / <code>{job.model_name}</code></div></div>
            <div><strong>Dataset / mode</strong><div className="meta"><code>{job.input_path}</code><br />{job.dataset_version || "dataset-defined"} / {job.evaluation_mode}</div></div>
            <div><strong>Oracle profile</strong><div className="meta">{job.oracle_profile} (metadata only; dataset-defined scoring)</div></div>
            <div><strong>Submitted by</strong><div className="meta">{job.submitted_by || "n/a"}</div></div>
            <div><strong>Team / client</strong><div className="meta">{job.team_name || "n/a"} / {job.client_name || "n/a"}</div></div>
            <div><strong>Project</strong><div className="meta">{job.project_name || "n/a"}</div></div>
            <div><strong>Submitted at</strong><div className="meta">{asDate(job.created_at)}</div></div>
            <div><strong>Queued at</strong><div className="meta">{asDate(job.queued_at ?? null)}</div></div>
            <div><strong>Started at</strong><div className="meta">{asDate(job.started_at)}</div></div>
            <div><strong>Completed at</strong><div className="meta">{asDate(job.completed_at)}</div></div>
            <div><strong>Last updated</strong><div className="meta">{asDate(job.updated_at)}</div></div>
            <div><strong>Run duration</strong><div className="meta">{asDuration(job.started_at, job.completed_at)}</div></div>
          </div>
          {job.source_job_id && <p className="meta">Source job: <Link href={`/jobs/${job.source_job_id}`}><u>{job.source_job_id}</u></Link></p>}
          {job.dataset_sha256 && <p className="meta">Frozen dataset SHA-256: <code>{job.dataset_sha256}</code></p>}
          {job.failure_reason && <p className="error">Failure reason: {job.failure_reason}</p>}
          {job.notes && <p className="meta">Notes: {job.notes}</p>}
        </section>

        <section className="panel">
          <h2>Summary Metrics</h2>
          <PanelError label="Summary" error={summaryResource.error} />
          {summary ? <>
            <div className="form-grid">
              <div><strong>Attempts</strong><div>{summary.report.total_test_cases}</div></div>
              <div><strong>Unique cases</strong><div>{summary.report.unique_case_count ?? "Not reported"}</div></div>
              <div><strong>Passed attempts</strong><div>{summary.report.passed}</div></div>
              <div><strong>Failed attempts</strong><div>{summary.report.failed}</div></div>
              <div><strong>Accuracy</strong><div>{asNumber(summary.report.accuracy * 100, 2)}%</div></div>
              <div><strong>Avg latency</strong><div>{asNumber(summary.report.average_latency_ms, 2)} ms</div></div>
              <div><strong>Reliability heuristic</strong><div>{asNumber(summary.report.overall_reliability_score)}</div></div>
            </div>
            <p className="meta">Metric version: <code>{summary.report.metric_version ?? "Not reported; eligibility is unknown"}</code>. A heuristic score is not a guarantee of reliability.</p>
            <p className="meta">Repeatability: {summary.report.repeated_case_count == null ? "eligibility not reported" : summary.report.repeated_case_count === 0 ? "not measured (no repeated cases)" : `${summary.report.repeated_case_count} repeated cases eligible`}.</p>
            <p className="meta">Schema compliance: {summary.report.schema_case_count == null ? "eligibility not reported" : summary.report.schema_case_count === 0 ? "not measured (no schema cases)" : `${summary.report.schema_case_count} schema cases eligible`}.</p>
            <p className="meta">Latency sources: {summary.report.latency_sources?.join(", ") || "not reported"}. {job.provider === "mock" && "Mock latency is synthetic, not real model performance."}</p>
            {!!summary.report.measurement_notes?.length && <ul className="meta">{summary.report.measurement_notes.map((note, index) => <li key={index}>{note}</li>)}</ul>}
            {job.status !== "completed" && <p className="meta">Partial evaluation: these metrics are not a completed-run result.</p>}
          </> : !summaryResource.error && <p className="meta">{summaryResource.loading ? "Loading summary..." : emptyEvidence}</p>}
        </section>

        <section className="panel">
          <h2>Failed Attempts ({failedTotal})</h2>
          <PanelError label="Failed attempts" error={failedResource.error} />
          <p className="meta">Showing {failedCases.length ? failedOffset + 1 : 0}-{failedCases.length ? failedOffset + failedCases.length : 0} of {failedTotal}</p>
          <div className="btn-row">
            <button className="btn btn-secondary" disabled={failedResource.loading || failedOffset === 0} onClick={() => setFailedOffset(value => Math.max(0, value - pageSize))} type="button">Previous</button>
            <button className="btn btn-secondary" disabled={failedResource.loading || failedOffset + pageSize >= failedTotal} onClick={() => setFailedOffset(value => value + pageSize)} type="button">Next</button>
          </div>
          {!failedCases.length ? !failedResource.error && <p className="meta">{failedResource.loading ? "Loading failed attempts..." : job.status === "completed" && failedResource.data ? "No failed attempts on this page." : emptyEvidence}</p> :
            <div className="grid evidence-list">{failedCases.map(item => <details className="evidence" key={`${item.test_case_id}:${item.attempt_index}`}>
              <summary><strong>{item.test_case_id}</strong> / attempt {item.attempt_index} | {item.error_type ?? "Incorrect answer"} | score {asNumber(item.score)}</summary>
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
        </section>

        <section className="panel" id="oracle-traces">
          <h2>Oracle Traces ({tracesTotal})</h2>
          <div className="btn-row">
            <label>Filter case<input className="input" placeholder="test_case_id" value={traceCaseInput} onChange={event => setTraceCaseInput(event.target.value)} /></label>
            <label className="checkbox-label"><input type="checkbox" checked={onlyFailedTraces} onChange={event => { setOnlyFailedTraces(event.target.checked); setTracesOffset(0); }} />Failed only</label>
            <button className="btn btn-secondary" onClick={() => { setTraceCaseFilter(traceCaseInput.trim()); setTracesOffset(0); }} type="button">Apply Filter</button>
            <button className="btn btn-secondary" onClick={() => { setTraceCaseInput(""); setTraceCaseFilter(""); setTracesOffset(0); }} type="button">Clear Filter</button>
          </div>
          <PanelError label="Traces" error={tracesResource.error} />
          {traceCaseFilter && <p className="meta">Active case: <code>{traceCaseFilter}</code>. Match the attempt index to the failed attempt above.</p>}
          <p className="meta">Showing {traces.length ? tracesOffset + 1 : 0}-{traces.length ? tracesOffset + traces.length : 0} of {tracesTotal}</p>
          <div className="btn-row">
            <button className="btn btn-secondary" disabled={tracesResource.loading || tracesOffset === 0} onClick={() => setTracesOffset(value => Math.max(0, value - pageSize))} type="button">Previous</button>
            <button className="btn btn-secondary" disabled={tracesResource.loading || tracesOffset + pageSize >= tracesTotal} onClick={() => setTracesOffset(value => value + pageSize)} type="button">Next</button>
          </div>
          {!traces.length ? !tracesResource.error && <p className="meta">{tracesResource.loading ? "Loading traces..." : tracesResource.data && job.status === "completed" ? "No traces match this filter or page." : emptyEvidence}</p> :
            <div className="grid evidence-list">{traces.map(trace => <Evidence key={trace.trace_id} trace={trace} />)}</div>}
        </section>

        <section className="panel">
          <h2>Simple Report Export</h2>
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
          {report?.markdown_report ? <pre>{report.markdown_report}</pre> : !reportResource.error && <p className="meta">{reportResource.loading ? "Loading report..." : emptyEvidence}</p>}
        </section>
      </div>}
    </main>
  );
}
