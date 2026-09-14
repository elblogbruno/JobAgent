/** Bridge between the Job Agent dashboard and the extension.
 *
 * The dashboard's Search buttons dispatch a DOM event. If the extension is
 * installed it opens the search and records the click for attribution; if not,
 * the dashboard falls back to opening the URL itself. The bridge also announces
 * its presence so the dashboard can tell which of the two will happen.
 */

interface OpenSearchDetail {
  queryId?: string | null;
  provider?: string | null;
  url?: string | null;
  query?: string;
  location?: string | null;
  remote?: boolean | null;
}

const version = chrome.runtime.getManifest().version;
document.documentElement.dataset.jobAgentExtension = version;

window.dispatchEvent(
  new CustomEvent("jobagent:extension-ready", { detail: { version } }),
);

window.addEventListener("jobagent:open-search", (event) => {
  const detail = (event as CustomEvent<OpenSearchDetail>).detail ?? {};
  void chrome.runtime.sendMessage({
    type: "OPEN_SEARCH",
    payload: {
      queryId: detail.queryId ?? null,
      provider: detail.provider ?? "generic-web",
      url: detail.url ?? null,
      query: detail.query ?? "",
      location: detail.location ?? null,
      remote: detail.remote ?? null,
    },
  });
});

window.addEventListener("jobagent:open-side-panel", () => {
  void chrome.runtime.sendMessage({ type: "OPEN_SIDE_PANEL" });
});
