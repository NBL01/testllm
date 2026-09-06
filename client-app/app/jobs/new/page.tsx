"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { createJob, getHealth, getJobOptions, getModels } from "@/lib/api";
import { API_BASE_URL, ApiClientError } from "@/lib/apiClient";
import type { JobOptionsResponse, ModelsResponse } from "@/lib/types";
import { validateJobNumbers } from "@/lib/jobForm";

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

const defaultState: JobFormState = {
  input_path: "",
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
        likelyCause: `FastAPI is offline, '${API_BASE_URL}' is incorrect, or browser CORS/mixed-content settings block the request.`,
        technicalDetail: `${error.detail} (request path: ${error.path})`,
        suggestedCommand: ".venv/bin/python -m uvicorn llm_reliability_analytics.main:app --app-dir src --reload"
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
  const [state, setState] = useState<JobFormState>(defaultState);
  const [datasetPreset, setDatasetPreset] = useState("");
  const [datasetSource, setDatasetSource] = useState<"preset" | "custom">("preset");
  const [discoveryAttempt, setDiscoveryAttempt] = useState(0);
  const submitLock = useRef(false);
  const [options, setOptions] = useState<JobOptionsResponse | null>(null);
  const [modelsSnapshot, setModelsSnapshot] = useState<ModelsResponse | null>(null);
  const [statusPanel, setStatusPanel] = useState<StatusPanelState>(defaultStatus);
  const [submitting, setSubmitting] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [apiError, setApiError] = useState<UiError | null>(null);
  const [successJobId, setSuccessJobId] = useState<string>("");
  const selectedDataset = options?.datasets.find(dataset => dataset.id === datasetPreset);
  const effectiveDataset = datasetSource === "preset" ? selectedDataset : {
    input_path: state.input_path.trim(), dataset_version: state.dataset_version.trim() || null,
    evaluation_mode: state.evaluation_mode
  };

  const modelChoices = useMemo(() => {
    const providerOptions = options?.models_by_provider[state.provider] || [];
    if (state.provider === "mock") {
      return dedupe(providerOptions);
    }
    return dedupe([
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

  const validationErrors = (() => {
    const errors = validateJobNumbers(state);
    if (!state.provider.trim()) errors.push("Provider is required.");
    if (!state.model_name.trim()) errors.push("Model name is required.");
    if (!effectiveDataset?.input_path.trim()) errors.push("Select a backend dataset or enter an explicit custom dataset path.");
    if (effectiveDataset?.input_path && !/\.(jsonl|csv)$/i.test(effectiveDataset.input_path)) errors.push("Dataset path must name a JSONL or CSV file on the backend.");
    if (options && !options.providers.includes(state.provider)) errors.push("Select a supported provider.");
    if (!modelChoices.includes(state.model_name)) errors.push("Select a model from the backend catalog.");
    return errors;
  })();

  const formInvalid = validationErrors.length > 0;

  useEffect(() => {
    let active = true;
    async function loadOptions() {
      setLoadingOptions(true);
      setApiError(null);
      try {
        const loaded = await getJobOptions();
        if (!active) return;
        setOptions(loaded);
        setDatasetPreset(previous => previous || loaded.datasets[0]?.id || "");
      } catch (error) {
        if (active) setApiError(toUiError(error));
      } finally {
        if (active) setLoadingOptions(false);
      }
    }
    void loadOptions();
    return () => { active = false; };
  }, [discoveryAttempt]);

  useEffect(() => {
    let active = true;
    setStatusPanel(defaultStatus);
    async function loadStatus() {
      try {
        const health = await getHealth();
        if (!active) return;
        setStatusPanel((prev) => ({
          ...prev,
          backend: health.status === "ok" ? "ok" : "down"
        }));
      } catch {
        if (!active) return;
        setStatusPanel((prev) => ({ ...prev, backend: "down" }));
      }

      try {
        const models = await getModels();
        if (!active) return;
        setModelsSnapshot(models);
        setStatusPanel((prev) => ({
          ...prev,
          modelsEndpointAvailable: true,
          ollama: models.ollama_reachable ? "ok" : "down",
          installedModelCount: models.installed_models.length
        }));
      } catch (error) {
        if (!active) return;
        setModelsSnapshot(null);
        if (error instanceof ApiClientError && error.status === 404) {
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
    return () => { active = false; };
  }, [discoveryAttempt]);

  useEffect(() => {
    setState((prev) => {
      const providerModels = modelChoices;
      const modelName = providerModels.includes(prev.model_name) ? prev.model_name : (providerModels[0] || "");
      return { ...prev, model_name: modelName };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.provider, modelChoices.join("|")]);

  function applyDatasetPreset(nextPreset: string) {
    setDatasetPreset(nextPreset);
    setDatasetSource("preset");
    setState((prev) => ({
      ...prev,
      input_path: "", dataset_version: "", evaluation_mode: "regression"
    }));
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (formInvalid || submitLock.current || !options || loadingOptions || !effectiveDataset) return;
    submitLock.current = true;
    setSubmitting(true);
    setApiError(null);
    setSuccessJobId("");

    try {
      const payload = {
        ...state,
        input_path: effectiveDataset.input_path,
        dataset_version: effectiveDataset.dataset_version,
        evaluation_mode: effectiveDataset.evaluation_mode,
        model_name: state.model_name.trim(),
        oracle_profile: "default",
        limit: state.limit > 0 ? state.limit : null
      };
      const job = await createJob(payload);
      setSuccessJobId(job.job_id);
    } catch (error) {
      submitLock.current = false;
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
        <div className="btn-row">
          <button className="btn btn-secondary" type="button" disabled={loadingOptions || submitting || !!successJobId}
            onClick={() => setDiscoveryAttempt(value => value + 1)}>Recheck Status and Options</button>
        </div>
        <p className="meta">API: <code>{API_BASE_URL}</code>. Configure <code>NEXT_PUBLIC_API_BASE_URL</code> in
          <code> client-app/.env.local</code>, then restart Next.js. If unavailable, run from the repository root:
          <code> .venv/bin/python -m uvicorn llm_reliability_analytics.main:app --app-dir src --reload</code>.</p>
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
        <fieldset className="grid form-fields" disabled={submitting || !!successJobId}>
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
                value={effectiveDataset?.evaluation_mode || state.evaluation_mode}
                disabled={datasetSource === "preset"}
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
              Dataset source
              <select value={datasetSource} onChange={event => {
                setDatasetSource(event.target.value as "preset" | "custom");
                setState(prev => ({ ...prev, input_path: "", dataset_version: "", evaluation_mode: "regression" }));
              }}>
                <option value="preset">Backend preset</option>
                <option value="custom">Custom backend file</option>
              </select>
            </label>
            {datasetSource === "preset" && <label>
              Dataset preset
              <select value={datasetPreset} onChange={(event) => applyDatasetPreset(event.target.value)}>
                <option value="" disabled>Select a dataset</option>
                {(options?.datasets || []).map(dataset => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.label}
                  </option>
                ))}
              </select>
            </label>}
            <label>
              Oracle profile
              <select
                value="default"
                disabled
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
                value={effectiveDataset?.dataset_version || ""}
                disabled={datasetSource === "preset"}
                onChange={(event) => setState((prev) => ({ ...prev, dataset_version: event.target.value }))}
              />
            </label>
          </div>
          <p className="meta">Default is metadata only: scoring uses each dataset case&apos;s oracle type and configuration.</p>
          {datasetSource === "custom" && (
            <label style={{ marginTop: "0.6rem" }}>
              Custom dataset path
              <input
                className="input"
                placeholder="data/raw/my_test_cases.jsonl"
                value={state.input_path}
                onChange={(event) => setState(prev => ({ ...prev, input_path: event.target.value }))}
              />
            </label>
          )}
          <p className="meta" aria-live="polite">Effective dataset: <code>{effectiveDataset?.input_path || "not selected"}</code>
            {" | "}version: {effectiveDataset?.dataset_version || "dataset-defined"}{" | "}mode: {effectiveDataset?.evaluation_mode || "not selected"}.
            Custom paths refer to supported files on the backend, not browser uploads.</p>
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
                step={1}
                value={Number.isFinite(state.repeat_count) ? state.repeat_count : ""}
                onChange={(event) => setState((prev) => ({ ...prev, repeat_count: event.target.valueAsNumber }))}
              />
            </label>
            <label>
              Temperature
              <input
                className="input"
                type="number"
                min={0}
                step="any"
                value={Number.isFinite(state.temperature) ? state.temperature : ""}
                onChange={(event) => setState((prev) => ({ ...prev, temperature: event.target.valueAsNumber }))}
              />
            </label>
            <label>
              Max output tokens
              <input
                className="input"
                type="number"
                min={1}
                max={1024}
                step={1}
                value={Number.isFinite(state.max_output_tokens) ? state.max_output_tokens : ""}
                onChange={(event) => setState((prev) => ({ ...prev, max_output_tokens: event.target.valueAsNumber }))}
              />
            </label>
            <label>
              Timeout seconds
              <input
                className="input"
                type="number"
                min={5}
                max={300}
                step="any"
                value={Number.isFinite(state.timeout_seconds) ? state.timeout_seconds : ""}
                onChange={(event) => setState((prev) => ({ ...prev, timeout_seconds: event.target.valueAsNumber }))}
              />
            </label>
            <label>
              Test-case limit (0 = none)
              <input
                className="input"
                type="number"
                min={0}
                step={1}
                value={Number.isFinite(state.limit) ? state.limit : ""}
                onChange={(event) => setState((prev) => ({ ...prev, limit: event.target.valueAsNumber }))}
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
        </fieldset>

        {validationErrors.length > 0 && (
          <div className="panel" aria-live="polite" style={{ borderColor: "#f0c3c3" }}>
            <strong>Form validation</strong>
            {validationErrors.map((item) => (
              <p className="error" key={item} style={{ margin: "0.35rem 0 0" }}>
                {item}
              </p>
            ))}
          </div>
        )}

        {apiError && (
          <div className="panel" role="alert" style={{ borderColor: "#f0c3c3", background: "#fff7f7" }}>
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
          <div className="panel" role="status" style={{ borderColor: "#b5e6ce", background: "#f4fff8" }}>
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
          <button className="btn btn-primary" disabled={submitting || !!successJobId || formInvalid || loadingOptions || !options} type="submit">
            {successJobId ? "Draft Created" : submitting ? "Creating..." : "Create Draft Job"}
          </button>
        </div>
      </form>
    </main>
  );
}
