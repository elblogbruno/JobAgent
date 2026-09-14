/** The side panel: Job Agent stays visible while you browse and apply.
 *
 * Two tabs, because the panel does two unrelated things. "Esta oferta" follows
 * the page you are on, in the order you actually work: read the job, answer the
 * form, ask for help, record that you sent it. "Búsquedas" is the daily slate.
 */

import {
  assistantAnswerToMessage,
  element,
  notice,
  renderChatMessage,
  renderImportCard,
  renderInbox,
  renderTotals,
  send,
} from "../shared/ui";
import {
  AssistantAnswer,
  ChatMessage,
  FormQuestion,
  ImportResult,
  SearchInbox,
  SearchRow,
  SessionInfo,
  SubmissionEvidence,
  TabState,
} from "../shared/types";
import { isJobLikeUrl } from "../shared/types";

const statusEl = document.getElementById("status") as HTMLElement;
const currentEl = document.getElementById("current") as HTMLElement;
const inboxEl = document.getElementById("inbox") as HTMLElement;
const totalsEl = document.getElementById("totals") as HTMLElement;
const formBlock = document.getElementById("form-block") as HTMLElement;
const formHint = document.getElementById("form-hint") as HTMLElement;
const formEl = document.getElementById("form-questions") as HTMLElement;
const sentEl = document.getElementById("sent-controls") as HTMLElement;
const chatLog = document.getElementById("chat-log") as HTMLElement;
const chatInput = document.getElementById("chat-question") as HTMLTextAreaElement;
const chatSend = document.getElementById("chat-send") as HTMLButtonElement;

let session: SessionInfo | null = null;
let apiBaseUrl = "";

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

const jobPanel = document.getElementById("panel-job") as HTMLElement;
const searchesPanel = document.getElementById("panel-searches") as HTMLElement;
const jobTab = document.getElementById("tab-job") as HTMLButtonElement;
const searchesTab = document.getElementById("tab-searches") as HTMLButtonElement;

function showTab(which: "job" | "searches"): void {
  jobPanel.hidden = which !== "job";
  searchesPanel.hidden = which !== "searches";
  jobTab.classList.toggle("active", which === "job");
  searchesTab.classList.toggle("active", which === "searches");
}

jobTab.addEventListener("click", () => showTab("job"));
searchesTab.addEventListener("click", () => showTab("searches"));

document.getElementById("options")?.addEventListener("click", () => chrome.runtime.openOptionsPage());
document.getElementById("refresh")?.addEventListener("click", () => {
  void loadInbox(true);
  void renderCurrent();
  void scanForm();
});

// ---------------------------------------------------------------------------
// Step 1: the job on this page
// ---------------------------------------------------------------------------

/**
 * Import publishes several state changes in quick succession, each triggering a
 * render. They are async, so without a token the slower one lands after the
 * newer one and the panel shows the same block twice.
 */
let renderToken = 0;
let currentResult: ImportResult | undefined;

function showBusy(text: string): void {
  renderToken += 1;
  currentEl.replaceChildren(notice(text));
}

async function renderCurrent(): Promise<void> {
  const token = ++renderToken;
  const built = await buildCurrent();
  if (token !== renderToken) return;
  currentEl.replaceChildren(built);
  renderSentControls();
}

async function buildCurrent(): Promise<HTMLElement> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/i.test(tab.url)) {
    currentResult = undefined;
    return notice("Abre una oferta de empleo para empezar.");
  }

  const state = (await send<TabState | null>({ type: "GET_TAB_STATE" })) ?? null;
  const lookup = await send<{ found?: boolean } & Partial<ImportResult>>({
    type: "LOOKUP_CURRENT_TAB",
  });

  const existing: ImportResult | undefined =
    state?.result ?? (lookup?.found ? (lookup as ImportResult) : undefined);
  currentResult = existing;

  if (existing) {
    return renderImportCard(existing, {
      phase: state?.phase ?? "done",
      highThreshold: session?.highMatchThreshold,
      apiBaseUrl,
      onOpenDashboard: () => void send({ type: "OPEN_DASHBOARD", payload: existing.jobId }),
      onPrepare: () => void prepareCv(existing),
    });
  }

  if (state?.phase === "error") return notice(state.error ?? "No se pudo importar", true);
  if (state?.phase === "preparing") return notice("Preparando el CV…");
  if (state?.phase === "capturing" || state?.phase === "importing") return notice("Importando…");

  if (!isJobLikeUrl(tab.url)) {
    return notice("Esta página no parece una oferta. Abre una, o mira tus búsquedas.");
  }

  const card = element("div", "card");
  card.append(element("div", "label", tab.title ?? "Esta página"));
  card.append(element("div", "meta", new URL(tab.url).hostname));
  const actions = element("div", "actions");
  const importButton = element("button", undefined, "Importar oferta");
  importButton.addEventListener("click", () => void importCurrent(false));
  const prepareButton = element("button", "ghost", "Importar y preparar CV");
  prepareButton.addEventListener("click", () => void importCurrent(true));
  actions.append(importButton, prepareButton);
  card.append(actions);
  return card;
}

