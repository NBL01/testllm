import type { JobOptionsResponse } from "./types";

export function validateJobNumbers(state: {
  repeat_count: number; temperature: number; max_output_tokens: number; timeout_seconds: number; limit: number;
}): string[] {
  const errors: string[] = [];
  if (!Number.isSafeInteger(state.repeat_count) || state.repeat_count < 1) errors.push("Repeat count must be a finite integer of at least 1.");
  if (!Number.isFinite(state.temperature) || state.temperature < 0) errors.push("Temperature must be finite and at least 0.");
  if (!Number.isInteger(state.max_output_tokens) || state.max_output_tokens < 1 || state.max_output_tokens > 1024) errors.push("Max output tokens must be an integer from 1 to 1024.");
  if (!Number.isFinite(state.timeout_seconds) || state.timeout_seconds < 5 || state.timeout_seconds > 300) errors.push("Timeout seconds must be finite and from 5 to 300.");
  if (!Number.isSafeInteger(state.limit) || state.limit < 0) errors.push("Test-case limit must be a finite nonnegative integer (0 = none).");
  return errors;
}

export function validateJobOptions(value: JobOptionsResponse): JobOptionsResponse {
  const strings = (items: unknown): items is string[] => Array.isArray(items) && items.every(item => typeof item === "string" && item.trim());
  if (!value || !strings(value.providers) || !value.providers.length || !value.models_by_provider ||
      !value.providers.every(provider => strings(value.models_by_provider[provider])) ||
      !strings(value.evaluation_modes) || !value.evaluation_modes.length ||
      !strings(value.oracle_profiles) || value.oracle_profiles.length !== 1 || value.oracle_profiles[0] !== "default" ||
      !Array.isArray(value.datasets) || !value.datasets.every(dataset => dataset &&
        strings([dataset.id, dataset.label, dataset.input_path, dataset.evaluation_mode]) &&
        value.evaluation_modes.includes(dataset.evaluation_mode) &&
        (dataset.dataset_version === null || typeof dataset.dataset_version === "string")) ||
      new Set(value.datasets.map(dataset => dataset.id)).size !== value.datasets.length) {
    throw new Error("Backend options catalog is incomplete or invalid. Update FastAPI and recheck status; no client presets have been substituted.");
  }
  return value;
}
