"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createJob, getJobOptions } from "@/lib/api";
import type { JobOptionsResponse } from "@/lib/types";

type JobFormState = {
  input_path: string;
  provider: "mock" | "ollama" | "local";
  model_name: string;
  dataset_version: string;
  evaluation_mode: "regression" | "exploratory" | "adversarial" | "trace_replay";
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

export default function NewJobPage() {
  const router = useRouter();
  const [state, setState] = useState<JobFormState>(defaultState);
  const [options, setOptions] = useState<JobOptionsResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadOptions() {
      setLoadingOptions(true);
      try {
        const loaded = await getJobOptions();
        setOptions(loaded);
        setState((prev) => {
          const fallbackProvider = (loaded.providers[0] as JobFormState["provider"] | undefined) || prev.provider;
          const provider = loaded.providers.includes(prev.provider) ? prev.provider : fallbackProvider;
          const providerModels = loaded.models_by_provider[provider] || [];
          const modelName = providerModels.includes(prev.model_name) ? prev.model_name : (providerModels[0] || prev.model_name);
          const fallbackMode =
            (loaded.evaluation_modes[0] as JobFormState["evaluation_mode"] | undefined) || prev.evaluation_mode;
          const evaluationMode = loaded.evaluation_modes.includes(prev.evaluation_mode)
            ? prev.evaluation_mode
            : fallbackMode;
          const oracleProfile = loaded.oracle_profiles.includes(prev.oracle_profile)
            ? prev.oracle_profile
            : (loaded.oracle_profiles[0] || prev.oracle_profile);
          const inputPath = loaded.dataset_paths.includes(prev.input_path)
            ? prev.input_path
            : (loaded.dataset_paths[0] || prev.input_path);
          const datasetVersion = prev.dataset_version.trim() ? prev.dataset_version : "";
          return {
            ...prev,
            provider,
            model_name: modelName,
            evaluation_mode: evaluationMode,
            oracle_profile: oracleProfile,
            input_path: inputPath,
            dataset_version: datasetVersion
          };
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load job options.");
      } finally {
        setLoadingOptions(false);
      }
    }

    void loadOptions();
  }, []);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const payload = {
        ...state,
        dataset_version: state.dataset_version.trim() || null,
        limit: state.limit > 0 ? state.limit : null
      };
      const job = await createJob(payload);
      router.push(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <h1>Create Evaluation Job</h1>
          <p>Define one evaluation request. After creation, run it and inspect summary, failures, traces, and report.</p>
        </div>
        <Link className="btn btn-secondary" href="/jobs">
          Back to Jobs
        </Link>
      </section>

      <form className="panel grid" onSubmit={onSubmit}>
        {loadingOptions && <p className="meta">Loading provider/model/dataset options...</p>}
        <div className="form-grid">
          <label>
            Dataset path
            <input
              className="input"
              list="dataset-path-options"
              value={state.input_path}
              onChange={(event) => setState((prev) => ({ ...prev, input_path: event.target.value }))}
            />
            <datalist id="dataset-path-options">
              {(options?.dataset_paths || []).map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
          </label>
          <label>
            Provider
            <select
              value={state.provider}
              onChange={(event) => {
                const provider = event.target.value as JobFormState["provider"];
                setState((prev) => {
                  const models = options?.models_by_provider[provider] || [];
                  const resolvedModel = models.includes(prev.model_name) ? prev.model_name : (models[0] || prev.model_name);
                  return { ...prev, provider, model_name: resolvedModel };
                });
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
            <input
              className="input"
              list="model-name-options"
              value={state.model_name}
              onChange={(event) => setState((prev) => ({ ...prev, model_name: event.target.value }))}
            />
            <datalist id="model-name-options">
              {(options?.models_by_provider[state.provider] || []).map((model) => (
                <option key={model} value={model} />
              ))}
            </datalist>
          </label>
          <label>
            Evaluation mode
            <select
              value={state.evaluation_mode}
              onChange={(event) =>
                setState((prev) => ({
                  ...prev,
                  evaluation_mode: event.target.value as JobFormState["evaluation_mode"]
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
          <label>
            Oracle profile
            <input
              className="input"
              list="oracle-profile-options"
              value={state.oracle_profile}
              onChange={(event) => setState((prev) => ({ ...prev, oracle_profile: event.target.value }))}
            />
            <datalist id="oracle-profile-options">
              {(options?.oracle_profiles || []).map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
          </label>
          <label>
            Dataset version (optional)
            <input
              className="input"
              list="dataset-version-options"
              value={state.dataset_version}
              onChange={(event) => setState((prev) => ({ ...prev, dataset_version: event.target.value }))}
            />
            <datalist id="dataset-version-options">
              {(options?.dataset_versions || []).map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
          </label>
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
              step={0.1}
              min={0}
              max={1}
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
              max={1024}
              value={state.max_output_tokens}
              onChange={(event) => setState((prev) => ({ ...prev, max_output_tokens: Number(event.target.value) }))}
            />
          </label>
          <label>
            Timeout seconds
            <input
              className="input"
              type="number"
              min={1}
              max={300}
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

        <label>
          Notes
          <textarea
            rows={4}
            value={state.notes}
            onChange={(event) => setState((prev) => ({ ...prev, notes: event.target.value }))}
          />
        </label>

        {error && <p className="error">{error}</p>}

        <div className="btn-row">
          <button className="btn btn-primary" disabled={submitting} type="submit">
            {submitting ? "Creating..." : "Create Job"}
          </button>
        </div>
      </form>
    </main>
  );
}
