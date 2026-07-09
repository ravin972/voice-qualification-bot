import type {
  ApiErrorBody,
  ConversationTurnResponse,
  HealthResponse,
  StartConversationRequest,
  SubmitMessageRequest,
} from "@/types/api";

/**
 * Base URL for the backend API.
 *
 * In dev, Vite proxies `/api/*` to `http://localhost:8000/*` (see
 * vite.config.ts) so the browser never has to deal with cross-origin
 * requests. Set VITE_API_BASE_URL to point at a different backend (e.g. a
 * deployed instance) — it's used as-is, with no proxy involved.
 */
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<TResponse>(
  path: string,
  init?: RequestInit,
): Promise<TResponse> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      detail = body.detail ?? detail;
    } catch {
      // Response wasn't JSON (e.g. a proxy/network error page) — keep the fallback.
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as TResponse;
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  startConversation: (body: StartConversationRequest) =>
    request<ConversationTurnResponse>("/conversation/test/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  submitMessage: (body: SubmitMessageRequest) =>
    request<ConversationTurnResponse>("/conversation/test/message", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
