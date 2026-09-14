import { firstText, metaContent } from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

export const greenhouseExtractor: JobExtractor = {
  id: "greenhouse",
  matches: /greenhouse\.io$/i,
  extract(): ExtractedJob {
    return {
      role: firstText([".app-title", "h1.section-header", "h1"]),
      company:
        firstText([".company-name", "#header .company-name"])?.replace(/^at\s+/i, "") ??
        metaContent("og:site_name"),
      location: firstText([".location", ".job__location", "#location"]),
      description: firstText(["#content", ".job__description", ".content"]),
      // Greenhouse hosts the form on the posting itself.
      applyUrl: document.querySelector("#application_form") ? window.location.href : undefined,
    };
  },
};
