/** Client-side search providers.
 *
 * The backend resolves a URL for every stored query, and that URL is what the
 * extension opens. These providers are the fallback for when a query arrives
 * without one, and they define the shape a new provider must implement.
 */

export interface JobSearchQuery {
  query: string;
  location?: string | null;
  remote?: boolean | null;
}

export interface SearchProvider {
  id: string;
  name: string;
  buildSearchUrl(query: JobSearchQuery): string;
}

import { genericProvider } from "./generic";
import { googleProvider } from "./google";
import { indeedProvider } from "./indeed";
import { infojobsProvider } from "./infojobs";
import { linkedinProvider } from "./linkedin";

const providers: SearchProvider[] = [
  linkedinProvider,
  infojobsProvider,
  googleProvider,
  indeedProvider,
  genericProvider,
];

export function getProvider(id: string): SearchProvider {
  return providers.find((provider) => provider.id === id) ?? genericProvider;
}

export function allProviders(): SearchProvider[] {
  return [...providers];
}

/** Resolves the URL to open: the backend's, or a locally built fallback. */
export function resolveSearchUrl(
  providerId: string,
  query: JobSearchQuery,
  backendUrl?: string | null,
): string {
  if (backendUrl) return backendUrl;
  return getProvider(providerId).buildSearchUrl(query);
}

export function providerLabel(id: string): string {
  return getProvider(id).name;
}
