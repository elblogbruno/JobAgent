/** The popup: today's searches, plus import for the page currently open. */

import {
  element,
  notice,
  renderImportCard,
  renderInbox,
  renderTotals,
  send,
} from "../shared/ui";
import { ImportResult, SearchInbox, SearchRow, SessionInfo, TabState } from "../shared/types";
import { isJobLikeUrl } from "../shared/types";

const statusEl = document.getElementById("status") as HTMLElement;
const currentEl = document.getElementById("current") as HTMLElement;
const inboxEl = document.getElementById("inbox") as HTMLElement;
const totalsEl = document.getElementById("totals") as HTMLElement;

let session: SessionInfo | null = null;
let apiBaseUrl = "";

document.getElementById("options")?.addEventListener("click", () => chrome.runtime.openOptionsPage());
document.getElementById("refresh")?.addEventListener("click", () => void load(true));
document.getElementById("side-panel")?.addEventListener("click", async () => {
  await send({ type: "OPEN_SIDE_PANEL" });
  window.close();
});

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
  window.close();
}

/** Same token discipline as the side panel: build first, swap once. */
let renderToken = 0;

function showBusy(text: string): void {
  renderToken += 1;
  const block = element("section", "block");
  block.append(element("h2", "section-title", "Esta página"));
  block.append(notice(text));
  currentEl.replaceChildren(block);
}

async function renderCurrentTab(): Promise<void> {
  const token = ++renderToken;
  const block = await buildCurrentBlock();
  if (token !== renderToken) return;
  currentEl.replaceChildren(...(block ? [block] : []));
}

async function buildCurrentBlock(): Promise<HTMLElement | null> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/i.test(tab.url)) return null;

  const state = (await send<TabState | null>({ type: "GET_TAB_STATE" })) ?? null;
  const lookup = await send<{ found?: boolean; error?: string } & Partial<ImportResult>>({
    type: "LOOKUP_CURRENT_TAB",
  });

  const block = element("section", "block");
  block.append(element("h2", "section-title", "Esta página"));

  const existing: ImportResult | undefined =
    state?.result ?? (lookup?.found ? (lookup as ImportResult) : undefined);

  if (existing) {
    block.append(
      renderImportCard(existing, {
        phase: state?.phase ?? "done",
        highThreshold: session?.highMatchThreshold,
        apiBaseUrl,
        onOpenDashboard: () => void send({ type: "OPEN_DASHBOARD", payload: existing.jobId }),
        onPrepare: () => void prepareCv(existing),
      }),
    );
  } else if (state?.phase === "error") {
    block.append(notice(state.error ?? "No se pudo importar", true));
  } else if (state?.phase === "preparing") {
    block.append(notice("Preparando el CV…"));
  } else if (state?.phase === "capturing" || state?.phase === "importing") {
    block.append(notice("Importando…"));
  } else if (isJobLikeUrl(tab.url)) {
    const card = element("div", "card");
    card.append(element("div", "label", tab.title ?? "Esta página"));
    card.append(element("div", "meta", new URL(tab.url).hostname));
    const actions = element("div", "actions");
    const importButton = element("button", undefined, "Importar oferta");
    importButton.addEventListener("click", () => void importCurrent(false));
    const prepareButton = element("button", "ghost", "Importar y preparar");
    prepareButton.addEventListener("click", () => void importCurrent(true));
    actions.append(importButton, prepareButton);
    card.append(actions);
    block.append(card);
  } else {
    return null;
  }

  return block;
}

/** Prepares the CV for a job already in Job Agent, without re-reading the page. */
async function prepareCv(result: ImportResult): Promise<void> {
  if (!result.jobId) return;
  showBusy("Preparando el CV…");
  await send({ type: "PREPARE_JOB", payload: { jobId: result.jobId } });
  await renderCurrentTab();
}

async function importCurrent(prepare: boolean): Promise<void> {
  showBusy(prepare ? "Importando y preparando…" : "Importando…");
  await send({ type: "IMPORT_CURRENT_TAB", payload: { prepare } });
  await renderCurrentTab();
}

async function load(force = false): Promise<void> {
  statusEl.replaceChildren();
  inboxEl.replaceChildren(notice("Cargando búsquedas…"));

  // The download link points straight at the API, so the panel needs its URL.
  const config = await send<{ apiBaseUrl?: string }>({ type: "GET_CONFIG" });
  apiBaseUrl = (config?.apiBaseUrl ?? "").replace(/\/+$/, "");

  const sessionResult = await send<{ value?: SessionInfo; error?: string; needsPairing?: boolean }>(
    { type: "GET_SESSION" },
  );

  if (sessionResult?.error) {
    inboxEl.replaceChildren();
    statusEl.replaceChildren(notice(sessionResult.error, true));
    if (sessionResult.needsPairing) {
      const button = element("button", undefined, "Abrir ajustes");
      button.style.marginTop = "10px";
      button.addEventListener("click", () => chrome.runtime.openOptionsPage());
      statusEl.append(button);
    }
    return;
  }

  session = sessionResult?.value ?? null;
  if (session?.candidateName) {
    const line = element(
      "div",
      "meta",
      session.primaryRole
        ? `${session.candidateName} · ${session.primaryRole}`
        : session.candidateName,
    );
    statusEl.replaceChildren(line);
  }

  const inboxResult = await send<{ inbox?: SearchInbox; error?: string }>({
    type: "GET_INBOX",
    payload: { force },
  });

  if (inboxResult?.error || !inboxResult?.inbox) {
    inboxEl.replaceChildren(notice(inboxResult?.error ?? "No se pudieron cargar las búsquedas.", true));
    return;
  }

  inboxEl.replaceChildren(renderInbox(inboxResult.inbox, openSearch));
  totalsEl.replaceChildren(renderTotals(inboxResult.inbox));
  await renderCurrentTab();
}

chrome.runtime.onMessage.addListener((message: { type?: string }) => {
  if (message?.type === "TAB_STATE_CHANGED") void renderCurrentTab();
});

void load();
