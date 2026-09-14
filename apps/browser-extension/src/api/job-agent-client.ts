/** The only place the extension talks to the backend.
 *
 * The backend is the source of truth for the role map, the searches, the jobs
 * and the scores. The extension holds no business logic of its own beyond
 * extracting a page and rendering what it is told.
 */

import { getConfig } from "../shared/storage";
import {
  AssistantAnswer,
  CapturePayload,
  ImportResult,
  SearchInbox,
  SessionInfo,
} from "../shared/types";

export class JobAgentApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly needsPairing = false,
  ) {
    super(message);
    this.name = "JobAgentApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const config = await getConfig();
  if (!config.apiBaseUrl) {
    throw new JobAgentApiError("No Job Agent URL configured.", 0, true);
  }

  const headers = new Headers(init.headers ?? {});
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (config.token) headers.set("Authorization", `Bearer ${config.token}`);

  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, { ...init, headers });
  } catch (cause) {
    throw new JobAgentApiError(
      `Cannot reach Job Agent at ${config.apiBaseUrl}. Is it running?`,
      0,
    );
  }

  if (response.status === 401 || response.status === 403) {
    const detail = await safeDetail(response);
    throw new JobAgentApiError(detail ?? "Extension is not paired.", response.status, true);
  }
  if (!response.ok) {
    const detail = await safeDetail(response);
    throw new JobAgentApiError(detail ?? `Request failed (${response.status}).`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function safeDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    return detail ? JSON.stringify(detail) : null;
  } catch {
    return null;
  }
}

export const jobAgentClient = {
  getSession(): Promise<SessionInfo> {
    return request<SessionInfo>("/api/extension/session");
  },

  getInbox(): Promise<SearchInbox> {
    return request<SearchInbox>("/api/extension/searches");
  },

  recordSearchOpened(queryId: string): Promise<unknown> {
    return request(`/api/extension/searches/${encodeURIComponent(queryId)}/opened`, {
      method: "POST",
    });
  },

  lookupJob(url: string): Promise<{ found: boolean } & Partial<ImportResult>> {
    return request(`/api/extension/jobs/lookup?url=${encodeURIComponent(url)}`);
  },

  importJob(payload: CapturePayload): Promise<ImportResult> {
    return request<ImportResult>("/api/jobs/import-browser", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getImportStatus(jobId: string): Promise<ImportResult> {
    return request<ImportResult>(`/api/extension/jobs/${encodeURIComponent(jobId)}/status`);
  },

  askAssistant(payload: {
    question: string;
    jobId?: string | null;
    pageContext?: string;
    history?: { role: string; content: string }[];
  }): Promise<AssistantAnswer> {
    return request<AssistantAnswer>("/api/assistant/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  rememberAnswer(question: string, answer: string): Promise<unknown> {
    return request("/api/assistant/answers", {
      method: "POST",
      body: JSON.stringify({ question, answer }),
    });
  },

  recordOutcome(jobId: string, outcome: string, note = ""): Promise<{ status: string }> {
    return request(`/api/extension/jobs/${encodeURIComponent(jobId)}/outcome`, {
      method: "POST",
      body: JSON.stringify({ outcome, note }),
    });
  },

  undoOutcome(jobId: string): Promise<{ status: string }> {
    return request(`/api/extension/jobs/${encodeURIComponent(jobId)}/outcome/undo`, {
      method: "POST",
    });
  },

  prepareApplication(jobId: string): Promise<unknown> {
    return request(`/api/jobs/${encodeURIComponent(jobId)}/prepare`, { method: "POST" });
  },
};
