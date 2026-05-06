export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type ApiErrorKind =
  | "backend_unreachable"
  | "endpoint_not_found"
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
};

async function parseErrorPayload(response: Response): Promise<{ detail: string; payload?: unknown }> {
  const fallbackDetail = `${response.status} ${response.statusText}`.trim();
  try {
    const payload = (await response.json()) as unknown;
    if (payload && typeof payload === "object") {
      const detailField = (payload as { detail?: unknown }).detail;
      if (typeof detailField === "string" && detailField.trim()) {
        return { detail: detailField, payload };
      }
      return { detail: fallbackDetail, payload };
    }
    return { detail: fallbackDetail };
  } catch {
    try {
      const text = await response.text();
      if (text.trim()) return { detail: text.trim() };
    } catch {
      return { detail: fallbackDetail };
    }
  }
  return { detail: fallbackDetail };
}

export async function requestJson<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json"
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store"
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Could not connect to backend API.";
    throw new ApiClientError({
      kind: "backend_unreachable",
      path,
      detail
    });
  }

  if (!response.ok) {
    const parsed = await parseErrorPayload(response);
    const kind: ApiErrorKind =
      response.status === 404
        ? "endpoint_not_found"
        : response.status === 400 || response.status === 422
          ? "validation_error"
          : "non_2xx_response";
    throw new ApiClientError({
      kind,
      status: response.status,
      path,
      detail: parsed.detail,
      responseBody: parsed.payload
    });
  }

  return (await response.json()) as T;
}

