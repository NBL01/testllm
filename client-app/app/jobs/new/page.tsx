"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createJob, getHealth, getJobOptions, getModels } from "@/lib/api";
import { API_BASE_URL, ApiClientError } from "@/lib/apiClient";
import type { JobOptionsResponse, ModelsResponse } from "@/lib/types";

type Provider = "mock" | "ollama" | "local";
type EvaluationMode = "regression" | "exploratory" | "adversarial" | "trace_replay";

type JobFormState = {
  input_path: string;
  provider: Provider;
  model_name: string;
  dataset_version: string;
  evaluation_mode: EvaluationMode;
  oracle_profile: string;
  repeat_count: number;
  temperature: number;
  max_output_tokens: number;
  timeout_seconds: number;
  limit: number;
  notes: string;
  submitted_by: string;
  team_name: string;
  client_name: string;
  project_name: string;
};

type DatasetPresetKey = "sample_test_cases.jsonl" | "regression_v1" | "adversarial_v1";
type StatusFlag = "checking" | "ok" | "down" | "not_checked";

type StatusPanelState = {
  backend: StatusFlag;
  ollama: StatusFlag;
  installedModelCount: number | null;
  modelsEndpointAvailable: boolean;
};

type UiError = {
  title: string;
  likelyCause: string;
  technicalDetail: string;
  suggestedCommand?: string;
};

const MOCK_MODELS = ["mock-baseline", "mock-noisy", "mock-failing"];
const RECOMMENDED_OLLAMA_MODELS = ["llama3.2:1b", "qwen2.5:0.5b", "qwen2.5:1.5b", "gemma2:2b"];

const DATASET_PRESETS: Record<
  DatasetPresetKey,
  { label: string; inputPath: string; datasetVersion: string; evaluationMode?: EvaluationMode }
> = {
  "sample_test_cases.jsonl": {
    label: "sample_test_cases.jsonl",
    inputPath: "sample_test_cases.jsonl",
    datasetVersion: ""
  },
  regression_v1: {
    label: "regression_v1",
    inputPath: "sample_test_cases.jsonl",
    datasetVersion: "regression_v1",
    evaluationMode: "regression"
  },
  adversarial_v1: {
    label: "adversarial_v1",
    inputPath: "sample_adversarial_test_cases.jsonl",
    datasetVersion: "adversarial_v1",
    evaluationMode: "adversarial"
  }
};

const defaultState: JobFormState = {
  input_path: "sample_test_cases.jsonl",
  provider: "mock",
  model_name: "mock-baseline",
  dataset_version: "",
  evaluation_mode: "regression",
  oracle_profile: "default",
  repeat_count: 1,
  temperature: 0,
  max_output_tokens: 128,
  timeout_seconds: 30,
  limit: 0,
  notes: "",
  submitted_by: "",
  team_name: "",
  client_name: "",
  project_name: ""
};

const defaultStatus: StatusPanelState = {
  backend: "checking",
  ollama: "not_checked",
  installedModelCount: null,
  modelsEndpointAvailable: false
};

function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

function toUiError(error: unknown): UiError {
  if (error instanceof ApiClientError) {
    if (error.kind === "backend_unreachable") {
      return {
        title: "Backend API unreachable",
        likelyCause: `FastAPI is offline or '${API_BASE_URL}' is incorrect.`,
        technicalDetail: `${error.detail} (request path: ${error.path})`,
        suggestedCommand: "uvicorn app.api.main:app --reload"
      };
    }
    if (error.kind === "endpoint_not_found") {
      return {
        title: "API endpoint not found",
        likelyCause: "Frontend/backend versions are out of sync or route is missing.",
        technicalDetail: `404 on ${error.path}: ${error.detail}`
      };
    }
    if (error.kind === "validation_error") {
      return {
        title: "Validation failed",
        likelyCause: "One or more fields are invalid for this backend request.",
        technicalDetail: `${error.status ?? 400}: ${error.detail}`
      };
    }
    return {
      title: "Backend request failed",
      likelyCause: "Backend rejected the request or encountered an internal error.",
      technicalDetail: `${error.status ?? "n/a"}: ${error.detail}`
    };
  }
  return {
    title: "Unexpected client error",
    likelyCause: "An unknown client-side error occurred while sending the request.",
    technicalDetail: error instanceof Error ? error.message : String(error)
  };
}

