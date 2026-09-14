/** The service worker: the only place that talks to the backend and coordinates
 * captures, imports, attribution and the per-tab state every surface renders.
 *
 * Nothing here runs without a user action. There is no crawling, no scrolling,
 * no background scraping and no bulk opening of pages.
 */

import { JobAgentApiError, jobAgentClient } from "../api/job-agent-client";
import { resolveSearchUrl } from "../providers/index";
import {
  clearTabState,
  getAttribution,
  getConfig,
  getCachedInbox,
  cacheInbox,
  getTabState,
  isPaired,
  setAttribution,
  setTabState,
} from "../shared/storage";
import { CapturePayload, ImportResult, Message, TabState } from "../shared/types";

const MENU_ROOT = "job-agent-root";
const MENU_IMPORT = "job-agent-import";
const MENU_IMPORT_PREPARE = "job-agent-import-prepare";
const MENU_OPEN = "job-agent-open";
const MENU_ASK = "job-agent-ask";

const ANALYSIS_POLL_INTERVAL_MS = 1500;
const ANALYSIS_POLL_ATTEMPTS = 24;

// Preparing a CV duplicates the master, patches it and renders a PDF in Reactive
// Resume, so it takes noticeably longer than scoring.
const PREPARE_POLL_INTERVAL_MS = 2500;
const PREPARE_POLL_ATTEMPTS = 36;

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: MENU_ROOT, title: "Job Agent", contexts: ["page", "link", "selection"] });
    chrome.contextMenus.create({
      id: MENU_IMPORT,
      parentId: MENU_ROOT,
      title: "Import this job",
      contexts: ["page", "link", "selection"],
    });
    chrome.contextMenus.create({
      id: MENU_IMPORT_PREPARE,
      parentId: MENU_ROOT,
      title: "Import + prepare application",
      contexts: ["page", "link", "selection"],
    });
    chrome.contextMenus.create({
      id: MENU_ASK,
      parentId: MENU_ROOT,
      title: "Ask Job Agent about this",
      contexts: ["selection"],
    });
    chrome.contextMenus.create({
      id: MENU_OPEN,
      parentId: MENU_ROOT,
      title: "Open Job Agent",
      contexts: ["page", "link", "selection"],
    });
  });

  // The action opens the popup; the side panel is opened deliberately.
  chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: false }).catch(() => undefined);

  void reinjectOpenTabs();
});

/** Re-injects the content script into tabs that were open before an update.
 *
 * Chrome leaves those tabs running the previous build's script, disconnected
 * from the extension, so an import from one of them fails until the page is
 * reloaded. Where permissions allow it, this repairs them silently.
 */
async function reinjectOpenTabs(): Promise<void> {
  const patterns = (chrome.runtime.getManifest().content_scripts ?? [])
    .flatMap((entry) => entry.matches ?? [])
    .filter((pattern) => pattern.startsWith("http"));
  if (!patterns.length) return;

  let tabs: chrome.tabs.Tab[] = [];
  try {
    tabs = await chrome.tabs.query({ url: patterns });
  } catch {
    return;
  }

  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    } catch {
      // Without host permission for this tab the user reloads it themselves,
      // which the import error message tells them to do.
    }
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab?.id) return;
  if (info.menuItemId === MENU_IMPORT) void importTab(tab.id, false);
  if (info.menuItemId === MENU_IMPORT_PREPARE) void importTab(tab.id, true);
  if (info.menuItemId === MENU_OPEN) void openDashboard(null);
  if (info.menuItemId === MENU_ASK) void askAboutSelection(tab, info.selectionText ?? "");
});

/** Opens the side panel with the highlighted form question already typed in. */
async function askAboutSelection(tab: chrome.tabs.Tab, selection: string): Promise<void> {
  const question = selection.trim();
  if (!question) return;
  try {
    await chrome.sidePanel?.open?.({ windowId: tab.windowId ?? chrome.windows.WINDOW_ID_CURRENT });
  } catch {
    // The panel may already be open, which is fine.
  }
  await chrome.storage.session.set({ assistantPrefill: { question, at: Date.now() } });
  chrome.runtime
    .sendMessage({ type: "ASSISTANT_PREFILL", payload: { question } })
    .catch(() => undefined);
}

