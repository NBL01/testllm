import Link from "next/link";

export default function HomePage() {
  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>LLM Reliability Client Workflow</h1>
          <p>
            Create evaluation jobs, run them against selected providers and models, inspect failures, and export a
            simple report for stakeholders.
          </p>
        </div>
        <div className="btn-row">
          <Link className="btn btn-primary" href="/jobs/new">
            Create New Job
          </Link>
          <Link className="btn btn-secondary" href="/jobs">
            Browse Jobs
          </Link>
        </div>
      </section>
      <section className="panel">
        <p className="meta">
          This app is intentionally thin. FastAPI remains the only business-logic boundary for orchestration,
          scoring, traces, and reporting.
        </p>
      </section>
    </main>
  );
}
