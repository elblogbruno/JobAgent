/** Rendering shared by the popup and the side panel.
 *
 * Both surfaces show the same Search Inbox and the same import card, so the
 * markup lives here once. All DOM is built with createElement: no HTML strings,
 * so nothing from the backend or a page can be injected as markup.
 */

import { providerLabel } from "../providers/index";
import { AssistantAnswer, ChatMessage, ImportResult, Message, SearchInbox, SearchRow } from "./types";

export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function send<T = unknown>(message: Message): Promise<T> {
  return chrome.runtime.sendMessage(message) as Promise<T>;
}

export function scoreClass(score: number | null | undefined, highThreshold = 80): string {
  if (score === null || score === undefined) return "";
  if (score >= highThreshold) return "good";
  if (score >= 60) return "mid";
  return "low";
}

export function notice(text: string, isError = false): HTMLElement {
  return element("div", isError ? "notice error" : "notice", text);
}

/** One search row: the query, then a button per provider. */
function renderRow(row: SearchRow, onOpen: (row: SearchRow, targetIndex: number) => void): HTMLElement {
  const container = element("div", "row");

  const label = element("div", "label");
  label.append(document.createTextNode(row.label));
  if (row.isExploratory) {
    const pill = element("span", "pill explore", "explorar");
    pill.style.marginLeft = "6px";
    label.append(pill);
  }
  container.append(label);

  const metaParts = [row.query];
  if (row.location) metaParts.push(row.location);
  if (row.remote) metaParts.push("remote");
  container.append(element("div", "meta", metaParts.join(" · ")));

  const targets = element("div", "targets");
  row.targets.forEach((target, index) => {
    const button = element("button", "ghost small", providerLabel(target.provider));
    button.addEventListener("click", () => onOpen(row, index));
    targets.append(button);
  });
  container.append(targets);

  return container;
}

export function renderInbox(
  inbox: SearchInbox,
  onOpen: (row: SearchRow, targetIndex: number) => void,
): DocumentFragment {
  const fragment = document.createDocumentFragment();

  for (const section of inbox.sections) {
    const hasRows = section.groups.some((group) => group.searches.length > 0);
    if (!hasRows) continue;

    const block = element("section", "block");
    block.append(element("h2", "section-title", section.title));

    for (const group of section.groups) {
      if (!group.searches.length) continue;
      block.append(element("h3", "group-title", group.label));
      for (const row of group.searches) {
        block.append(renderRow(row, onOpen));
      }
    }
    fragment.append(block);
  }

  if (!fragment.childElementCount) {
    fragment.append(
      notice(
        "Aún no hay búsquedas. Abre el dashboard y lanza Role Discovery para construir tu mapa de roles.",
      ),
    );
  }
  return fragment;
}

export function renderTotals(inbox: SearchInbox): HTMLElement {
  const totals = element("div", "totals");
  const entries: [string, number][] = [
    ["búsquedas", inbox.totals.searches ?? 0],
    ["abiertas", inbox.totals.searchesOpened ?? 0],
    ["importadas", inbox.totals.jobsImported ?? 0],
    ["buen match", inbox.totals.highMatchJobsImported ?? 0],
    ["candidaturas", inbox.totals.applicationsGenerated ?? 0],
    ["entrevistas", inbox.totals.interviewsProduced ?? 0],
  ];
  for (const [label, value] of entries) {
    const span = element("span");
    const bold = element("b", undefined, String(value));
    span.append(bold, document.createTextNode(` ${label}`));
    totals.append(span);
  }
  return totals;
}

