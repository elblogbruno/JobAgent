import { firstText, metaContent } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const workdayExtractor: JobExtractor = {
  id: "workday",
  matches: /(myworkdayjobs|workday)\.com$/i,
  extract(): ExtractedJob {
    return {
      role: firstText(["[data-automation-id='jobPostingHeader']", "h1", "h2"]),
      company: metaContent("og:site_name") ?? firstText(["[data-automation-id='company']"]),
      location: firstText([
        "[data-automation-id='locations'] dd",
        "[data-automation-id='jobPostingLocation']",
      ]),
      employmentType: firstText(["[data-automation-id='time'] dd"]),
      datePosted: firstText(["[data-automation-id='postedOn'] dd"]),
      description: firstText([
        "[data-automation-id='jobPostingDescription']",
        "[data-automation-id='job-posting-details']",
      ]),
    };
  },
};