async function importCurrent(prepare: boolean): Promise<void> {
  showBusy(prepare ? "Importando y preparando…" : "Importando…");
  await send({ type: "IMPORT_CURRENT_TAB", payload: { prepare } });
  await renderCurrent();
}

/** Prepares the CV for a job already in Job Agent, without re-reading the page. */
async function prepareCv(result: ImportResult): Promise<void> {
  if (!result.jobId) return;
  showBusy("Preparando el CV…");
  await send({ type: "PREPARE_JOB", payload: { jobId: result.jobId } });
  await renderCurrent();
}

// ---------------------------------------------------------------------------
// Step 4: recording that you sent it
// ---------------------------------------------------------------------------

const SENT_STATUSES = ["APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"];

/** Set when this page announced a confirmation, so the panel can explain itself. */
let detectedSubmission: { evidence: SubmissionEvidence; recorded: boolean } | null = null;

function renderSentControls(): void {
  sentEl.replaceChildren();

  if (!currentResult?.jobId) {
    sentEl.append(element("div", "meta", "Importa la oferta primero."));
    return;
  }

  const status = currentResult.jobStatus ?? "";
  if (SENT_STATUSES.includes(status)) {
    if (detectedSubmission?.recorded) {
      const box = element("div", "notice");
      box.textContent =
        "Marcada como enviada automáticamente: la página confirmó el envío.\n" +
        `"${detectedSubmission.evidence.excerpt}"`;
      box.style.whiteSpace = "pre-line";
      sentEl.append(box);
    } else {
      sentEl.append(notice(`Ya registrada como ${status}.`));
    }

    // Automatic detection can be wrong, and a mis-click should not be permanent.
    const actions = element("div", "actions");
    const undo = element("button", "ghost", "Deshacer");
    undo.addEventListener("click", async () => {
      if (!currentResult?.jobId) return;
      undo.disabled = true;
      undo.textContent = "Deshaciendo…";
      const result = await send<{ error?: string }>({
        type: "UNDO_OUTCOME",
        payload: { jobId: currentResult.jobId },
      });
      if (result?.error) {
        sentEl.replaceChildren(notice(result.error, true));
        return;
      }
      detectedSubmission = null;
      await renderCurrent();
    });
    actions.append(undo);
    sentEl.append(actions);
    return;
  }

  if (detectedSubmission && !detectedSubmission.recorded) {
    const box = element("div", "notice");
    box.textContent =
      "Parece que enviaste esta solicitud, pero la oferta no está importada todavía.\n" +
      `"${detectedSubmission.evidence.excerpt}"`;
    box.style.whiteSpace = "pre-line";
    sentEl.append(box);

    const actions = element("div", "actions");
    const importAndMark = element("button", undefined, "Importar y marcar como enviada");
    importAndMark.addEventListener("click", async () => {
      importAndMark.disabled = true;
      importAndMark.textContent = "Importando…";
      await send({ type: "IMPORT_CURRENT_TAB", payload: { prepare: false } });
      await renderCurrent();
      if (currentResult?.jobId) {
        await send({
          type: "RECORD_OUTCOME",
          payload: {
            jobId: currentResult.jobId,
            outcome: "applied",
            note: `Detectado en la página: "${detectedSubmission?.evidence.excerpt ?? ""}"`,
          },
        });
        await renderCurrent();
      }
    });
    actions.append(importAndMark);
    sentEl.append(actions);
    return;
  }

  const note = element("input");
  note.type = "text";
  note.placeholder = "Nota opcional: fecha, contacto, portal…";
  sentEl.append(note);

  const actions = element("div", "actions");
  const button = element("button", undefined, "La envié yo");
  button.addEventListener("click", async () => {
    if (!currentResult?.jobId) return;
    button.disabled = true;
    button.textContent = "Registrando…";

    const result = await send<{ error?: string }>({
      type: "RECORD_OUTCOME",
      payload: { jobId: currentResult.jobId, outcome: "applied", note: note.value.trim() },
    });

    if (result?.error) {
      sentEl.replaceChildren(notice(result.error, true));
      return;
    }
    await renderCurrent();
  });
  actions.append(button);
  sentEl.append(actions);
}

// ---------------------------------------------------------------------------
// Step 2: the questions this form is asking
// ---------------------------------------------------------------------------