export default function NewJobPage() {
  const router = useRouter();
  const [state, setState] = useState<JobFormState>(defaultState);
  const [datasetPreset, setDatasetPreset] = useState<DatasetPresetKey>("sample_test_cases.jsonl");
  const [advancedDatasetPath, setAdvancedDatasetPath] = useState("");
  const [options, setOptions] = useState<JobOptionsResponse | null>(null);
  const [modelsSnapshot, setModelsSnapshot] = useState<ModelsResponse | null>(null);
  const [statusPanel, setStatusPanel] = useState<StatusPanelState>(defaultStatus);
  const [submitting, setSubmitting] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [apiError, setApiError] = useState<UiError | null>(null);
  const [successJobId, setSuccessJobId] = useState<string>("");

  const modelChoices = useMemo(() => {
    const providerOptions = options?.models_by_provider[state.provider] || [];
    if (state.provider === "mock") {
      return dedupe([...MOCK_MODELS, ...providerOptions]);
    }
    return dedupe([
      ...RECOMMENDED_OLLAMA_MODELS,
      ...(modelsSnapshot?.available_models || []),
      ...providerOptions
    ]);
  }, [modelsSnapshot?.available_models, options?.models_by_provider, state.provider]);

  const selectedModelMayBeMissing = useMemo(() => {
    if (state.provider !== "ollama") return false;
    if (!statusPanel.modelsEndpointAvailable || !modelsSnapshot) return false;
    if (!modelsSnapshot.ollama_reachable) return true;
    if (!state.model_name.trim()) return true;
    return !modelsSnapshot.installed_models.includes(state.model_name.trim());
  }, [state.provider, state.model_name, statusPanel.modelsEndpointAvailable, modelsSnapshot]);

  const validationErrors = useMemo(() => {
    const errors: string[] = [];
    if (!state.provider.trim()) errors.push("Provider is required.");
    if (!state.model_name.trim()) errors.push("Model name is required.");
    if (!state.input_path.trim()) errors.push("Dataset is required.");
    if (state.repeat_count < 1) errors.push("Repeat count must be at least 1.");
    if (state.temperature < 0) errors.push("Temperature must be at least 0.");
    if (state.max_output_tokens < 1) errors.push("Max output tokens must be at least 1.");
    if (state.timeout_seconds < 5) errors.push("Timeout seconds must be at least 5.");
    if (state.limit < 0) errors.push("Test-case limit cannot be negative.");
    return errors;
  }, [state]);

  const formInvalid = validationErrors.length > 0;

  useEffect(() => {
    async function loadOptions() {
      setLoadingOptions(true);
      try {
        const loaded = await getJobOptions();
        setOptions(loaded);
      } catch (error) {
        setApiError(toUiError(error));
      } finally {
        setLoadingOptions(false);
      }
    }
    void loadOptions();
  }, []);

  useEffect(() => {
    async function loadStatus() {
      try {
        const health = await getHealth();
        setStatusPanel((prev) => ({
          ...prev,
          backend: health.status === "ok" ? "ok" : "down"
        }));
      } catch {
        setStatusPanel((prev) => ({ ...prev, backend: "down" }));
      }

      try {
        const models = await getModels();
        setModelsSnapshot(models);
        setStatusPanel((prev) => ({
          ...prev,
          modelsEndpointAvailable: true,
          ollama: models.ollama_reachable ? "ok" : "down",
          installedModelCount: models.installed_models.length
        }));
      } catch (error) {
        if (error instanceof ApiClientError && error.kind === "endpoint_not_found") {
          setStatusPanel((prev) => ({
            ...prev,
            modelsEndpointAvailable: false,
            ollama: "not_checked",
            installedModelCount: null
          }));
          return;
        }
        setStatusPanel((prev) => ({
          ...prev,
          modelsEndpointAvailable: false,
          ollama: prev.backend === "down" ? "not_checked" : "down",
          installedModelCount: null
        }));
      }
    }
    void loadStatus();
  }, []);

  useEffect(() => {
    setState((prev) => {
      const providerModels = modelChoices;
      const modelName = providerModels.includes(prev.model_name) ? prev.model_name : (providerModels[0] || "");
      return { ...prev, model_name: modelName };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.provider, modelChoices.join("|")]);

  function applyDatasetPreset(nextPreset: DatasetPresetKey) {
    setDatasetPreset(nextPreset);
    const preset = DATASET_PRESETS[nextPreset];
    setState((prev) => ({
      ...prev,
      input_path: preset.inputPath,
      dataset_version: preset.datasetVersion || prev.dataset_version,
      evaluation_mode: preset.evaluationMode || prev.evaluation_mode
    }));
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (formInvalid || submitting) return;
    setSubmitting(true);
    setApiError(null);
    setSuccessJobId("");

    try {
      const payload = {
        ...state,
        input_path: advancedDatasetPath.trim() || state.input_path,
        dataset_version: state.dataset_version.trim() || null,
        limit: state.limit > 0 ? state.limit : null
      };
      const job = await createJob(payload);
      setSuccessJobId(job.job_id);
      setTimeout(() => {
        router.push(`/jobs/${job.job_id}`);
      }, 1000);
    } catch (error) {
      setApiError(toUiError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Create Evaluation Job</h1>
          <p>Define one evaluation request. Create a draft job, then review and run it from the job detail page.</p>
        </div>
        <Link className="btn btn-secondary" href="/jobs">
          Back to Jobs
        </Link>
      </section>

      <section className="panel grid" style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0 }}>System Status</h2>
        <div className="form-grid">
          <div>
            <strong>Backend API</strong>
            <div className="meta">
              {statusPanel.backend === "checking" && "checking..."}
              {statusPanel.backend === "ok" && "ok"}
              {statusPanel.backend === "down" && "unreachable"}
            </div>
          </div>
          <div>
            <strong>Ollama status</strong>
            <div className="meta">
              {statusPanel.ollama === "ok" && "reachable"}
              {statusPanel.ollama === "down" && "unreachable"}
              {statusPanel.ollama === "not_checked" && "not checked"}
              {statusPanel.ollama === "checking" && "checking..."}
            </div>
          </div>
          <div>
            <strong>Installed model count</strong>
            <div className="meta">
              {statusPanel.installedModelCount === null ? "not checked" : String(statusPanel.installedModelCount)}
            </div>
          </div>
        </div>
      </section>

      <form className="panel grid" onSubmit={onSubmit}>
        {loadingOptions && <p className="meta">Loading provider/model/dataset options...</p>}

        <section className="grid">
          <h2 style={{ margin: 0 }}>Evaluation Target</h2>
          <div className="form-grid">
            <label>
              Provider
              <select
                value={state.provider}
                onChange={(event) => {
                  const provider = event.target.value as Provider;
                  setState((prev) => ({ ...prev, provider }));
                }}
              >
                {(options?.providers || ["mock", "ollama", "local"]).map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model name
              <select
                value={state.model_name}
                onChange={(event) => setState((prev) => ({ ...prev, model_name: event.target.value }))}
              >
                {modelChoices.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Evaluation mode
              <select
                value={state.evaluation_mode}
                onChange={(event) =>
                  setState((prev) => ({
                    ...prev,
                    evaluation_mode: event.target.value as EvaluationMode
                  }))
                }
              >
                {(options?.evaluation_modes || ["regression", "exploratory", "adversarial", "trace_replay"]).map(
                  (mode) => (
                    <option key={mode} value={mode}>
                      {mode}
                    </option>
                  )
                )}
              </select>
            </label>
          </div>
          {selectedModelMayBeMissing && (
            <p className="error">
              Selected Ollama model may not be installed locally. Install with <code>ollama pull {state.model_name}</code>.
            </p>
          )}
        </section>

        <section className="grid">
          <h2 style={{ margin: 0 }}>Dataset and Oracle</h2>
          <div className="form-grid">
            <label>
              Dataset
              <select value={datasetPreset} onChange={(event) => applyDatasetPreset(event.target.value as DatasetPresetKey)}>
                {Object.entries(DATASET_PRESETS).map(([key, preset]) => (
                  <option key={key} value={key}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Oracle profile
              <select
                value={state.oracle_profile}
                onChange={(event) => setState((prev) => ({ ...prev, oracle_profile: event.target.value }))}
              >
                {(options?.oracle_profiles || ["default"]).map((profile) => (
                  <option key={profile} value={profile}>
                    {profile}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Dataset version (optional)
              <input
                className="input"
                value={state.dataset_version}
                onChange={(event) => setState((prev) => ({ ...prev, dataset_version: event.target.value }))}
              />
            </label>
          </div>
          <details>
            <summary className="meta" style={{ cursor: "pointer" }}>
              Advanced dataset path
            </summary>
            <label style={{ marginTop: "0.6rem" }}>
              Custom dataset path
              <input
                className="input"
                placeholder="sample_test_cases.jsonl"
                value={advancedDatasetPath}
                onChange={(event) => setAdvancedDatasetPath(event.target.value)}
              />
            </label>
          </details>
        </section>

        <section className="grid">
          <h2 style={{ margin: 0 }}>Run Settings</h2>
          <div className="form-grid">
            <label>
              Repeat count
              <input
                className="input"
                type="number"
                min={1}
                value={state.repeat_count}
                onChange={(event) => setState((prev) => ({ ...prev, repeat_count: Number(event.target.value) }))}
              />
            </label>
            <label>
              Temperature
              <input
                className="input"
                type="number"
                min={0}
                step={0.1}
                value={state.temperature}
                onChange={(event) => setState((prev) => ({ ...prev, temperature: Number(event.target.value) }))}
              />
            </label>
            <label>
              Max output tokens
              <input
                className="input"
                type="number"
                min={1}
                value={state.max_output_tokens}
                onChange={(event) => setState((prev) => ({ ...prev, max_output_tokens: Number(event.target.value) }))}
              />
            </label>
            <label>
              Timeout seconds
              <input
                className="input"
                type="number"
                min={5}
                value={state.timeout_seconds}
                onChange={(event) => setState((prev) => ({ ...prev, timeout_seconds: Number(event.target.value) }))}
              />
            </label>
            <label>
              Test-case limit (0 = none)
              <input
                className="input"
                type="number"
                min={0}
                value={state.limit}
                onChange={(event) => setState((prev) => ({ ...prev, limit: Number(event.target.value) }))}
              />
            </label>
          </div>
        </section>

        <section className="grid">
          <h2 style={{ margin: 0 }}>Client Metadata</h2>
          <div className="form-grid">
            <label>
              Submitted by
              <input
                className="input"
                value={state.submitted_by}
                onChange={(event) => setState((prev) => ({ ...prev, submitted_by: event.target.value }))}
              />
            </label>
            <label>
              Team name
              <input
                className="input"
                value={state.team_name}
                onChange={(event) => setState((prev) => ({ ...prev, team_name: event.target.value }))}
              />
            </label>
            <label>
              Client name
              <input
                className="input"
                value={state.client_name}
                onChange={(event) => setState((prev) => ({ ...prev, client_name: event.target.value }))}
              />
            </label>
            <label>
              Project name
              <input
                className="input"
                value={state.project_name}
                onChange={(event) => setState((prev) => ({ ...prev, project_name: event.target.value }))}
              />
            </label>
          </div>
        </section>

        <label>
          Notes
          <textarea
            rows={4}
            value={state.notes}
            onChange={(event) => setState((prev) => ({ ...prev, notes: event.target.value }))}
          />
        </label>

        {validationErrors.length > 0 && (
          <div className="panel" style={{ borderColor: "#f0c3c3" }}>
            <strong>Form validation</strong>
            {validationErrors.map((item) => (
              <p className="error" key={item} style={{ margin: "0.35rem 0 0" }}>
                {item}
              </p>
            ))}
          </div>
        )}

        {apiError && (
          <div className="panel" style={{ borderColor: "#f0c3c3", background: "#fff7f7" }}>
            <strong className="error">{apiError.title}</strong>
            <p className="meta" style={{ margin: "0.35rem 0 0" }}>
              Likely cause: {apiError.likelyCause}
            </p>
            <p className="meta" style={{ margin: "0.35rem 0 0" }}>
              Technical detail: <code>{apiError.technicalDetail}</code>
            </p>
            {apiError.suggestedCommand && (
              <p className="meta" style={{ margin: "0.35rem 0 0" }}>
                Suggested command: <code>{apiError.suggestedCommand}</code>
              </p>
            )}
          </div>
        )}

        {successJobId && (
          <div className="panel" style={{ borderColor: "#b5e6ce", background: "#f4fff8" }}>
            <strong className="success">Draft evaluation job created.</strong>
            <p className="meta" style={{ margin: "0.35rem 0 0" }}>
              job_id: <code>{successJobId}</code>
            </p>
            <div className="btn-row" style={{ marginTop: "0.6rem" }}>
              <Link className="btn btn-primary" href={`/jobs/${successJobId}`}>
                View Job
              </Link>
            </div>
          </div>
        )}

        <div className="btn-row">
          <button className="btn btn-primary" disabled={submitting || formInvalid} type="submit">
            {submitting ? "Creating..." : "Create Draft Job"}
          </button>
        </div>
      </form>
    </main>
  );
}