chrome.commands.onCommand.addListener(async (command) => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  if (command === "import-job") void importTab(tab.id, false);
  if (command === "import-and-prepare") void importTab(tab.id, true);
});

chrome.tabs.onRemoved.addListener((tabId) => void clearTabState(tabId));

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  // A new page in the tab invalidates the previous import result.
  if (changeInfo.url) void clearTabState(tabId);
});

// ---------------------------------------------------------------------------
// Messaging
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message: Message, sender, respond) => {
  void handleMessage(message, sender).then(respond).catch((error) => {
    respond({ error: error instanceof Error ? error.message : String(error) });
  });
  return true;
});

async function handleMessage(message: Message, sender: chrome.runtime.MessageSender): Promise<unknown> {
  const tabId = sender.tab?.id ?? (await activeTabId());

  switch (message.type) {
    case "GET_CONFIG":
      return getConfig();

    case "GET_SESSION":
      return safe(() => jobAgentClient.getSession());

    case "GET_INBOX": {
      const force = (message.payload as { force?: boolean } | undefined)?.force ?? false;
      if (!force) {
        const cached = await getCachedInbox();
        if (cached) return { inbox: cached, cached: true };
      }
      const result = await safe(() => jobAgentClient.getInbox());
      if (!("error" in result) && result.value) {
        await cacheInbox(result.value);
        return { inbox: result.value, cached: false };
      }
      return result;
    }

    case "OPEN_SEARCH":
      return openSearch(message.payload as OpenSearchPayload);

    case "IMPORT_CURRENT_TAB": {
      if (!tabId) return { error: "No active tab." };
      const prepare = (message.payload as { prepare?: boolean } | undefined)?.prepare ?? false;
      return importTab(tabId, prepare);
    }

    case "PREPARE_JOB": {
      if (!tabId) return { error: "No active tab." };
      const jobId = (message.payload as { jobId?: string } | undefined)?.jobId;
      if (!jobId) return { error: "No job to prepare." };
      return prepareJob(tabId, jobId);
    }

    case "LOOKUP_CURRENT_TAB": {
      if (!tabId) return { found: false };
      const tab = await chrome.tabs.get(tabId);
      if (!tab.url) return { found: false };
      const existing = await getTabState(tabId);
      if (existing?.result) return { found: true, ...existing.result, fromState: true };

      // safe() wraps its result in { value }. Returning that shape here made the
      // panel read `found` as undefined and offer to import a job it already had.
      const lookup = await safe(() => jobAgentClient.lookupJob(tab.url as string));
      if ("error" in lookup) return { found: false, error: lookup.error };
      return lookup.value;
    }

    case "GET_TAB_STATE":
      return tabId ? getTabState(tabId) : null;

    case "ASK_ASSISTANT": {
      const ask = message.payload as {
        question: string;
        jobId?: string | null;
        history?: { role: string; content: string }[];
      };
      const pageContext = tabId ? await readPageContext(tabId) : "";
      return safe(() =>
        jobAgentClient.askAssistant({
          question: ask.question,
          jobId: ask.jobId ?? null,
          pageContext,
          history: ask.history ?? [],
        }),
      );
    }

    case "REMEMBER_ANSWER": {
      const payload = message.payload as { question: string; answer: string };
      return safe(() => jobAgentClient.rememberAnswer(payload.question, payload.answer));
    }

    case "SCAN_FORM": {
      if (!tabId) return { questions: [] };
      try {
        return await chrome.tabs.sendMessage(tabId, { type: "SCAN_FORM" });
      } catch {
        return { questions: [] };
      }
    }

    case "FILL_FIELD": {
      if (!tabId) return { ok: false };
      try {
        return await chrome.tabs.sendMessage(tabId, {
          type: "FILL_FIELD",
          payload: message.payload,
        });
      } catch {
        return { ok: false };
      }
    }

    case "FORM_DETECTED": {
      // Forwarded straight to the panel. The badge is the only side effect:
      // nothing is sent to the backend until the user asks for an answer.
      const payload = message.payload as { questions?: unknown[] } | undefined;
      const count = payload?.questions?.length ?? 0;
      if (tabId && count) {
        await chrome.action
          .setBadgeText({ tabId, text: String(count) })
          .catch(() => undefined);
        await chrome.action
          .setBadgeBackgroundColor({ tabId, color: "#f59e0b" })
          .catch(() => undefined);
      }
      chrome.runtime
        .sendMessage({ type: "FORM_DETECTED", payload: message.payload })
        .catch(() => undefined);
      return { ok: true };
    }

    case "RECORD_OUTCOME": {
      const payload = message.payload as { jobId: string; outcome: string; note?: string };
      const recorded = await safe(() =>
        jobAgentClient.recordOutcome(payload.jobId, payload.outcome, payload.note ?? ""),
      );
      if (!("error" in recorded) && tabId) {
        // Refresh the card so it shows the new status straight away.
        const status = await safe(() => jobAgentClient.getImportStatus(payload.jobId));
        if (!("error" in status)) await publish(tabId, { phase: "done", result: status.value });
      }
      return recorded;
    }

    case "SUBMISSION_DETECTED": {
      if (!tabId) return { ok: false };
      return handleSubmissionDetected(tabId, message.payload as SubmissionDetectedPayload);
    }

    case "UNDO_OUTCOME": {
      const payload = message.payload as { jobId: string };
      const undone = await safe(() => jobAgentClient.undoOutcome(payload.jobId));
      if (!("error" in undone) && tabId) {
        const status = await safe(() => jobAgentClient.getImportStatus(payload.jobId));
        if (!("error" in status)) await publish(tabId, { phase: "done", result: status.value });
      }
      return undone;
    }

    case "OPEN_DASHBOARD":
      return openDashboard((message.payload as string | null) ?? null);

    case "OPEN_SIDE_PANEL": {
      const windowId = sender.tab?.windowId ?? chrome.windows.WINDOW_ID_CURRENT;
      await chrome.sidePanel?.open?.({ windowId });
      return { ok: true };
    }

    default:
      return { error: `Unknown message: ${message.type}` };
  }
}

