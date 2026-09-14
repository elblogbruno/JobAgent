import { findApplyUrl, firstText } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const linkedinExtractor: JobExtractor = {
  id: "linkedin",
  matches: /(^|\.)linkedin\.com$/i,
  extract(): ExtractedJob {
    const description = firstText([
      ".jobs-description__content",
      "#job-details",
      ".jobs-box__html-content",
      ".show-more-less-html__markup",
    ]);

    // LinkedIn shows workplace type, employment type and pay as pills in the header.
    const pillText = [
      ...document.querySelectorAll(
        ".job-details-jobs-unified-top-card__job-insight, .jobs-unified-top-card__job-insight",
      ),
    ]
      .map((node) => node.textContent?.replace(/\s+/g, " ").trim() ?? "")
      .filter(Boolean)
      .join(" | ");

    let remotePolicy: string | undefined;
    if (/remote/i.test(pillText)) remotePolicy = "remote";
    else if (/hybrid/i.test(pillText)) remotePolicy = "hybrid";
    else if (/on-?site/i.test(pillText)) remotePolicy = "onsite";

    return {
      role: firstText([
        ".job-details-jobs-unified-top-card__job-title",
        ".jobs-unified-top-card__job-title",
        ".topcard__title",
        "h1",
      ]),
      company: firstText([
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
      ]),
      location: firstText([
        ".job-details-jobs-unified-top-card__bullet",
        ".jobs-unified-top-card__bullet",
        ".topcard__flavor--bullet",
      ]),
      remotePolicy,
      employmentType: /full-?time|part-?time|contract|internship/i.exec(pillText)?.[0],
      salary: /[€$£]\s?\d[\d.,]*/.exec(pillText)?.[0],
      description,
      // The real application usually lives on the company ATS behind Apply.
      applyUrl: findApplyUrl() ?? undefined,
    };
  },
};
