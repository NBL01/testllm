"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  cancelJob,
  duplicateJob,
  getJob,
  getJobClientReport,
  getJobFailedCases,
  getJobReport,
  getJobSummary,
  getJobTraces,
  processQueue,
  queueJob,
  retryJob,
  runJob
} from "@/lib/api";
import type {
  EvaluationJob,
  FailedCase,
  JobReportPayload,
  JobSummaryResult,
  TraceRecord
} from "@/lib/types";

function statusClass(status: string): string {
  if (status === "running") return "pill status-running";
  if (status === "completed") return "pill status-completed";
  if (status === "failed") return "pill status-failed";
  if (status === "canceled") return "pill status-canceled";
  return "pill";
}

function asPct(value: number | undefined): string {
  if (typeof value !== "number") return "n/a";
  return `${(value * 100).toFixed(2)}%`;
}

export default function JobDetailPage({ params }: { params: { jobId: string } }) {
  const router = useRouter();
  const [job, setJob] = useState<EvaluationJob | null>(null);
  const [summary, setSummary] = useState<JobSummaryResult | null>(null);
  const [failedCases, setFailedCases] = useState<FailedCase[]>([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [failedOffset, setFailedOffset] = useState(0);
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [tracesTotal, setTracesTotal] = useState(0);
  const [tracesOffset, setTracesOffset] = useState(0);
  const [report, setReport] = useState<JobReportPayload | null>(null);
  const [traceCaseInput, setTraceCaseInput] = useState("");
  const [traceCaseFilter, setTraceCaseFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [processingQueue, setProcessingQueue] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const failedPageSize = 20;
  const tracesPageSize = 20;

  const canRunNow = useMemo(() => {
    if (!job) return false;
    return job.status === "draft" && !job.linked_run_id;
  }, [job]);

  const canQueue = useMemo(() => {
    if (!job) return false;
    return job.status === "draft" && !job.linked_run_id;
  }, [job]);

  const canProcessQueue = useMemo(() => {
    if (!job) return false;
    return job.status === "queued" && !job.linked_run_id;
  }, [job]);

  const canCancel = useMemo(() => {
    if (!job) return false;
    return ["draft", "queued"].includes(job.status) && !job.linked_run_id;
  }, [job]);

  async function loadAll(activeTraceCaseFilter?: string) {
    setLoading(true);
    setError("");
    try {
      const loadedJob = await getJob(params.jobId);
      setJob(loadedJob);

      if (loadedJob.linked_run_id) {
        const normalizedCaseFilter = (activeTraceCaseFilter ?? traceCaseFilter).trim();
        const [summaryData, failedData, tracesData, reportData] = await Promise.all([
          getJobSummary(params.jobId),
          getJobFailedCases(params.jobId, {
            limit: failedPageSize,
            offset: failedOffset
          }),
          getJobTraces(params.jobId, {
            limit: tracesPageSize,
            offset: tracesOffset,
            onlyFailed: true,
            testCaseId: normalizedCaseFilter || undefined
          }),
          getJobReport(params.jobId)
        ]);
        setSummary(summaryData);
        setFailedCases(failedData.items);
        setFailedTotal(failedData.total);
        setTraces(tracesData.items);
        setTracesTotal(tracesData.total);
        setReport(reportData);
      } else {
        setSummary(null);
        setFailedCases([]);
        setFailedTotal(0);
        setTraces([]);
        setTracesTotal(0);
        setReport(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job details.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.jobId, traceCaseFilter, failedOffset, tracesOffset]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      void loadAll();
    }, 3000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, params.jobId]);

  async function handleRun() {
    setRunning(true);
    setError("");
    try {
      await runJob(params.jobId);
      await loadAll(traceCaseFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run evaluation job.");
    } finally {
      setRunning(false);
    }
  }

  async function handleQueue() {
    setQueueing(true);
    setError("");
    try {
      await queueJob(params.jobId);
      await loadAll(traceCaseFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to queue evaluation job.");
    } finally {
      setQueueing(false);
    }
  }

  async function handleProcessQueue() {
    setProcessingQueue(true);
    setError("");
    try {
      await processQueue(1);
      await loadAll(traceCaseFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process queued jobs.");
    } finally {
      setProcessingQueue(false);
    }
  }

  async function handleCancel() {
    const reason = window.prompt("Optional cancel reason", "Canceled by user.") || "";
    setCanceling(true);
    setError("");
    try {
      await cancelJob(params.jobId, reason);
      await loadAll(traceCaseFilter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel evaluation job.");
    } finally {
      setCanceling(false);
    }
  }

  async function handleDuplicate() {
    setDuplicating(true);
    setError("");
    try {
      const duplicated = await duplicateJob(params.jobId);
      router.push(`/jobs/${duplicated.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to duplicate evaluation job.");
    } finally {
      setDuplicating(false);
    }
  }

  async function handleRetryQueued() {
    setRetrying(true);
    setError("");
    try {
      const retried = await retryJob(params.jobId, true);
      router.push(`/jobs/${retried.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retry evaluation job.");
    } finally {
      setRetrying(false);
    }
  }

  async function copyReport() {
    if (!report?.markdown_report) return;
    await navigator.clipboard.writeText(report.markdown_report);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  }

  function downloadReport() {
    if (!report?.markdown_report) return;
    const blob = new Blob([report.markdown_report], { type: "text/markdown;charset=utf-8" });
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    const runLabel = report.run_id || params.jobId;
    link.href = objectUrl;
    link.download = `evaluation-report-${runLabel}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objectUrl);
  }

  async function downloadClientJsonReport() {
    try {
      const payload = await getJobClientReport(params.jobId, 25);
      const body = JSON.stringify(payload, null, 2);
      const blob = new Blob([body], { type: "application/json;charset=utf-8" });
      const link = document.createElement("a");
      const objectUrl = URL.createObjectURL(blob);
      const runLabel = payload.run_id || params.jobId;
      link.href = objectUrl;
      link.download = `evaluation-client-report-${runLabel}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download client report.");
    }
  }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Evaluation Job Detail</h1>
          <p>Job ID: <code>{params.jobId}</code></p>
        </div>
        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => void loadAll()} type="button">
            Refresh
          </button>
          <button className="btn btn-secondary" disabled={duplicating} onClick={() => void handleDuplicate()} type="button">
            {duplicating ? "Duplicating..." : "Duplicate Job"}
          </button>
          <button className="btn btn-secondary" disabled={retrying} onClick={() => void handleRetryQueued()} type="button">
            {retrying ? "Retrying..." : "Retry + Queue"}
          </button>
          {canRunNow && (
            <button className="btn btn-primary" disabled={running} onClick={() => void handleRun()} type="button">
              {running ? "Running..." : "Run Evaluation"}
            </button>
          )}
          {canQueue && (
            <button className="btn btn-secondary" disabled={queueing} onClick={() => void handleQueue()} type="button">
              {queueing ? "Queueing..." : "Queue Job"}
            </button>
          )}
          {canProcessQueue && (
            <button
              className="btn btn-primary"
              disabled={processingQueue}
              onClick={() => void handleProcessQueue()}
              type="button"
            >
              {processingQueue ? "Processing..." : "Process Queue"}
            </button>
          )}
          {canCancel && (
            <button className="btn btn-secondary" disabled={canceling} onClick={() => void handleCancel()} type="button">
              {canceling ? "Canceling..." : "Cancel Job"}
            </button>
          )}
          <Link className="btn btn-secondary" href="/jobs">
            Back to Jobs
          </Link>
        </div>
      </section>

      {loading && <p className="meta">Loading job detail...</p>}
      {error && <p className="error">{error}</p>}

      {job && !loading && (
        <div className="grid">
          <section className="panel grid">
            <div className="btn-row">
              <span className={statusClass(job.status)}>{job.status}</span>
              {job.linked_run_id && <span className="pill">run: {job.linked_run_id}</span>}
              {["queued", "running"].includes(job.status) && <span className="pill">auto-refresh 3s</span>}
            </div>
            <div className="form-grid">
              <div>
                <strong>Provider / model</strong>
                <div className="meta">
                  {job.provider} / <code>{job.model_name}</code>
                </div>
              </div>
              <div>
                <strong>Dataset / mode</strong>
                <div className="meta">
                  {job.dataset_version || "auto"} / {job.evaluation_mode}
                </div>
              </div>
              <div>
                <strong>Oracle profile</strong>
                <div className="meta">{job.oracle_profile}</div>
              </div>
              <div>
                <strong>Submitted by</strong>
                <div className="meta">{job.submitted_by || "n/a"}</div>
              </div>
              <div>
                <strong>Team / client</strong>
                <div className="meta">
                  {job.team_name || "n/a"} / {job.client_name || "n/a"}
                </div>
              </div>
              <div>
                <strong>Project</strong>
                <div className="meta">{job.project_name || "n/a"}</div>
              </div>
            </div>
            {job.failure_reason && <p className="error">Failure reason: {job.failure_reason}</p>}
          </section>

          {summary && (
            <section className="panel">
              <h2>Summary Metrics</h2>
              <div className="form-grid">
                <div>
                  <strong>Total</strong>
                  <div>{summary.report.total_test_cases}</div>
                </div>
                <div>
                  <strong>Passed</strong>
                  <div>{summary.report.passed}</div>
                </div>
                <div>
                  <strong>Failed</strong>
                  <div>{summary.report.failed}</div>
                </div>
                <div>
                  <strong>Accuracy</strong>
                  <div>{asPct(summary.report.accuracy)}</div>
                </div>
                <div>
                  <strong>Avg latency</strong>
                  <div>{summary.report.average_latency_ms.toFixed(2)} ms</div>
                </div>
                <div>
                  <strong>Reliability score</strong>
                  <div>{summary.report.overall_reliability_score.toFixed(3)}</div>
                </div>
              </div>
            </section>
          )}

          <section className="panel">
            <h2>Failed Cases ({failedTotal})</h2>
            <p className="meta">
              Showing {failedTotal === 0 ? 0 : failedOffset + 1}-{failedOffset + failedCases.length} of {failedTotal}
            </p>
            <div className="btn-row" style={{ marginBottom: "0.6rem" }}>
              <button
                className="btn btn-secondary"
                disabled={loading || failedOffset === 0}
                onClick={() => setFailedOffset((prev) => Math.max(0, prev - failedPageSize))}
                type="button"
              >
                Previous
              </button>
              <button
                className="btn btn-secondary"
                disabled={loading || failedOffset + failedCases.length >= failedTotal}
                onClick={() => setFailedOffset((prev) => prev + failedPageSize)}
                type="button"
              >
                Next
              </button>
            </div>
            {failedCases.length === 0 ? (
              <p className="meta">No failed cases found for this job.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Category</th>
                      <th>Score</th>
                      <th>Error</th>
                      <th>Explanation</th>
                      <th>Trace</th>
                    </tr>
                  </thead>
                  <tbody>
                    {failedCases.map((item) => (
                      <tr key={`${item.test_case_id}:${item.attempt_index}`}>
                        <td>
                          <code>{item.test_case_id}</code>
                          <div className="meta">attempt {item.attempt_index}</div>
                        </td>
                        <td>{item.category || "n/a"}</td>
                        <td>{item.score.toFixed(3)}</td>
                        <td>{item.error_type || "n/a"}</td>
                        <td>{item.explanation || "n/a"}</td>
                        <td>
                          <button
                            className="btn btn-secondary"
                            onClick={() => {
                              setTraceCaseInput(item.test_case_id);
                              setTraceCaseFilter(item.test_case_id);
                              setTracesOffset(0);
                            }}
                            type="button"
                          >
                            View Traces
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="panel">
            <h2>Oracle Traces ({tracesTotal})</h2>
            <div className="btn-row" style={{ marginBottom: "0.6rem" }}>
              <label className="meta" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
                Filter case
                <input
                  className="input"
                  placeholder="test_case_id"
                  value={traceCaseInput}
                  onChange={(event) => setTraceCaseInput(event.target.value)}
                />
              </label>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setTraceCaseFilter(traceCaseInput.trim());
                  setTracesOffset(0);
                }}
                type="button"
              >
                Apply Filter
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setTraceCaseInput("");
                  setTraceCaseFilter("");
                  setTracesOffset(0);
                }}
                type="button"
              >
                Clear Filter
              </button>
            </div>
            {traceCaseFilter && <p className="meta">Active filter: <code>{traceCaseFilter}</code></p>}
            <p className="meta">
              Showing {tracesTotal === 0 ? 0 : tracesOffset + 1}-{tracesOffset + traces.length} of {tracesTotal}
            </p>
            <div className="btn-row" style={{ marginBottom: "0.6rem" }}>
              <button
                className="btn btn-secondary"
                disabled={loading || tracesOffset === 0}
                onClick={() => setTracesOffset((prev) => Math.max(0, prev - tracesPageSize))}
                type="button"
              >
                Previous
              </button>
              <button
                className="btn btn-secondary"
                disabled={loading || tracesOffset + traces.length >= tracesTotal}
                onClick={() => setTracesOffset((prev) => prev + tracesPageSize)}
                type="button"
              >
                Next
              </button>
            </div>
            {traces.length === 0 ? (
              <p className="meta">No traces available yet.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Trace</th>
                      <th>Prompt</th>
                      <th>Output</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traces.map((trace) => (
                      <tr key={trace.trace_id}>
                        <td>
                          <code>{trace.trace_id}</code>
                        </td>
                        <td>{trace.prompt || "n/a"}</td>
                        <td>{trace.raw_output || "n/a"}</td>
                        <td>{trace.error_type || "n/a"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="panel">
            <h2>Simple Report Export</h2>
            {report?.markdown_report ? (
              <>
                <div className="btn-row" style={{ marginBottom: "0.8rem" }}>
                  <button className="btn btn-primary" onClick={() => void copyReport()} type="button">
                    {copied ? "Copied" : "Copy Markdown Report"}
                  </button>
                  <button className="btn btn-secondary" onClick={downloadReport} type="button">
                    Download .md
                  </button>
                  <button className="btn btn-secondary" onClick={() => void downloadClientJsonReport()} type="button">
                    Download Client .json
                  </button>
                </div>
                <pre>{report.markdown_report}</pre>
              </>
            ) : (
              <p className="meta">Report will be available after job completion.</p>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