async function activeTabId(): Promise<number | undefined> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id;
}

type SafeResult<T> = { value: T } | { error: string; needsPairing?: boolean };

async function safe<T>(action: () => Promise<T>): Promise<SafeResult<T>> {
  try {
    return { value: await action() };
  } catch (error) {
    if (error instanceof JobAgentApiError) {
      return { error: error.message, needsPairing: error.needsPairing };
    }
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

// ---------------------------------------------------------------------------
// Searches
// ---------------------------------------------------------------------------

interface OpenSearchPayload {
  queryId: string | null;
  provider: string;
  url: string | null;
  query: string;
  location?: string | null;
  remote?: boolean | null;
}

async function openSearch(payload: OpenSearchPayload): Promise<{ ok: boolean; url: string }> {
  const url = resolveSearchUrl(
    payload.provider,
    { query: payload.query, location: payload.location, remote: payload.remote },
    payload.url,
  );

  const tab = await chrome.tabs.create({ url, active: true });

  // Remember which search produced this tab, so an import from it can be
  // attributed to the query that surfaced the job.
  if (tab.id) {
    await setAttribution(tab.id, {
      queryId: payload.queryId,
      provider: payload.provider,
      openedAt: Date.now(),
    });
  }
  if (payload.queryId) {
    void jobAgentClient.recordSearchOpened(payload.queryId).catch(() => undefined);
  }
  return { ok: true, url };
}

async function openDashboard(jobId: string | null): Promise<{ ok: boolean }> {
  const config = await getConfig();
  const session = await safe(() => jobAgentClient.getSession());
  const base =
    "value" in session && session.value.dashboardUrl
      ? session.value.dashboardUrl.replace(/\/+$/, "")
      : config.apiBaseUrl.replace(":8000", ":3000");
  const url = jobId ? `${base}/?job=${encodeURIComponent(jobId)}` : base;
  await chrome.tabs.create({ url, active: true });
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Import
// ---------------------------------------------------------------------------

async function importTab(tabId: number, requestedPrepare: boolean): Promise<unknown> {
  if (!(await isPaired())) {
    const state = await publish(tabId, {
      phase: "error",
      error: "Job Agent is not paired. Open the extension options to add a token.",
    });
    void chrome.runtime.openOptionsPage();
    return state;
  }

  // "Import Job" prepares the CV too when the profile says so, which is the
  // flow where you import an offer and immediately have a PDF to upload.
  let prepare = requestedPrepare;
  if (!prepare) {
    const session = await safe(() => jobAgentClient.getSession());
    if (!("error" in session)) prepare = session.value.importPreparesApplication === true;
  }

  const tab = await chrome.tabs.get(tabId).catch(() => undefined);
  const restricted = restrictedReason(tab?.url);
  if (restricted) {
    return publish(tabId, { phase: "error", error: restricted });
  }

  await publish(tabId, { phase: "capturing" });

  const capture = await capturePage(tabId);
  if ("reason" in capture) {
    return publish(tabId, { phase: "error", error: capture.reason });
  }

  const attribution = await getAttribution(tabId);
  const payload: CapturePayload = {
    ...capture,
    prepareApplication: prepare,
    discoveredBy: "browser-extension",
    searchQueryId: attribution?.queryId ?? null,
    searchProvider: attribution?.provider ?? null,
  };

  await publish(tabId, { phase: "importing" });

  const imported = await safe(() => jobAgentClient.importJob(payload));
  if ("error" in imported) {
    return publish(tabId, { phase: "error", error: imported.error });
  }

  const result = imported.value;
  if (result.status === "duplicate" || result.analysisState === "complete") {
    await badge(tabId, result);
    // An already-imported job still has to honour a prepare request, otherwise
    // the button does nothing at all on the second click.
    if (prepare && result.jobId && !result.applicationRunId) {
      return prepareJob(tabId, result.jobId, result);
    }
    return publish(tabId, { phase: "done", result });
  }

  await publish(tabId, { phase: "analyzing", result });
  void pollAnalysis(tabId, result);
  return result;
}

/** Prepares the application documents for a job that is already imported. */
async function prepareJob(
  tabId: number,
  jobId: string,
  known?: ImportResult,
): Promise<unknown> {
  if (!(await isPaired())) {
    return publish(tabId, {
      phase: "error",
      error: "Job Agent is not paired. Open the extension options to add a token.",
    });
  }

  const current = known ?? (await getTabState(tabId))?.result;
  await publish(tabId, { phase: "preparing", result: current });

  const queued = await safe(() => jobAgentClient.prepareApplication(jobId));
  if ("error" in queued) {
    return publish(tabId, { phase: "error", error: queued.error });
  }

  void pollPreparation(tabId, jobId);
  return { ok: true };
}

/** Waits for the application run to appear, which is when the CV is ready. */
async function pollPreparation(tabId: number, jobId: string): Promise<void> {
  for (let attempt = 0; attempt < PREPARE_POLL_ATTEMPTS; attempt += 1) {
    await delay(PREPARE_POLL_INTERVAL_MS);
    const status = await safe(() => jobAgentClient.getImportStatus(jobId));
    if ("error" in status) continue;

    const result = status.value;
    if (result.preparationState === "failed" || result.preparationState === "skipped") {
      await publish(tabId, {
        phase: "error",
        error: result.preparationError || "No se pudo preparar el CV.",
        result,
      });
      return;
    }
    if (result.applicationRunId && result.preparationState === "ready") {
      await badge(tabId, result);
      await publish(tabId, { phase: "done", result });
      void notify(result);
      return;
    }
    await publish(tabId, { phase: "preparing", result });
  }

  const last = await safe(() => jobAgentClient.getImportStatus(jobId));
  if ("error" in last) {
    return void publish(tabId, { phase: "error", error: last.error });
  }
  // Reverting to the button with no explanation is what made this confusing.
  const reason =
    last.value.preparationError ||
    "La preparación está tardando más de lo normal. Revisa que el worker esté en marcha.";
  await publish(tabId, {
    phase: "error",
    error: reason,
    result: last.value,
  });
}

/** A short excerpt of the page, so the assistant sees the form around the field.
 *
 * Best effort by design: on a page with no content script this returns nothing
 * rather than asking for permission the user did not offer.
 */
async function readPageContext(tabId: number): Promise<string> {
  try {
    const response = (await chrome.tabs.sendMessage(tabId, { type: "READ_PAGE_CONTEXT" })) as
      | { text?: string }
      | undefined;
    return (response?.text ?? "").slice(0, 4000);
  } catch {
    return "";
  }
}

interface SubmissionDetectedPayload {
  url: string;
  title: string;
  evidence: { matched: string; excerpt: string; source: string };
}

/** Statuses that already mean the application went out. */
const SENT_STATUSES = ["APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"];

/**
 * Records an application the page says was sent.
 *
 * Only for a job already in Job Agent: without one there is nothing to mark, and
 * importing a page on the strength of a confirmation banner would be guessing at
 * which job it even belongs to. In that case the panel offers the choice instead.
 */
async function handleSubmissionDetected(
  tabId: number,
  payload: SubmissionDetectedPayload,
): Promise<unknown> {
  if (!(await isPaired())) return { ok: false };

  const state = await getTabState(tabId);
  let result = state?.result;

  if (!result?.jobId) {
    const lookup = await safe(() => jobAgentClient.lookupJob(payload.url));
    if (!("error" in lookup) && lookup.value.found) {
      result = lookup.value as ImportResult;
    }
  }

  if (!result?.jobId) {
    // Nothing to mark yet. The panel shows the offer to import and record.
    chrome.runtime
      .sendMessage({ type: "SUBMISSION_DETECTED", payload })
      .catch(() => undefined);
    return { ok: false, reason: "not-imported" };
  }

  if (SENT_STATUSES.includes(result.jobStatus ?? "")) {
    return { ok: true, reason: "already-recorded" };
  }

  const note = `Detectado automáticamente en la página: "${payload.evidence.excerpt}"`;
  const recorded = await safe(() =>
    jobAgentClient.recordOutcome(result.jobId as string, "applied", note),
  );
  if ("error" in recorded) return { ok: false, reason: recorded.error };

  const refreshed = await safe(() => jobAgentClient.getImportStatus(result.jobId as string));
  if (!("error" in refreshed)) {
    await publish(tabId, { phase: "done", result: refreshed.value });
  }

  chrome.runtime
    .sendMessage({ type: "SUBMISSION_DETECTED", payload: { ...payload, recorded: true } })
    .catch(() => undefined);

  try {
    await chrome.notifications.create({
      type: "basic",
      iconUrl: chrome.runtime.getURL("icon-128.png"),
      title: "Candidatura marcada como enviada",
      message: `${result.company} — ${result.role}. Puedes deshacerlo en el panel.`,
    });
  } catch {
    // Notifications are optional.
  }
  return { ok: true, recorded: true };
}

interface CaptureFailure {
  reason: string;
}

const RESTRICTED_SCHEME = /^(chrome|edge|about|devtools|view-source|file|chrome-extension|moz-extension):/i;
const RESTRICTED_HOST = /(^|\.)chromewebstore\.google\.com$|(^|\.)chrome\.google\.com$/i;

/** Pages no extension may read, whatever its permissions. */
function restrictedReason(url: string | undefined): string | null {
  if (!url) return "Job Agent cannot read this tab.";
  if (RESTRICTED_SCHEME.test(url)) {
    return "Job Agent cannot read browser pages. Open a job posting first.";
  }
  try {
    if (RESTRICTED_HOST.test(new URL(url).hostname)) {
      return "Chrome does not let extensions read the Web Store.";
    }
  } catch {
    return "Job Agent cannot read this tab.";
  }
  return null;
}

/** Sends the capture request, injecting the content script if it is not there. */
async function capturePage(tabId: number): Promise<CapturePayload | CaptureFailure> {
  const ask = async (): Promise<CapturePayload | null> => {
    try {
      const response = (await chrome.tabs.sendMessage(tabId, { type: "CAPTURE_PAGE" })) as
        | CapturePayload
        | { error: string }
        | undefined;
      if (!response || "error" in response) return null;
      return response;
    } catch {
      // No listener in the page: either the site is not in the manifest, or the
      // extension was reloaded and the tab's old content script is orphaned.
      return null;
    }
  };

  const first = await ask();
  if (first) return first;

  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  } catch {
    // Chrome refuses to inject without host permission, and the side panel is
    // not one of the gestures that grant activeTab. Both fixes are the user's.
    return {
      reason:
        "Reload this page and try again. If it keeps failing, import from the " +
        "Job Agent toolbar icon or the right-click menu.",
    };
  }

  // The freshly injected script registers its listener as it evaluates, which
  // can land a moment after executeScript resolves.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const retry = await ask();
    if (retry) return retry;
    await delay(250);
  }

  return {
    reason:
      "Reload this page and try again. Job Agent could not read it in its current state.",
  };
}

async function pollAnalysis(tabId: number, initial: ImportResult): Promise<void> {
  if (!initial.jobId) return;

  for (let attempt = 0; attempt < ANALYSIS_POLL_ATTEMPTS; attempt += 1) {
    await delay(ANALYSIS_POLL_INTERVAL_MS);
    const status = await safe(() => jobAgentClient.getImportStatus(initial.jobId as string));
    if ("error" in status) continue;

    const result = status.value;
    if (result.analysisState === "complete" || result.analysisState === "failed") {
      await badge(tabId, result);
      await publish(tabId, { phase: "done", result });
      void notify(result);
      return;
    }
    await publish(tabId, { phase: "analyzing", result });
  }

  await publish(tabId, {
    phase: "done",
    result: { ...initial, message: "Imported. The analysis is still running." },
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Writes tab state and pushes it to the content script and any open panel. */
async function publish(tabId: number, patch: Partial<TabState>): Promise<TabState> {
  const tab = await chrome.tabs.get(tabId).catch(() => undefined);
  const previous = await getTabState(tabId);
  const state: TabState = {
    tabId,
    url: tab?.url ?? previous?.url ?? "",
    phase: patch.phase ?? previous?.phase ?? "idle",
    result: patch.result ?? previous?.result,
    error: patch.phase === "error" ? patch.error : undefined,
    updatedAt: Date.now(),
  };
  await setTabState(state);

  chrome.tabs.sendMessage(tabId, { type: "SHOW_IMPORT_STATE", payload: state }).catch(
    () => undefined,
  );
  chrome.runtime.sendMessage({ type: "TAB_STATE_CHANGED", payload: state }).catch(
    () => undefined,
  );
  return state;
}

async function badge(tabId: number, result: ImportResult): Promise<void> {
  const score = result.matchScore;
  try {
    await chrome.action.setBadgeText({
      tabId,
      text: score === null || score === undefined ? "✓" : String(score),
    });
    await chrome.action.setBadgeBackgroundColor({
      tabId,
      color: score !== null && score !== undefined && score >= 80 ? "#059669" : "#4f46e5",
    });
  } catch {
    // Badges are cosmetic; a failure must never break an import.
  }
}

async function notify(result: ImportResult): Promise<void> {
  const score = result.matchScore;
  try {
    await chrome.notifications.create({
      type: "basic",
      iconUrl: chrome.runtime.getURL("icon-128.png"),
      title:
        score === null || score === undefined
          ? `Imported: ${result.role}`
          : `Match ${score}/100 — ${result.role}`,
      message: `${result.company}${result.primaryRole ? ` · ${result.primaryRole}` : ""}`,
    });
  } catch {
    // Notifications are optional.
  }
}
