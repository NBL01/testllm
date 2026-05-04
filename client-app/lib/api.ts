import type {
  EvaluationJob,
  EvaluationJobListResponse,
  FailedCasesResponse,
  JobReportPayload,
  JobRunResult,
  JobSummaryResult,
  QueueProcessResult,
  QueueStatsResult,
  TracesResponse
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

type ApiRequestOptions = {
  method?: "GET" | "POST";
  body?: Record<string, unknown>;
};

async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json"
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store"
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = typeof payload?.detail === "string" ? payload.detail : detail;
    } catch {
      detail = response.statusText;
    }
    throw new Error(`${response.status}: ${detail}`);
  }

  return (await response.json()) as T;
}

export function listJobs(): Promise<EvaluationJobListResponse> {
  return apiRequest<EvaluationJobListResponse>("/evaluation-jobs");
}

export function createJob(payload: Record<string, unknown>): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>("/evaluation-jobs", { method: "POST", body: payload });
}

export function getJob(jobId: string): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${jobId}`);
}

export function runJob(jobId: string): Promise<JobRunResult> {
  return apiRequest<JobRunResult>(`/evaluation-jobs/${jobId}/run`, { method: "POST" });
}

export function queueJob(jobId: string): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${jobId}/queue`, { method: "POST" });
}

export function cancelJob(jobId: string, reason = ""): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${jobId}/cancel`, {
    method: "POST",
    body: { reason }
  });
}

export function processQueue(maxJobs = 10): Promise<QueueProcessResult> {
  return apiRequest<QueueProcessResult>(`/evaluation-jobs/process-queue?max_jobs=${maxJobs}`, {
    method: "POST"
  });
}

export function getQueueStats(): Promise<QueueStatsResult> {
  return apiRequest<QueueStatsResult>("/evaluation-jobs/queue/stats");
}

export function getJobSummary(jobId: string): Promise<JobSummaryResult> {
  return apiRequest<JobSummaryResult>(`/evaluation-jobs/${jobId}/summary`);
}

export function getJobFailedCases(jobId: string, limit = 50): Promise<FailedCasesResponse> {
  return apiRequest<FailedCasesResponse>(`/evaluation-jobs/${jobId}/failed-cases?limit=${limit}`);
}

export function getJobTraces(jobId: string, limit = 50): Promise<TracesResponse> {
  return apiRequest<TracesResponse>(`/evaluation-jobs/${jobId}/traces?limit=${limit}&only_failed=true`);
}

export function getJobReport(jobId: string): Promise<JobReportPayload> {
  return apiRequest<JobReportPayload>(`/evaluation-jobs/${jobId}/report`);
}
