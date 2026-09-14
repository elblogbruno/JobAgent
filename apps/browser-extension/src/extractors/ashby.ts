import { firstText, metaContent } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const ashbyExtractor: JobExtractor = {
  id: "ashby",
  matches: /ashbyhq\.com$/i,
  extract(): ExtractedJob {
    // Ashby renders client-side and hashes its class names, so page metadata is
    // the most reliable source for the header fields.
    const ogTitle = metaContent("og:title") ?? "";
    const [titlePart, companyPart] = ogTitle.split(/\s+[@|]\s+/);

    return {
      role: firstText(["h1", "[class*='_title']"]) ?? titlePart,
      company:
        firstText(["[class*='_organizationName']"]) ??
        companyPart ??
        metaContent("og:site_name"),
      location: firstText(["[class*='_location']", "[class*='locationName']"]),
      employmentType: firstText(["[class*='_employmentType']"]),
      description: firstText(["[class*='_description']", "main", "article"]),
      applyUrl: document.querySelector<HTMLAnchorElement>("a[href*='/application']")?.href,
    };
  },
};
