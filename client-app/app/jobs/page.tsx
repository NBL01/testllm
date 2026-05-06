"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getQueueStats, listJobs, processQueue } from "@/lib/api";
import type { EvaluationJob, QueueStatsResult } from "@/lib/types";

function statusClass(status: string): string {
  if (status === "running") return "pill status-running";
  if (status === "completed") return "pill status-completed";
  if (status === "failed") return "pill status-failed";
  if (status === "canceled") return "pill status-canceled";
  return "pill";
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<EvaluationJob[]>([]);
  const [queueStats, setQueueStats] = useState<QueueStatsResult | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [totalJobs, setTotalJobs] = useState(0);
  const [jobsOffset, setJobsOffset] = useState(0);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const jobsPageSize = 25;

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [response, stats] = await Promise.all([
        listJobs({ status: statusFilter, limit: jobsPageSize, offset: jobsOffset }),
        getQueueStats()
      ]);
      setJobs(response.items);
      setTotalJobs(response.total);
      setQueueStats(stats);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs.");
    } finally {
      setLoading(false);
    }
  }

  async function handleProcessQueue() {
    setProcessing(true);
    setError("");
    try {
      await processQueue(10);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process queue.");
    } finally {
      setProcessing(false);
    }
  }

  useEffect(() => {
    void load();
  }, [statusFilter, jobsOffset]);

  useEffect(() => {
    setJobsOffset(0);
  }, [statusFilter]);

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
            {processing ? "Processing Queue..." : "Process Queue"}
          </button>
          <Link className="btn btn-primary" href="/jobs/new">
            New Job
          </Link>
        </div>
      </section>

      <section className="panel">
        <div className="btn-row" style={{ marginBottom: "0.8rem" }}>
          <label className="meta" style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
            Status filter
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">all</option>
              <option value="draft">draft</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
              <option value="canceled">canceled</option>
            </select>
          </label>
        </div>
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
          </p>
        )}
        {loading && <p className="meta">Loading jobs...</p>}
        {error && <p className="error">{error}</p>}
        {!loading && !error && jobs.length === 0 && <p className="meta">No jobs found yet.</p>}
        {!loading && !error && jobs.length > 0 && (
          <div className="table-wrap">
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