/** The import card: match score, strengths, gaps and what was produced. */
export function renderImportCard(
  result: ImportResult,
  options: {
    phase: string;
    highThreshold?: number;
    apiBaseUrl?: string;
    onOpenDashboard: () => void;
    onPrepare?: () => void;
  },
): HTMLElement {
  const card = element("div", "card");

  card.append(element("div", "label", result.role || "Job"));
  const meta = [result.company, result.location].filter(Boolean).join(" · ");
  if (meta) card.append(element("div", "meta", meta));

  if (result.matchScore !== null && result.matchScore !== undefined) {
    const score = element("div", `score ${scoreClass(result.matchScore, options.highThreshold)}`);
    score.append(document.createTextNode(String(result.matchScore)));
    score.append(element("small", undefined, " / 100"));
    score.style.marginTop = "10px";
    card.append(score);
    if (result.primaryRole) {
      card.append(element("div", "meta", `Rol principal: ${result.primaryRole}`));
    }
  } else if (options.phase === "analyzing") {
    card.append(element("div", "meta", "Analizando la oferta…"));
  }

  if (options.phase === "preparing") {
    card.append(element("div", "meta", "Adaptando tu CV en Reactive Resume…"));
  }

  const steps = element("div", "meta");
  const lines = ["✓ Oferta importada"];
  if (result.applicationRunId) lines.push("✓ CV adaptado y candidatura creada");
  if (result.jobStatus) lines.push(`Estado: ${result.jobStatus}`);
  if (result.message) lines.push(result.message);
  steps.textContent = lines.join("\n");
  steps.style.whiteSpace = "pre-line";
  steps.style.marginTop = "8px";
  card.append(steps);

  if (result.strengths.length) {
    card.append(element("h2", "section-title", "A favor"));
    const list = element("ul", "tags");
    result.strengths.slice(0, 4).forEach((item) => list.append(element("li", undefined, item)));
    card.append(list);
  }
  if (result.gaps.length) {
    card.append(element("h2", "section-title", "Puntos flojos"));
    const list = element("ul", "tags");
    result.gaps.slice(0, 4).forEach((item) => list.append(element("li", undefined, item)));
    card.append(list);
  }

  const actions = element("div", "actions");
  const open = element("button", "ghost", "Abrir en Job Agent");
  open.addEventListener("click", options.onOpenDashboard);
  actions.append(open);

  if (options.onPrepare && result.preparationState !== "ready") {
    const prepare = element("button", undefined, "Preparar CV");
    prepare.disabled = options.phase === "preparing";
    // The label says what pressing it would do given where things stand.
    if (options.phase === "preparing") prepare.textContent = "Preparando…";
    else if (result.preparationState === "skipped") prepare.textContent = "Preparar igualmente";
    else if (result.preparationState === "failed") prepare.textContent = "Reintentar CV";
    prepare.addEventListener("click", options.onPrepare);
    actions.append(prepare);
  }

  // The whole point of preparing: the PDF to attach when applying by hand.
  if (result.preparationState === "ready" && result.applicationRunId && options.apiBaseUrl) {
    const download = element("a", "button");
    download.textContent = "Descargar CV";
    download.href = `${options.apiBaseUrl}/api/applications/${encodeURIComponent(
      result.applicationRunId,
    )}/resume`;
    download.target = "_blank";
    download.rel = "noreferrer";
    download.style.textDecoration = "none";
    actions.append(download);
  }
  card.append(actions);

  return card;
}


/** One turn of the form assistant conversation. */
export function renderChatMessage(
  message: ChatMessage,
  onCopy: (text: string) => void,
  onRemember?: (text: string) => void,
): HTMLElement {
  const wrapper = element("div", message.role === "user" ? "chat-turn user" : "chat-turn");

  const body = element("div", "chat-body");
  body.textContent = message.content;
  wrapper.append(body);

  if (message.role !== "assistant") return wrapper;

  const meta = message.meta;
  if (meta) {
    if (meta.source === "vault") {
      wrapper.append(
        element("div", "chat-note", "De tus respuestas guardadas, así coincide con lo que dijiste antes."),
      );
    } else if (meta.groundedOn.length) {
      wrapper.append(element("div", "chat-note", `Con base en: ${meta.groundedOn.join(", ")}`));
    }

    for (const warning of meta.warnings) {
      wrapper.append(element("div", "chat-warning", `Revisa esto: ${warning}`));
    }
    for (const caveat of meta.caveats) {
      wrapper.append(element("div", "chat-note", caveat));
    }
    if (meta.missing.length) {
      wrapper.append(
        element("div", "chat-warning", `No está en tu CV: ${meta.missing.join(", ")}`),
      );
    }
  }

  const actions = element("div", "actions");
  const copy = element("button", "ghost small", "Copiar");
  copy.addEventListener("click", () => onCopy(message.content));
  actions.append(copy);

  // Only fields the vault recognises can be recalled later, so the button is
  // offered only when the backend said it has somewhere to put the answer.
  if (onRemember && meta && meta.canonicalKey) {
    const remember = element("button", "ghost small", "Recordar");
    remember.title = "Guarda esta respuesta para la próxima vez que salga el mismo campo";
    remember.addEventListener("click", () => onRemember(message.content));
    actions.append(remember);
  }
  wrapper.append(actions);

  return wrapper;
}

export function assistantAnswerToMessage(answer: AssistantAnswer): ChatMessage {
  return { role: "assistant", content: answer.answer, meta: answer };
}
