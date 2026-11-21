type JobStatus = "draft" | "queued" | "running" | "completed" | "failed" | "canceled";

export type EvaluationJob = {
  job_id: string;
  status: JobStatus;
  input_path: string;
  provider: string;
  model_name: string;
  dataset_version: string | null;
  evaluation_mode: string;
  oracle_profile: string;
  temperature: number;
  max_output_tokens: number;
  timeout_seconds: number;
  repeat_count: number;
  limit: number | null;
  notes: string;
  submitted_by: string;
  team_name: string;
  client_name: string;
  project_name: string;
  linked_run_id: string | null;
  source_job_id?: string | null;
  dataset_sha256?: string | null;
  dataset_snapshot?: Record<string, unknown>[];
  queued_at?: string | null;
  failure_reason: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  /** List responses only: attempt outcomes of the linked run, null before execution. */
  attempts?: number | null;
  passed_attempts?: number | null;
  /** Live progress while the API process executes this job. */
  progress_done?: number | null;
  progress_total?: number | null;
  stop_requested?: boolean;
};

export type EvaluationJobListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: EvaluationJob[];
};

export type QueueScheduleResult = {
  requested_max_jobs: number;
  scheduled_count: number;
  job_ids: string[];
};

export type QueueStatsResult = {
  total: number;
  by_status: {
    draft: number;
    queued: number;
    running: number;
    completed: number;
    failed: number;
    canceled: number;
  };
};

export type JobSummaryResult = {
  job: EvaluationJob;
  storage_summary: Record<string, unknown>;
  report: {
    total_test_cases: number;
    passed: number;
    failed: number;
    accuracy: number;
    average_latency_ms: number;
    schema_case_count?: number;
    measurement_notes?: string[];
    latency_sources?: Record<string, number>;
    unique_test_cases?: number;
    p95_latency_ms?: number;
    p50_latency_ms?: number;
    repeat_k?: number | null;
    pass_at_k?: number | null;
    pass_hat_k?: number | null;
    schema_pass_rate?: number | null;
    schema_attempt_count?: number;
    category_reports?: { category: string; total_test_cases: number; passed: number; failed: number; accuracy: number }[];
    error_distribution?: Record<string, number>;
  };
};

type FailedCase = {
  test_case_id: string;
  attempt_index: number;
  category: string | null;
  test_source: string | null;
  oracle_type: string | null;
  expected_answer: string | null;
  actual_answer: string | null;
  is_correct: boolean;
  score: number;
  error_type: string | null;
  explanation: string | null;
  latency_ms: number;
};

export type FailedCasesResponse = {
  total: number;
  limit: number;
  offset: number;
  items: FailedCase[];
};

export type TraceRecord = {
  trace_id: string;
  run_id: string;
  test_case_id: string;
  attempt_index: number;
  prompt: string | null;
  raw_output: string | null;
  normalized_output: string | null;
  expected_answer: string | null;
  oracle_details: Record<string, unknown> | null;
  oracle_config: Record<string, unknown> | null;
  category: string | null;
  test_source: string | null;
  oracle_type: string | null;
  score: number;
  is_correct: boolean;
  error_type: string | null;
  explanation: string | null;
  created_at: string | null;
};

export type TracesResponse = {
  total: number;
  limit: number;
  offset: number;
  items: TraceRecord[];
};

export type JobReportPayload = {
  job: EvaluationJob;
  run_id: string;
  markdown_report: string;
  storage_summary: Record<string, unknown>;
  report: Record<string, unknown>;
};

export type JobClientReportPayload = {
  job: EvaluationJob;
  run_id: string;
  generated_at: string;
  storage_summary: Record<string, unknown>;
  report: Record<string, unknown>;
  failed_case_total: number;
  failed_cases_sample: FailedCase[];
  markdown_report: string;
};

type DatasetOption = {
  id: string;
  label: string;
  input_path: string;
  dataset_version: string | null;
  evaluation_mode: string;
};

export type JobOptionsResponse = {
  providers: string[];
  models_by_provider: Record<string, string[]>;
  dataset_paths: string[];
  datasets: DatasetOption[];
  dataset_versions: string[];
  oracle_profiles: string[];
  oracle_types: string[];
  evaluation_modes: string[];
  openai_compatible_base_url?: string;
};

export type HealthResponse = {
  status: string;
};

export type ModelsResponse = {
  provider: string;
  ollama_reachable: boolean;
  installed_models: string[];
  recommended_models: string[];
  available_models: string[];
  error: string | null;
};

export type MetricsReport = JobSummaryResult["report"] & { run_id: string };

export type CaseChange = {
  test_case_id: string;
  category: string;
  attempts: number;
  baseline_passed: number;
  candidate_passed: number;
};

export type RunComparison = {
  eligibility: { eligible: boolean; research_only: boolean; issues: string[] };
  baseline_report: MetricsReport;
  candidate_report: MetricsReport;
  case_changes: { regressions: CaseChange[]; improvements: CaseChange[] };
};
