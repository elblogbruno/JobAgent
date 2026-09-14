import { firstText, metaContent } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const leverExtractor: JobExtractor = {
  id: "lever",
  matches: /lever\.co$/i,
  extract(): ExtractedJob {
    const categories = [
      ...document.querySelectorAll(".posting-categories div, .posting-category"),
    ]
      .map((node) => node.textContent?.replace(/\s+/g, " ").trim() ?? "")
      .filter(Boolean);

    return {
      role: firstText([".posting-headline h2", "h2", "h1"]),
      company: metaContent("og:site_name") ?? firstText([".main-header-logo img"]),
      location: firstText([".posting-categories .location", ".sort-by-location"]) ?? categories[0],
      employmentType: categories.find((value) =>
        /full-?time|part-?time|contract|intern/i.test(value),
      ),
      description: firstText([".section-wrapper.page-full-width", ".posting-content", ".content"]),
      applyUrl: document.querySelector<HTMLAnchorElement>("a.postings-btn[href*='apply']")?.href,
    };
  },
};
