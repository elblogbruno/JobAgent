import { firstText } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const infojobsExtractor: JobExtractor = {
  id: "infojobs",
  matches: /(^|\.)infojobs\.net$/i,
  extract(): ExtractedJob {
    const requirements = [...document.querySelectorAll("#requirements li, .requirements li")]
      .map((node) => node.textContent?.replace(/\s+/g, " ").trim() ?? "")
      .filter((value) => value.length > 6);

    return {
      role: firstText(["h1[data-testid='offer-title']", ".job-title", "h1"]),
      company: firstText([
        "[data-testid='offer-company']",
        "a.link[href*='/empresa']",
        ".company-name",
      ]),
      location: firstText(["[data-testid='offer-location']", ".location"]),
      salary: firstText(["[data-testid='offer-salary']", ".salary"]),
      employmentType: firstText(["[data-testid='offer-contract']", ".contract-type"]),
      description: firstText([
        "[data-testid='offer-description']",
        "#description",
        ".description",
      ]),
      requirements,
    };
  },
};
