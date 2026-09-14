import type { JobSearchQuery, SearchProvider } from "./index";

export const googleProvider: SearchProvider = {
  id: "google",
  name: "Google Jobs",
  buildSearchUrl(query: JobSearchQuery): string {
    const terms = [query.query, query.remote ? "remote" : "", query.location ?? ""];
    const phrase = terms.filter(Boolean).join(" ");
    return `https://www.google.com/search?q=${encodeURIComponent(phrase)}&ibp=htl;jobs`;
  },
};
