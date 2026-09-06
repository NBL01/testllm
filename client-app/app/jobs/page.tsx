"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { getQueueStats, listJobs, processQueue } from "@/lib/api";
import { useRemoteResource } from "@/lib/useRemoteResource";

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
    try {
      await processQueue(10);
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
  const showingFrom = totalJobs === 0 ? 0 : jobsOffset + 1;
  const showingTo = jobsOffset + jobs.length;

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Evaluation Jobs</h1>
          <p>Track job status and open each job for summary, failed-case review, traces, and report export.</p>
        </div>
        <div className="btn-row">
          <button className="btn btn-secondary" onClick={() => void load()} type="button">
            Refresh
          </button>
          <button className="btn btn-primary" onClick={() => void handleProcessQueue()} disabled={processing} type="button">
            {processing ? "Processing Global Queue..." : "Process Global Queue (up to 10)"}
          </button>
          <Link className="btn btn-primary" href="/jobs/new">
            New Job
          </Link>
        </div>
      </section>

      <section className="panel">
        <div className="btn-row" style={{ marginBottom: "0.8rem" }}>
          <label className="meta" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            Search
            <input
              className="input"
              placeholder="project/client/team/model/job id"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </label>
          <button
            className="btn btn-secondary"
            onClick={() => { setSearchFilter(searchInput.trim()); setJobsOffset(0); }}
            type="button"
          >
            Apply Search
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              setSearchInput("");
              setSearchFilter("");
              setJobsOffset(0);
            }}
            type="button"
          >
            Clear Search
          </button>
          <label className="meta" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            Status filter
            <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setJobsOffset(0); }}>
              <option value="all">all</option>
              <option value="draft">draft</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
              <option value="canceled">canceled</option>
            </select>
          </label>
          <label className="meta" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            Sort by
            <select value={sortBy} onChange={(event) => { setSortBy(event.target.value as "created_at" | "updated_at"); setJobsOffset(0); }}>
              <option value="created_at">created_at</option>
              <option value="updated_at">updated_at</option>
            </select>
          </label>
          <label className="meta" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            Order
            <select value={sortOrder} onChange={(event) => { setSortOrder(event.target.value as "desc" | "asc"); setJobsOffset(0); }}>
              <option value="desc">desc</option>
              <option value="asc">asc</option>
            </select>
          </label>
        </div>
        {searchFilter && <p className="meta">Search: <code>{searchFilter}</code></p>}
        <p className="meta">
          Showing {showingFrom}-{showingTo} of {totalJobs}
        </p>
        <div className="btn-row" style={{ marginBottom: "0.8rem" }}>
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
        </div>
        {queueStats && (
          <p className="meta">
            Queue total: {queueStats.total} | queued: {queueStats.by_status.queued} | running:{" "}
            {queueStats.by_status.running} | draft: {queueStats.by_status.draft} | completed:{" "}
            {queueStats.by_status.completed} | failed: {queueStats.by_status.failed} | canceled:{" "}
            {queueStats.by_status.canceled}
            {(queueStats.by_status.queued > 0 || queueStats.by_status.running > 0) && " | auto-refresh 3s"}
          </p>
        )}
        {loading && <p className="meta">Loading jobs...</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {result.error && <p className="error" role="alert">Jobs: {result.error}</p>}
        {stats.error && <p className="error" role="alert">Queue statistics: {stats.error}</p>}
        {!loading && !result.error && jobs.length === 0 && <p className="meta">No jobs match this page or filter.</p>}
        {jobs.length > 0 && (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Evaluation jobs">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Provider/Model</th>
                  <th>Dataset</th>
                  <th>Metadata</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.job_id}>
                    <td>
                      <Link href={`/jobs/${job.job_id}`}>
                        <strong>{job.project_name || job.job_id}</strong>
                      </Link>
                      <div className="meta">{job.job_id}</div>
                    </td>
                    <td>
                      <span className={statusClass(job.status)}>{job.status}</span>
                    </td>
                    <td>
                      {job.provider} / <code>{job.model_name}</code>
                    </td>
                    <td>{job.dataset_version || "auto"}</td>
                    <td className="meta">
                      by {job.submitted_by || "n/a"}
                      <br />
                      {job.client_name || "internal"} / {job.team_name || "team"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