let detected: FormQuestion[] = [];
const drafted = new Map<string, AssistantAnswer>();

function copyToClipboard(text: string): void {
  void navigator.clipboard.writeText(text).catch(() => undefined);
}

function rememberAnswer(question: string, answer: string): void {
  void send({ type: "REMEMBER_ANSWER", payload: { question, answer } });
}

async function answerQuestion(question: FormQuestion, row: HTMLElement): Promise<void> {
  const status = element("div", "chat-note", "Redactando…");
  row.append(status);

  const prompt = question.options.length
    ? `${question.label}\nElige una de: ${question.options.join(" | ")}`
    : question.label;

  const result = await send<{ value?: AssistantAnswer; error?: string }>({
    type: "ASK_ASSISTANT",
    payload: { question: prompt, jobId: currentResult?.jobId ?? null, history: [] },
  });

  if (result?.error || !result?.value) {
    status.className = "chat-warning";
    status.textContent = result?.error ?? "No se pudo contactar con Job Agent.";
    return;
  }

  drafted.set(question.id, result.value);
  renderDetected();

  conversation.push({ role: "user", content: question.label });
  conversation.push(assistantAnswerToMessage(result.value));
  renderChat();
}

function renderDetected(): void {
  formEl.replaceChildren();
  formBlock.hidden = detected.length === 0;
  if (!detected.length) return;

  const pending = detected.filter((question) => !question.filled).length;
  formHint.textContent =
    `${detected.length} pregunta(s) detectadas, ${pending} sin rellenar. ` +
    "Redacto una, la revisas, y la escribo en el campo.";

  for (const question of detected) {
    const row = element("div", "row");
    const label = element("div", "label");
    label.textContent = question.label.slice(0, 160);
    if (question.required) {
      const pill = element("span", "pill", "obligatoria");
      pill.style.marginLeft = "6px";
      label.append(pill);
    }
    row.append(label);

    const draft = drafted.get(question.id);
    if (draft) {
      const body = element("div", "chat-body");
      body.textContent = draft.answer;
      body.style.marginTop = "6px";
      row.append(body);
      for (const warning of draft.warnings) {
        row.append(element("div", "chat-warning", `Revisa esto: ${warning}`));
      }
      if (draft.source === "vault") {
        row.append(element("div", "chat-note", "De tus respuestas guardadas."));
      }
    }

    const actions = element("div", "targets");
    if (!draft) {
      const ask = element("button", "ghost small", question.filled ? "Reescribir" : "Redactar");
      ask.addEventListener("click", () => {
        ask.disabled = true;
        void answerQuestion(question, row);
      });
      actions.append(ask);
    } else {
      const fill = element("button", "small", "Rellenar");
      fill.addEventListener("click", async () => {
        const response = await send<{ ok?: boolean }>({
          type: "FILL_FIELD",
          payload: { fieldId: question.id, value: draft.answer },
        });
        fill.textContent = response?.ok ? "Rellenado" : "No se pudo";
        fill.disabled = true;
      });
      const copy = element("button", "ghost small", "Copiar");
      copy.addEventListener("click", () => copyToClipboard(draft.answer));
      const redo = element("button", "ghost small", "Rehacer");
      redo.addEventListener("click", () => {
        drafted.delete(question.id);
        renderDetected();
      });
      actions.append(fill, copy, redo);
    }
    row.append(actions);
    formEl.append(row);
  }
}

async function scanForm(): Promise<void> {
  const response = await send<{ questions?: FormQuestion[] }>({ type: "SCAN_FORM" });
  const questions = response?.questions ?? [];
  // A different page means the drafts no longer belong to anything.
  if (questions.map((q) => q.id).join("|") !== detected.map((q) => q.id).join("|")) {
    drafted.clear();
  }
  detected = questions;
  renderDetected();
}

// ---------------------------------------------------------------------------
// Step 3: the chat
// ---------------------------------------------------------------------------

let conversation: ChatMessage[] = [];
let asking = false;

function renderChat(): void {
  chatLog.replaceChildren();
  conversation.forEach((message, index) => {
    // The question an answer belongs to is the turn before it.
    const question = conversation[index - 1]?.content ?? "";
    chatLog.append(
      renderChatMessage(message, copyToClipboard, (text) => rememberAnswer(question, text)),
    );
  });
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function ask(): Promise<void> {
  const question = chatInput.value.trim();
  if (!question || asking) return;

  asking = true;
  chatSend.disabled = true;
  chatSend.textContent = "Pensando…";
  conversation.push({ role: "user", content: question });
  chatInput.value = "";
  renderChat();

  const result = await send<{ value?: AssistantAnswer; error?: string }>({
    type: "ASK_ASSISTANT",
    payload: {
      question,
      jobId: currentResult?.jobId ?? null,
      history: conversation.slice(0, -1).map((turn) => ({
        role: turn.role,
        content: turn.content,
      })),
    },
  });

  conversation.push(
    result?.error || !result?.value
      ? { role: "assistant", content: result?.error ?? "No se pudo contactar con Job Agent." }
      : assistantAnswerToMessage(result.value),
  );

  asking = false;
  chatSend.disabled = false;
  chatSend.textContent = "Preguntar";
  renderChat();
}

chatSend?.addEventListener("click", () => void ask());
chatInput?.addEventListener("keydown", (event) => {
  // Enter sends, Shift+Enter writes a new line.
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void ask();
  }
});
document.getElementById("chat-clear")?.addEventListener("click", () => {
  conversation = [];
  renderChat();
});

