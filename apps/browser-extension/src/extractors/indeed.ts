import { firstText } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const indeedExtractor: JobExtractor = {
  id: "indeed",
  matches: /(^|\.)indeed\.[a-z.]+$/i,
  extract(): ExtractedJob {
    return {
      role: firstText([
        "h1.jobsearch-JobInfoHeader-title",
        "[data-testid='jobsearch-JobInfoHeader-title']",
        "h1",
      ]),
      company: firstText([
        "[data-testid='inlineHeader-companyName']",
        "[data-company-name]",
        ".jobsearch-CompanyInfoContainer a",
      ]),
      location: firstText([
        "[data-testid='inlineHeader-companyLocation']",
        "[data-testid='job-location']",
      ]),
      salary: firstText([
        "#salaryInfoAndJobType span",
        "[data-testid='attribute_snippet_testid']",
      ]),
      description: firstText(["#jobDescriptionText", ".jobsearch-JobComponent-description"]),
    };
  },
};
