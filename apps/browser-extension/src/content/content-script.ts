/** Content script: captures the page on request and shows the import control.
 *
 * It never scrapes on its own and never navigates. Capture happens only when the
 * user asks for it, through the button, the popup, the side panel, the context
 * menu or the keyboard shortcut.
 */

import { runExtraction } from "../extractors/index";
import { detectFormQuestions, fillField } from "./form-scanner";
import { detectSubmission } from "./submission-detector";
import {
  canonicalUrlHint,
  cleanedHtml,
  collectJsonLd,
  findContentRoot,
  visibleText,
} from "../shared/dom";
import { CapturePayload, Message, TabState } from "../shared/types";

function looksLikeJobPage(): boolean {
  const hasJobPostingLd = collectJsonLd().some((block) =>
    JSON.stringify(block).includes("JobPosting"),
  );
  if (hasJobPostingLd) return true;
  if (document.querySelector("[itemtype*='JobPosting']")) return true;

  const path = window.location.pathname;
  const singleJobPath =
    /\/jobs\/view\//.test(path) ||
    /\/(job|jobs|oferta|ofertas-trabajo|posting|positions?)\/[^/]+/.test(path) ||
    /viewjob/.test(window.location.search);
  if (!singleJobPath) return false;

  const content = findContentRoot();
  return (content.textContent ?? "").trim().length > 600;
}

function capture(): CapturePayload {
  const root = findContentRoot();
  const { extracted, strategy } = runExtraction(window.location.hostname);
  return {
    url: window.location.href,
    title: document.title,
    hostname: window.location.hostname,
    visibleText: visibleText(root),
    structuredData: collectJsonLd(),
    cleanedHtml: cleanedHtml(root),
    capturedAt: new Date().toISOString(),
    extracted,
    canonicalUrlHint: canonicalUrlHint(),
    extractionStrategy: strategy,
  };
}

// ---------------------------------------------------------------------------
// Injected control
// ---------------------------------------------------------------------------

const HOST_ID = "job-agent-host";
let shadow: ShadowRoot | null = null;

const PANEL_STYLE = `
  :host { all: initial; }
  .wrap {
    pointer-events: auto;
    font: 500 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    gap: 8px;
    align-items: center;
    background: #0f172a;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 8px;
    box-shadow: 0 10px 30px rgba(0,0,0,.35);
  }
  button {
    font: inherit;
    cursor: pointer;
    border: 0;
    border-radius: 8px;
    padding: 8px 12px;
    background: #4f46e5;
    color: #fff;
  }
  button.ghost { background: #1e293b; color: #cbd5e1; }
  button:hover { filter: brightness(1.1); }
  button:disabled { opacity: .6; cursor: default; }
  .score {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #064e3b;
    color: #6ee7b7;
    border-radius: 8px;
    padding: 8px 12px;
  }
  .muted { color: #94a3b8; padding: 0 4px; }
  .error { color: #fca5a5; padding: 0 4px; max-width: 240px; }
`;

function ensureShadow(): ShadowRoot {
  let host = document.getElementById(HOST_ID);
  if (!host) {
    host = document.createElement("div");
    host.id = HOST_ID;
    document.body.appendChild(host);
  }

  if (!shadow) {
    // Reloading the extension leaves the previous instance's host in the page.
    // Calling attachShadow on it again throws, so adopt the existing root.
    shadow = host.shadowRoot ?? host.attachShadow({ mode: "open" });
  }
  if (!shadow.querySelector(".wrap")) {
    shadow.replaceChildren();
    const style = document.createElement("style");
    style.textContent = PANEL_STYLE;
    shadow.appendChild(style);
    const wrap = document.createElement("div");
    wrap.className = "wrap";
    shadow.appendChild(wrap);
  }
  return shadow;
}

function removeControl(): void {
  document.getElementById(HOST_ID)?.remove();
  shadow = null;
}

function send<T>(message: Message<T>): Promise<unknown> {
  return chrome.runtime.sendMessage(message).catch(() => undefined);
}

