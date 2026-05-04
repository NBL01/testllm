"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listJobs } from "@/lib/api";
import type { EvaluationJob } from "@/lib/types";

function statusClass(status: string): string {
  if (status === "running") return "pill status-running";
  if (status === "completed") return "pill status-completed";
  if (status === "failed") return "pill status-failed";
  return "pill";
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<EvaluationJob[]>([]);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await listJobs();
      setJobs(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

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
          <Link className="btn btn-primary" href="/jobs/new">
            New Job
          </Link>
        </div>
      </section>

      <section className="panel">
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
