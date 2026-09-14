import type { JobSearchQuery, SearchProvider } from "./index";

const DOMAINS: [RegExp, string][] = [
  [/spain|espa|barcelona|madrid|valencia|bilbao|sevilla/i, "https://es.indeed.com"],
  [/united kingdom|\buk\b|london|manchester|england|scotland/i, "https://uk.indeed.com"],
  [/germany|deutschland|berlin|munich|hamburg/i, "https://de.indeed.com"],
  [/netherlands|amsterdam|rotterdam|utrecht/i, "https://nl.indeed.com"],
];

export const indeedProvider: SearchProvider = {
  id: "indeed",
  name: "Indeed",
  buildSearchUrl(query: JobSearchQuery): string {
    const location = query.location ?? "";
    const domain =
      DOMAINS.find(([pattern]) => pattern.test(location))?.[1] ?? "https://www.indeed.com";
    const params = new URLSearchParams({ q: query.query });
    if (query.remote) params.set("l", "Remote");
    else if (query.location) params.set("l", query.location);
    return `${domain}/jobs?${params.toString()}`;
  },
};
