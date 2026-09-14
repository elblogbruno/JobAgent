/** Options page: pairing and behaviour.
 *
 * Pairing is a token the user creates in their own dashboard and pastes here.
 * The extension holds no credentials of its own and never asks for a job board
 * password.
 */

import { getConfig, setConfig } from "../shared/storage";
import { notice } from "../shared/ui";
import { SessionInfo } from "../shared/types";

const apiInput = document.getElementById("api-url") as HTMLInputElement;
const tokenInput = document.getElementById("token") as HTMLInputElement;
const injectInput = document.getElementById("inject") as HTMLInputElement;
const resultEl = document.getElementById("result") as HTMLElement;

async function restore(): Promise<void> {
  const config = await getConfig();
  apiInput.value = config.apiBaseUrl;
  tokenInput.value = config.token;
  injectInput.checked = config.injectPageButton;
}

/**
 * A custom backend host needs its own permission. localhost is already in
 * host_permissions, so this only prompts when the user points somewhere else.
 */
async function ensureHostPermission(apiBaseUrl: string): Promise<boolean> {
  let origin: string;
  try {
    origin = `${new URL(apiBaseUrl).origin}/*`;
  } catch {
    return false;
  }
  if (await chrome.permissions.contains({ origins: [origin] })) return true;
  try {
    return await chrome.permissions.request({ origins: [origin] });
  } catch {
    return false;
  }
}

document.getElementById("save")?.addEventListener("click", async () => {
  resultEl.replaceChildren(notice("Saving…"));

  const apiBaseUrl = apiInput.value.trim().replace(/\/+$/, "");
  if (!apiBaseUrl) {
    resultEl.replaceChildren(notice("A Job Agent URL is required.", true));
    return;
  }

  if (!(await ensureHostPermission(apiBaseUrl))) {
    resultEl.replaceChildren(
      notice(`Permission to reach ${apiBaseUrl} was not granted.`, true),
    );
    return;
  }

  await setConfig({
    apiBaseUrl,
    token: tokenInput.value.trim(),
    injectPageButton: injectInput.checked,
  });

  // Imported lazily so the client picks up the configuration just saved.
  const { jobAgentClient } = await import("../api/job-agent-client");
  try {
    const session: SessionInfo = await jobAgentClient.getSession();
    const lines = [
      `Paired as ${session.candidateName}.`,
      session.roleMapVersion
        ? `Role map v${session.roleMapVersion}${session.primaryRole ? ` · primary role: ${session.primaryRole}` : ""}`
        : "No role map yet: run Role Discovery in the dashboard.",
    ];
    const box = notice(lines.join("\n"));
    box.style.whiteSpace = "pre-line";
    resultEl.replaceChildren(box);
  } catch (error) {
    resultEl.replaceChildren(
      notice(error instanceof Error ? error.message : String(error), true),
    );
  }
});

document.getElementById("clear")?.addEventListener("click", async () => {
  await setConfig({ token: "" });
  tokenInput.value = "";
  resultEl.replaceChildren(notice("Token cleared."));
});

injectInput.addEventListener("change", () => {
  void setConfig({ injectPageButton: injectInput.checked });
});

void restore();
