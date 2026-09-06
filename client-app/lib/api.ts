import type {
  JobClientReportPayload,
  EvaluationJob,
  EvaluationJobListResponse,
  FailedCasesResponse,
  HealthResponse,
  JobOptionsResponse,
  JobReportPayload,
  JobRunResult,
  JobSummaryResult,
  ModelsResponse,
  QueueProcessResult,
  QueueStatsResult,
  TracesResponse
} from "./types";
import { requestDownload, requestJson } from "./apiClient";
import { validateJobOptions } from "./jobForm";

export function getJobFailedCasesCsv(jobId: string): Promise<Blob> {
  return requestDownload(`/evaluation-jobs/${encodeURIComponent(jobId)}/failed-cases.csv`);
}

export function listJobs(params?: {
  status?: string;
  limit?: number;
  offset?: number;
  sortBy?: "created_at" | "updated_at";
  sortOrder?: "asc" | "desc";
  searchQuery?: string;
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
  const normalizedSearchQuery = (params?.searchQuery || "").trim();
  if (normalizedSearchQuery) {
    query.set("q", normalizedSearchQuery);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<EvaluationJobListResponse>(`/evaluation-jobs${suffix}`);
}

export function getJobOptions(): Promise<JobOptionsResponse> {
  return requestJson<JobOptionsResponse>("/evaluation-jobs/options").then(validateJobOptions);
}

export function createJob(payload: Record<string, unknown>): Promise<EvaluationJob> {
  return requestJson<EvaluationJob>("/evaluation-jobs", { method: "POST", body: payload });
}

export function duplicateJob(jobId: string): Promise<EvaluationJob> {
  return requestJson<EvaluationJob>(`/evaluation-jobs/${jobId}/duplicate`, { method: "POST" });
}

export function retryJob(jobId: string, queue = true): Promise<EvaluationJob> {
  return requestJson<EvaluationJob>(`/evaluation-jobs/${jobId}/retry`, {
    method: "POST",
    body: { queue }
  });
}

export function getJob(jobId: string): Promise<EvaluationJob> {
  return requestJson<EvaluationJob>(`/evaluation-jobs/${jobId}`);
}

export function runJob(jobId: string): Promise<JobRunResult> {
  return requestJson<JobRunResult>(`/evaluation-jobs/${jobId}/run`, { method: "POST" });
}

export function queueJob(jobId: string): Promise<EvaluationJob> {
  return requestJson<EvaluationJob>(`/evaluation-jobs/${jobId}/queue`, { method: "POST" });
}

export function cancelJob(jobId: string, reason = ""): Promise<EvaluationJob> {
  return requestJson<EvaluationJob>(`/evaluation-jobs/${jobId}/cancel`, {
    method: "POST",
    body: { reason }
  });
}

export function processQueue(maxJobs = 10): Promise<QueueProcessResult> {
  return requestJson<QueueProcessResult>(`/evaluation-jobs/process-queue?max_jobs=${maxJobs}`, {
    method: "POST"
  });
}

export function getQueueStats(): Promise<QueueStatsResult> {
  return requestJson<QueueStatsResult>("/evaluation-jobs/queue/stats");
}

export function getJobSummary(jobId: string): Promise<JobSummaryResult> {
  return requestJson<JobSummaryResult>(`/evaluation-jobs/${jobId}/summary`);
}

export function getJobFailedCases(
  jobId: string,
  options?: { limit?: number; offset?: number }
): Promise<FailedCasesResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(options?.limit ?? 50));
  query.set("offset", String(options?.offset ?? 0));
  return requestJson<FailedCasesResponse>(`/evaluation-jobs/${jobId}/failed-cases?${query.toString()}`);
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
  return requestJson<TracesResponse>(`/evaluation-jobs/${jobId}/traces?${query.toString()}`);
}

export function getJobReport(jobId: string): Promise<JobReportPayload> {
  return requestJson<JobReportPayload>(`/evaluation-jobs/${jobId}/report`);
}

export function getJobClientReport(jobId: string, failedCaseLimit = 20): Promise<JobClientReportPayload> {
  return requestJson<JobClientReportPayload>(
    `/evaluation-jobs/${jobId}/client-report?failed_case_limit=${failedCaseLimit}`
  );
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export function getModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models");
}
