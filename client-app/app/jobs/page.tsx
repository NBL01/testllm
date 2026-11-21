"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { getQueueStats, listJobs, processQueue } from "@/lib/api";
import { useRemoteResource } from "@/lib/useRemoteResource";
import { formatDate, formatPercent, rateTone } from "@/lib/format";
import type { QueueProcessResult } from "@/lib/types";

const STATUSES = ["draft", "queued", "running", "completed", "failed", "canceled"] as const;
const SORTS = { "created_at:desc": "Newest first", "created_at:asc": "Oldest first", "updated_at:desc": "Recently updated" };

function statusClass(status: string): string {
  if (status === "running") return "pill status-running";
  if (status === "completed") return "pill status-completed";
  if (status === "failed") return "pill status-failed";
  if (status === "canceled") return "pill status-canceled";
  return "pill";
}

export default function JobsPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchInput, setSearchInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [sortBy, setSortBy] = useState<"created_at" | "updated_at">("created_at");
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");
  const [jobsOffset, setJobsOffset] = useState(0);
  const [error, setError] = useState<string>("");
  const [processing, setProcessing] = useState(false);
  const [queueOutcome, setQueueOutcome] = useState<QueueProcessResult | null>(null);
  const processLock = useRef(false);
  const mounted = useRef(true);
  const [refresh, setRefresh] = useState(0);
  const jobsPageSize = 25;
  const stats = useRemoteResource("queue-stats", getQueueStats, refresh, 3000);
  const queueStats = stats.data;
  const shouldPoll = processing || !!queueStats?.by_status.queued || !!queueStats?.by_status.running;
  const result = useRemoteResource(JSON.stringify([statusFilter, jobsOffset, sortBy, sortOrder, searchFilter]),
    () => listJobs({ status: statusFilter, limit: jobsPageSize, offset: jobsOffset, sortBy, sortOrder, searchQuery: searchFilter }),
    refresh, shouldPoll ? 3000 : 0);
  const jobs = result.data?.items || [];
  const totalJobs = result.data?.total || 0;
  const loading = result.loading;
  function load() { setRefresh(value => value + 1); }

  async function handleProcessQueue() {
    if (processLock.current) return;
    processLock.current = true;
    setProcessing(true);
    setError("");
    setQueueOutcome(null);
    try {
      const outcome = await processQueue(10);
      if (mounted.current) setQueueOutcome(outcome);
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : "Failed to process queue.");
    } finally {
      processLock.current = false;
      if (mounted.current) { setProcessing(false); load(); }
    }
  }

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const canPrevious = jobsOffset > 0;
  const canNext = jobsOffset + jobs.length < totalJobs;
  const showingFrom = jobs.length ? jobsOffset + 1 : 0;
  const showingTo = jobs.length ? jobsOffset + jobs.length : 0;

  const queued = queueStats?.by_status.queued ?? 0;
  const filtered = statusFilter !== "all" || !!searchFilter;
  function applySearch() { setSearchFilter(searchInput.trim()); setJobsOffset(0); }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Evaluation Jobs</h1>
          <p>Track runs, open a job to review failed attempts and traces, and export reports.</p>
        </div>
        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => void load()} type="button">
            Refresh
          </button>
          <button className="btn btn-secondary" onClick={() => void handleProcessQueue()} disabled={processing || (!!queueStats && queued === 0)} type="button">
            {processing ? "Running queued jobs..." : `Run queued jobs (${queued})`}
          </button>
          <Link className="btn btn-primary" href="/jobs/new">
            New Job
          </Link>
        </div>
      </section>

      <section className="panel">
        {queueOutcome && <div role="status">
          <p className="meta">Queue processing finished: {queueOutcome.processed_count} attempted, {queueOutcome.results.length} succeeded,
            {" "}{queueOutcome.failures?.length || 0} failed.</p>
          {!!queueOutcome.failures?.length && <ul className="error">{queueOutcome.failures.map((failure, index) => <li key={`${failure.job_id}:${index}`}>
            <Link href={`/jobs/${failure.job_id}`}><u>{failure.job_id}</u></Link>: {failure.error || failure.failure_reason || failure.detail || "Evaluation failed"}
          </li>)}</ul>}
        </div>}
        <div className="chips" role="group" aria-label="Filter by status">
          {(["all", ...STATUSES] as const).map(status => (
            <button key={status} className="chip" aria-pressed={statusFilter === status} type="button"
              onClick={() => { setStatusFilter(status); setJobsOffset(0); }}>
              {status === "all" ? "All" : status[0].toUpperCase() + status.slice(1)}
              {queueStats && <span className="chip-count">{status === "all" ? queueStats.total : queueStats.by_status[status] ?? 0}</span>}
            </button>
          ))}
        </div>
        <div className="toolbar">
          <label className="search">
            <span className="sr-only">Search</span>
            <input
              className="input"
              type="search"
              placeholder="Search project, client, team, model or job ID"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") applySearch(); }}
            />
          </label>
          <button className="btn btn-secondary" onClick={applySearch} type="button">
            Apply Search
          </button>
          {searchFilter && <button
            className="btn btn-secondary"
            onClick={() => {
              setSearchInput("");
              setSearchFilter("");
              setJobsOffset(0);
            }}
            type="button"
          >
            Clear Search
          </button>}
          <label>
            <span className="sr-only">Sort</span>
            <select value={`${sortBy}:${sortOrder}`} onChange={(event) => {
              const [by, order] = event.target.value.split(":") as ["created_at" | "updated_at", "desc" | "asc"];
              setSortBy(by); setSortOrder(order); setJobsOffset(0);
            }}>
              {Object.entries(SORTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        {searchFilter && <p className="meta">Search: <code>{searchFilter}</code></p>}
        {(queued > 0 || !!queueStats?.by_status.running) && <p className="meta" role="status">Jobs are queued or running; this list refreshes every 3 seconds.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {result.error && <p className="error" role="alert">Jobs: {result.error}</p>}
        {stats.error && <p className="error" role="alert">Queue statistics: {stats.error}</p>}
        {loading && !jobs.length && <p className="meta">Loading jobs...</p>}
        {!loading && !result.error && jobs.length === 0 && <div className="empty">
          {filtered ? <p>No jobs match these filters.</p> : <>
            <p>No evaluation jobs yet.</p>
            <Link className="btn btn-primary" href="/jobs/new">Create your first job</Link>
          </>}
        </div>}
        {jobs.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Evaluation jobs">
            <table className="job-table">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Model</th>
                  <th className="col-optional">Dataset</th>
                  <th>Result</th>
                  <th className="col-optional">Owner</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const rate = job.attempts ? (job.passed_attempts ?? 0) / job.attempts : null;
                  const owner = [job.submitted_by, job.client_name, job.team_name].filter(Boolean).join(" · ");
                  return (
                    <tr key={job.job_id}>
                      <td>
                        <Link href={`/jobs/${job.job_id}`}>
                          <strong>{job.project_name || `Job ${job.job_id.slice(0, 8)}`}</strong>
                        </Link>
                        <div className="meta"><code>{job.job_id.slice(0, 8)}</code> · {formatDate(job.created_at)}</div>
                      </td>
                      <td>
                        <span className={statusClass(job.status)}>{job.status}</span>
                      </td>
                      <td>
                        <code>{job.model_name}</code>
                        <div className="meta">{job.provider}</div>
                      </td>
                      <td className="col-optional">
                        {job.dataset_version || "auto"}
                        <div className="meta">{job.evaluation_mode}</div>
                      </td>
                      <td>
                        {rate === null ? <span className="meta">{job.linked_run_id ? "No attempts" : "Not run"}</span> : <>
                          <strong>{formatPercent(rate)}</strong>{" "}
                          <span className="meta">{job.passed_attempts}/{job.attempts} passed</span>
                          <div className="bar-track mini-bar" aria-hidden="true"><div className={rateTone(rate)} style={{ width: `${rate * 100}%` }} /></div>
                        </>}
                      </td>
                      <td className="meta col-optional">{owner || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {totalJobs > 0 && <div className="pager">
          <p className="meta">Showing {showingFrom}-{showingTo} of {totalJobs}</p>
          {totalJobs > jobsPageSize && <div className="btn-row">
            <button
              className="btn btn-secondary"
              disabled={!canPrevious || loading}
              onClick={() => setJobsOffset((prev) => Math.max(0, prev - jobsPageSize))}
              type="button"
            >
              Previous
            </button>
            <button
              className="btn btn-secondary"
              disabled={!canNext || loading}
              onClick={() => setJobsOffset((prev) => prev + jobsPageSize)}
              type="button"
            >
              Next
            </button>
          </div>}
        </div>}
      </section>
    </main>
  );
}
