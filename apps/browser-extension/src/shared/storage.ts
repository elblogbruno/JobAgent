/** Extension storage: configuration, the cached search inbox and per-tab state.
 *
 * The pairing token lives in chrome.storage.local, never in the source. Nothing
 * here is ever written to a page or sent anywhere except the configured backend.
 */

import { DEFAULT_CONFIG, ExtensionConfig, SearchInbox, TabState } from "./types";

const CONFIG_KEY = "config";
const INBOX_KEY = "inboxCache";
const TAB_STATE_KEY = "tabState";
const INBOX_TTL_MS = 10 * 60 * 1000;

export async function getConfig(): Promise<ExtensionConfig> {
  const stored = await chrome.storage.local.get(CONFIG_KEY);
  return { ...DEFAULT_CONFIG, ...(stored[CONFIG_KEY] ?? {}) };
}

export async function setConfig(patch: Partial<ExtensionConfig>): Promise<ExtensionConfig> {
  const merged = { ...(await getConfig()), ...patch };
  merged.apiBaseUrl = merged.apiBaseUrl.replace(/\/+$/, "");
  await chrome.storage.local.set({ [CONFIG_KEY]: merged });
  return merged;
}

export async function isPaired(): Promise<boolean> {
  const config = await getConfig();
  return Boolean(config.apiBaseUrl && config.token);
}

export async function cacheInbox(inbox: SearchInbox): Promise<void> {
  await chrome.storage.local.set({ [INBOX_KEY]: { inbox, fetchedAt: Date.now() } });
}

export async function getCachedInbox(maxAgeMs = INBOX_TTL_MS): Promise<SearchInbox | null> {
  const stored = await chrome.storage.local.get(INBOX_KEY);
  const entry = stored[INBOX_KEY] as { inbox: SearchInbox; fetchedAt: number } | undefined;
  if (!entry) return null;
  if (Date.now() - entry.fetchedAt > maxAgeMs) return null;
  return entry.inbox;
}

/** Tab state is session-scoped: it describes what is on screen right now. */
export async function getTabState(tabId: number): Promise<TabState | null> {
  const stored = await chrome.storage.session.get(TAB_STATE_KEY);
  const all = (stored[TAB_STATE_KEY] ?? {}) as Record<string, TabState>;
  return all[String(tabId)] ?? null;
}

export async function setTabState(state: TabState): Promise<void> {
  const stored = await chrome.storage.session.get(TAB_STATE_KEY);
  const all = (stored[TAB_STATE_KEY] ?? {}) as Record<string, TabState>;
  all[String(state.tabId)] = { ...state, updatedAt: Date.now() };
  await chrome.storage.session.set({ [TAB_STATE_KEY]: all });
}

export async function clearTabState(tabId: number): Promise<void> {
  const stored = await chrome.storage.session.get(TAB_STATE_KEY);
  const all = (stored[TAB_STATE_KEY] ?? {}) as Record<string, TabState>;
  delete all[String(tabId)];
  await chrome.storage.session.set({ [TAB_STATE_KEY]: all });
}

/**
 * Remembers which search the user opened in a tab, so an import from that tab
 * can be attributed to the query that produced it.
 */
const ATTRIBUTION_KEY = "searchAttribution";

export interface Attribution {
  queryId: string | null;
  provider: string | null;
  openedAt: number;
}

export async function setAttribution(tabId: number, attribution: Attribution): Promise<void> {
  const stored = await chrome.storage.session.get(ATTRIBUTION_KEY);
  const all = (stored[ATTRIBUTION_KEY] ?? {}) as Record<string, Attribution>;
  all[String(tabId)] = attribution;
  await chrome.storage.session.set({ [ATTRIBUTION_KEY]: all });
}

export async function getAttribution(tabId: number): Promise<Attribution | null> {
  const stored = await chrome.storage.session.get(ATTRIBUTION_KEY);
  const all = (stored[ATTRIBUTION_KEY] ?? {}) as Record<string, Attribution>;
  return all[String(tabId)] ?? null;
}
