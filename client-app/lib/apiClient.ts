export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type ApiErrorKind =
  | "backend_unreachable"
  | "endpoint_not_found"
  | "resource_not_found"
  | "request_timeout"
  | "invalid_response"
  | "validation_error"
  | "non_2xx_response";

export class ApiClientError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly path: string;
  readonly detail: string;
  readonly responseBody?: unknown;

  constructor(args: {
    kind: ApiErrorKind;
    path: string;
    detail: string;
    status?: number;
    responseBody?: unknown;
  }) {
    super(args.detail);
    this.name = "ApiClientError";
    this.kind = args.kind;
    this.status = args.status;
    this.path = args.path;
    this.detail = args.detail;
    this.responseBody = args.responseBody;
  }
}

type ApiRequestOptions = {
  method?: "GET" | "POST";
  body?: Record<string, unknown>;
  signal?: AbortSignal;
  timeoutMs?: number;
};

async function parseErrorPayload(response: Response): Promise<{ detail: string; payload?: unknown }> {
  const fallbackDetail = `${response.status} ${response.statusText}`.trim();
  const text = await response.text();
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = text;
  }
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : payload;
  if (Array.isArray(detail)) {
    const messages = detail.map((item: { loc?: unknown[]; msg?: string }) =>
      `${(item.loc || []).filter(part => part !== "body").join(".") || "request"}: ${item.msg || "Invalid value"}`);
    return { detail: messages.join("; ").slice(0, 2000), payload };
  }
  return { detail: typeof detail === "string" && detail.trim() ? detail.trim().slice(0, 2000) : fallbackDetail, payload };
}

async function request<T>(path: string, options: ApiRequestOptions, read: (response: Response) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) abort();
  const method = options.method || "GET";
  // Runs are synchronous POSTs: do not mistake a long evaluation for a GET timeout.
  const timeoutMs = options.timeoutMs ?? (method === "GET" ? 10000 : 0);
  let timedOut = false;
  const timer = timeoutMs > 0 ? setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs) : undefined;
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
      signal: controller.signal
    });
    if (!response.ok) {
      const parsed = await parseErrorPayload(response);
      const kind: ApiErrorKind = response.status === 404
        ? (parsed.detail.toLowerCase() === "not found" ? "endpoint_not_found" : "resource_not_found")
        : response.status === 400 || response.status === 422 ? "validation_error" : "non_2xx_response";
      throw new ApiClientError({ kind, status: response.status, path, detail: parsed.detail, responseBody: parsed.payload });
    }
    return await read(response);
  } catch (error) {
    if (options.signal?.aborted) throw error;
    if (error instanceof ApiClientError) throw error;
    throw new ApiClientError({
      kind: timedOut ? "request_timeout" : "backend_unreachable",
      path,
      detail: timedOut
        ? `Request to ${path} timed out after ${timeoutMs / 1000}s. Recheck backend status and try again.`
        : `Cannot reach ${API_BASE_URL}. Check that FastAPI is running, the API URL, and browser CORS/mixed-content settings. ${error instanceof Error ? error.message : "Network error"}`
    });
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

export function requestJson<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  return request(path, options, async response => {
    const text = await response.text();
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiClientError({ kind: "invalid_response", path, status: response.status,
        detail: `Invalid JSON from ${path}. Check the backend URL and proxy. Response excerpt: ${text.slice(0, 300)}` });
    }
  });
}

export function requestDownload(path: string, options: ApiRequestOptions = {}): Promise<Blob> {
  return request(path, { timeoutMs: 60000, ...options }, response => response.blob());
}

export function saveDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  try {
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    // Let the browser start consuming the URL before releasing it.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