/** A question sent from the page's right-click menu lands here. */
function prefill(question: string): void {
  showTab("job");
  chatInput.value = question;
  chatInput.focus();
}

void chrome.storage.session.get("assistantPrefill").then((stored) => {
  const entry = stored.assistantPrefill as { question?: string; at?: number } | undefined;
  if (entry?.question && Date.now() - (entry.at ?? 0) < 60_000) {
    prefill(entry.question);
    void chrome.storage.session.remove("assistantPrefill");
  }
});

// ---------------------------------------------------------------------------
// Searches
// ---------------------------------------------------------------------------

function openSearch(row: SearchRow, targetIndex: number): void {
  const target = row.targets[targetIndex];
  void send({
    type: "OPEN_SEARCH",
    payload: {
      queryId: target.queryId,
      provider: target.provider,
      url: target.url,
      query: row.query,
      location: row.location,
      remote: row.remote,
    },
  });
}

async function loadInbox(force = false): Promise<void> {
  // The download link points straight at the API, so the panel needs its URL.
  const config = await send<{ apiBaseUrl?: string }>({ type: "GET_CONFIG" });
  apiBaseUrl = (config?.apiBaseUrl ?? "").replace(/\/+$/, "");

  const sessionResult = await send<{ value?: SessionInfo; error?: string; needsPairing?: boolean }>(
    { type: "GET_SESSION" },
  );

  if (sessionResult?.error) {
    statusEl.replaceChildren(notice(sessionResult.error, true));
    if (sessionResult.needsPairing) {
      const button = element("button", undefined, "Abrir ajustes");
      button.style.marginTop = "10px";
      button.addEventListener("click", () => chrome.runtime.openOptionsPage());
      statusEl.append(button);
    }
    inboxEl.replaceChildren();
    return;
  }

  session = sessionResult?.value ?? null;
  statusEl.replaceChildren(
    element(
      "div",
      "meta",
      session?.primaryRole
        ? `${session.candidateName} · rol principal: ${session.primaryRole}`
        : (session?.candidateName ?? ""),
    ),
  );

  const inboxResult = await send<{ inbox?: SearchInbox; error?: string }>({
    type: "GET_INBOX",
    payload: { force },
  });

  if (inboxResult?.error || !inboxResult?.inbox) {
    inboxEl.replaceChildren(
      notice(inboxResult?.error ?? "No se pudieron cargar las búsquedas.", true),
    );
    return;
  }

  inboxEl.replaceChildren(renderInbox(inboxResult.inbox, openSearch));
  totalsEl.replaceChildren(renderTotals(inboxResult.inbox));
}

// ---------------------------------------------------------------------------

chrome.tabs.onActivated.addListener(() => {
  void renderCurrent();
  void scanForm();
});
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (changeInfo.url) detectedSubmission = null;
  if (tab.active && changeInfo.status === "complete") {
    void renderCurrent();
    void scanForm();
  }
});
chrome.runtime.onMessage.addListener((message: { type?: string; payload?: unknown }) => {
  if (message?.type === "TAB_STATE_CHANGED") void renderCurrent();
  if (message?.type === "ASSISTANT_PREFILL") {
    const payload = message.payload as { question?: string } | undefined;
    if (payload?.question) prefill(payload.question);
  }
  if (message?.type === "SUBMISSION_DETECTED") {
    const payload = message.payload as
      | { evidence?: SubmissionEvidence; recorded?: boolean }
      | undefined;
    if (payload?.evidence) {
      detectedSubmission = { evidence: payload.evidence, recorded: Boolean(payload.recorded) };
      showTab("job");
      void renderCurrent();
    }
  }
  if (message?.type === "FORM_DETECTED") {
    const payload = message.payload as { questions?: FormQuestion[] } | undefined;
    if (payload?.questions) {
      detected = payload.questions;
      renderDetected();
    }
  }
});

void (async () => {
  await loadInbox();
  await renderCurrent();
  await scanForm();
})();
