import type {
  JobClientReportPayload,
  EvaluationJob,
  EvaluationJobListResponse,
  FailedCasesResponse,
  JobOptionsResponse,
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

export function listJobs(params?: {
  status?: string;
  limit?: number;
  offset?: number;
  sortBy?: "created_at" | "updated_at";
  sortOrder?: "asc" | "desc";
}): Promise<EvaluationJobListResponse> {
  const query = new URLSearchParams();
  if (params?.status && params.status !== "all") {
    query.set("status", params.status);
  }
  if (typeof params?.limit === "number" && params.limit > 0) {
    query.set("limit", String(params.limit));
  }
  if (typeof params?.offset === "number" && params.offset >= 0) {
    query.set("offset", String(params.offset));
  }
  if (params?.sortBy) {
    query.set("sort_by", params.sortBy);
  }
  if (params?.sortOrder) {
    query.set("sort_order", params.sortOrder);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiRequest<EvaluationJobListResponse>(`/evaluation-jobs${suffix}`);
}

export function getJobOptions(): Promise<JobOptionsResponse> {
  return apiRequest<JobOptionsResponse>("/evaluation-jobs/options");
}

export function createJob(payload: Record<string, unknown>): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>("/evaluation-jobs", { method: "POST", body: payload });
}

export function duplicateJob(jobId: string): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${jobId}/duplicate`, { method: "POST" });
}

export function retryJob(jobId: string, queue = true): Promise<EvaluationJob> {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${jobId}/retry`, {
    method: "POST",
    body: { queue }
  });
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

export function getJobFailedCases(
  jobId: string,
  options?: { limit?: number; offset?: number }
): Promise<FailedCasesResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(options?.limit ?? 50));
  query.set("offset", String(options?.offset ?? 0));
  return apiRequest<FailedCasesResponse>(`/evaluation-jobs/${jobId}/failed-cases?${query.toString()}`);
}

export function getJobTraces(
  jobId: string,
  options?: { limit?: number; offset?: number; onlyFailed?: boolean; testCaseId?: string }
): Promise<TracesResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(options?.limit ?? 50));
  query.set("offset", String(options?.offset ?? 0));
  query.set("only_failed", String(options?.onlyFailed ?? true));
  const normalizedTestCaseId = (options?.testCaseId || "").trim();
  if (normalizedTestCaseId) {
    query.set("test_case_id", normalizedTestCaseId);
  }
  return apiRequest<TracesResponse>(`/evaluation-jobs/${jobId}/traces?${query.toString()}`);
}

export function getJobReport(jobId: string): Promise<JobReportPayload> {
  return apiRequest<JobReportPayload>(`/evaluation-jobs/${jobId}/report`);
}

export function getJobClientReport(jobId: string, failedCaseLimit = 20): Promise<JobClientReportPayload> {
  return apiRequest<JobClientReportPayload>(
    `/evaluation-jobs/${jobId}/client-report?failed_case_limit=${failedCaseLimit}`
  );
}