function render(state: TabState | null): void {
  const root = ensureShadow();
  const wrap = root.querySelector(".wrap");
  if (!wrap) return;
  wrap.replaceChildren();

  const addButton = (label: string, onClick: () => void, ghost = false) => {
    const button = document.createElement("button");
    button.textContent = label;
    if (ghost) button.className = "ghost";
    button.addEventListener("click", onClick);
    wrap.appendChild(button);
    return button;
  };

  const phase = state?.phase ?? "idle";

  if (phase === "capturing" || phase === "importing") {
    const span = document.createElement("span");
    span.className = "muted";
    span.textContent = "Importing…";
    wrap.appendChild(span);
    return;
  }

  if (phase === "analyzing" || phase === "preparing") {
    const span = document.createElement("span");
    span.className = "muted";
    span.textContent =
      phase === "preparing" ? "✓ Imported · preparing CV…" : "✓ Imported · analysing…";
    wrap.appendChild(span);
    addButton("Open", () => send({ type: "OPEN_DASHBOARD", payload: state?.result?.jobId }), true);
    return;
  }

  if (phase === "done" && state?.result) {
    const result = state.result;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent =
      result.matchScore === null || result.matchScore === undefined
        ? "✓ Job Agent"
        : `✓ Job Agent · Match ${result.matchScore}`;
    wrap.appendChild(score);
    addButton("Open", () => send({ type: "OPEN_DASHBOARD", payload: result.jobId }), true);
    if (!result.applicationRunId) {
      addButton(
        "Prepare CV",
        () => void send({ type: "PREPARE_JOB", payload: { jobId: result.jobId } }),
        true,
      );
    }
    return;
  }

  if (phase === "error") {
    const span = document.createElement("span");
    span.className = "error";
    span.textContent = state?.error ?? "Import failed";
    wrap.appendChild(span);
    addButton("Retry", () => send({ type: "IMPORT_CURRENT_TAB", payload: { prepare: false } }));
    return;
  }

  addButton(
    "Import to Job Agent",
    () => void send({ type: "IMPORT_CURRENT_TAB", payload: { prepare: false } }),
  );
  addButton(
    "Import + Prepare",
    () => void send({ type: "IMPORT_CURRENT_TAB", payload: { prepare: true } }),
    true,
  );
}

async function refresh(): Promise<void> {
  if (!looksLikeJobPage()) {
    removeControl();
    return;
  }
  const config = (await send({ type: "GET_CONFIG" })) as
    | { injectPageButton?: boolean }
    | undefined;
  if (config && config.injectPageButton === false) {
    removeControl();
    return;
  }
  const state = (await send({ type: "GET_TAB_STATE" })) as TabState | null;
  render(state ?? null);
}

chrome.runtime.onMessage.addListener((message: Message, _sender, respond) => {
  if (message.type === "CAPTURE_PAGE") {
    try {
      respond(capture());
    } catch (error) {
      respond({ error: error instanceof Error ? error.message : String(error) });
    }
    return true;
  }
  if (message.type === "SCAN_FORM") {
    try {
      respond({ questions: detectFormQuestions() });
    } catch {
      respond({ questions: [] });
    }
    return true;
  }
  if (message.type === "FILL_FIELD") {
    const payload = message.payload as { fieldId?: string; value?: string } | undefined;
    respond({ ok: fillField(payload?.fieldId ?? "", payload?.value ?? "") });
    return true;
  }
  if (message.type === "READ_PAGE_CONTEXT") {
    try {
      respond({ text: visibleText(findContentRoot()).slice(0, 4000) });
    } catch {
      respond({ text: "" });
    }
    return true;
  }
  if (message.type === "SHOW_IMPORT_STATE") {
    render((message.payload as TabState) ?? null);
    return false;
  }
  return false;
});

/**
 * Watches for an application form appearing and announces it once.
 *
 * Announcing is all it does: the questions travel no further until the user
 * asks for help with one. Detection is local, so nothing leaves the page here.
 */
let announcedCount = -1;

function announceForm(): void {
  let questions: ReturnType<typeof detectFormQuestions> = [];
  try {
    questions = detectFormQuestions();
  } catch {
    return;
  }
  if (questions.length === announcedCount) return;
  announcedCount = questions.length;
  if (!questions.length) return;

  void send({
    type: "FORM_DETECTED",
    payload: { url: window.location.href, questions },
  });
}

/** Tells the extension once when this page shows an application confirmation. */
let announcedSubmission = false;

function announceSubmission(): void {
  if (announcedSubmission) return;
  let evidence: ReturnType<typeof detectSubmission> = null;
  try {
    evidence = detectSubmission();
  } catch {
    return;
  }
  if (!evidence) return;

  announcedSubmission = true;
  void send({
    type: "SUBMISSION_DETECTED",
    payload: { url: window.location.href, title: document.title, evidence },
  });
}

// Job boards are single-page apps: the URL changes without a reload.
let lastUrl = window.location.href;
window.setInterval(() => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    announcedCount = -1;
    announcedSubmission = false;
    void refresh();
  }
  announceForm();
  announceSubmission();
}, 1200);

void refresh();
announceForm();
announceSubmission();
