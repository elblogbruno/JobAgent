import type { JobSearchQuery, SearchProvider } from "./index";

export const infojobsProvider: SearchProvider = {
  id: "infojobs",
  name: "InfoJobs",
  buildSearchUrl(query: JobSearchQuery): string {
    const keyword = query.location ? `${query.query} ${query.location}` : query.query;
    const params = new URLSearchParams({
      keyword,
      page: "1",
      sortBy: "RELEVANCE",
      onlyForeignCountry: "false",
      countryIds: "17",
      sinceDate: "ANY",
    });
    if (query.remote) params.set("teleworkingIds", "2");
    return `https://www.infojobs.net/jobsearch/search-results/list.xhtml?${params.toString()}`;
  },
};
