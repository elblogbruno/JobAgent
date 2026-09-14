import type { JobSearchQuery, SearchProvider } from "./index";

export const linkedinProvider: SearchProvider = {
  id: "linkedin",
  name: "LinkedIn",
  buildSearchUrl(query: JobSearchQuery): string {
    const params = new URLSearchParams({ keywords: query.query, sortBy: "R" });
    if (query.location) params.set("location", query.location);
    // Workplace type 2 is fully remote.
    if (query.remote) params.set("f_WT", "2");
    return `https://www.linkedin.com/jobs/search/?${params.toString()}`;
  },
};
