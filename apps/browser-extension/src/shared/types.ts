/** Types shared across the service worker, content scripts and UI surfaces. */

export interface ExtensionConfig {
  apiBaseUrl: string;
  token: string;
  injectPageButton: boolean;
}

export const DEFAULT_CONFIG: ExtensionConfig = {
  apiBaseUrl: "http://localhost:8000",
  token: "",
  injectPageButton: true,
};

export interface SessionInfo {
  status: string;
  tokenName: string | null;
  candidateName: string;
  dashboardUrl: string;
  highMatchThreshold: number;
  importPreparesApplication: boolean;
  roleMapVersion: number | null;
  primaryRole: string | null;
  supportedHosts: { host: string; extractor: string }[];
}

export interface SearchTarget {
  queryId: string | null;
  provider: string;
  url: string | null;
  stats?: Record<string, number>;
}

export interface SearchRow {
  label: string;
  query: string;
  roleId: string;
  roleTitle: string;
  location: string | null;
  remote: boolean | null;
  priority: number;
  isExploratory: boolean;
  targets: SearchTarget[];
}

export interface SearchGroup {
  label: string;
  priority: number;
  searches: SearchRow[];
}

export interface SearchSection {
  id: string;
  title: string;
  groups: SearchGroup[];
}

export interface SearchInbox {
  generatedAt: string;
  roleMapVersion: number | null;
  sections: SearchSection[];
  totals: Record<string, number>;
}

/** What an extractor produces. Every field is optional: the backend fills gaps. */
export interface ExtractedJob {
  role?: string;
  company?: string;
  location?: string;
  salary?: string;
  employmentType?: string;
  remotePolicy?: string;
  description?: string;
  applyUrl?: string;
  datePosted?: string;
  requirements?: string[];
  preferredRequirements?: string[];
  technologies?: string[];
}

export interface CapturePayload {
  url: string;
  title: string;
  hostname: string;
  visibleText: string;
  structuredData: unknown;
  cleanedHtml: string;
  capturedAt: string;
  extracted: ExtractedJob;
  canonicalUrlHint: string | null;
  extractionStrategy: string;
  searchQueryId?: string | null;
  searchProvider?: string | null;
  prepareApplication?: boolean;
  discoveredBy?: string;
}

export interface ImportResult {
  status: "imported" | "duplicate" | "rejected";
  jobId: string | null;
  company: string;
  role: string;
  location: string | null;
  canonicalUrl: string | null;
  applyUrl: string | null;
  matchScore: number | null;
  recommendation: string | null;
  primaryRole: string | null;
  strengths: string[];
  gaps: string[];
  applicationRunId: string | null;
  jobStatus: string | null;
  analysisState: "pending" | "complete" | "failed" | "skipped";
  prepareRequested: boolean;
  preparationState: "none" | "ready" | "skipped" | "failed";
  preparationError: string;
  message: string;
  dashboardUrl: string | null;
  analysisQueuedOn?: string;
}

export interface AssistantAnswer {
  answer: string;
  source: "vault" | "model" | "error";
  confidence: number;
  caveats: string[];
  missing: string[];
  warnings: string[];
  canonicalKey: string;
  groundedOn: string[];
}

export interface SubmissionEvidence {
  matched: string;
  excerpt: string;
  source: "text" | "dom" | "url";
}

export interface FormQuestion {
  id: string;
  label: string;
  type: string;
  required: boolean;
  options: string[];
  filled: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  meta?: AssistantAnswer;
}

export type MessageType =
  | "GET_CONFIG"
  | "GET_SESSION"
  | "GET_INBOX"
  | "OPEN_SEARCH"
  | "IMPORT_CURRENT_TAB"
  | "PREPARE_JOB"
  | "ASK_ASSISTANT"
  | "REMEMBER_ANSWER"
  | "READ_PAGE_CONTEXT"
  | "ASSISTANT_PREFILL"
  | "SCAN_FORM"
  | "FILL_FIELD"
  | "FORM_DETECTED"
  | "RECORD_OUTCOME"
  | "SUBMISSION_DETECTED"
  | "UNDO_OUTCOME"
  | "LOOKUP_CURRENT_TAB"
  | "GET_TAB_STATE"
  | "CAPTURE_PAGE"
  | "SHOW_IMPORT_STATE"
  | "OPEN_DASHBOARD"
  | "OPEN_SIDE_PANEL"
  | "TAB_STATE_CHANGED";

export interface Message<T = unknown> {
  type: MessageType;
  payload?: T;
}

/** The per-tab record the popup, side panel and injected button all read. */
export interface TabState {
  tabId: number;
  url: string;
  phase: "idle" | "capturing" | "importing" | "analyzing" | "preparing" | "done" | "error";
  result?: ImportResult;
  error?: string;
  searchQueryId?: string | null;
  searchProvider?: string | null;
  updatedAt: number;
}

export function isJobLikeUrl(url: string): boolean {
  return /(\/jobs?\/|\/careers?\/|\/vacan|\/oferta|\/stelle|\/positions?\/|greenhouse\.io|lever\.co|ashbyhq\.com|workday|workable|smartrecruiters)/i.test(
    url,
  );
}
