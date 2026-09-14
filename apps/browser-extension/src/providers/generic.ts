import type { JobSearchQuery, SearchProvider } from "./index";

export const genericProvider: SearchProvider = {
  id: "generic-web",
  name: "Web Search",
  buildSearchUrl(query: JobSearchQuery): string {
    const terms = [query.query, query.remote ? "remote" : "", query.location ?? ""];
    const phrase = terms.filter(Boolean).join(" ");
    return `https://duckduckgo.com/?q=${encodeURIComponent(phrase)}&ia=web`;
  },
};
