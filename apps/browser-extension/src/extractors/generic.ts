import {
  bulletsUnder,
  findApplyUrl,
  findContentRoot,
  firstText,
  metaContent,
  visibleText,
} from "../shared/dom";
import { ExtractedJob } from "../shared/types";
import type { JobExtractor } from "./index";

const REQUIREMENTS =
  /requirements|qualifications|what you.{0,4}ll need|who you are|requisitos|must have/i;
const PREFERRED = /nice to have|preferred|bonus|desirable|se valorar|valorable/i;

/** Works on any job page: semantic HTML first, then page metadata. */
export const genericExtractor: JobExtractor = {
  id: "generic",
  matches: /.*/,
  extract(): ExtractedJob {
    const root = findContentRoot();
    return {
      role:
        firstText(["[itemprop='title']", "h1"]) ?? metaContent("og:title") ?? document.title,
      company:
        firstText(["[itemprop='hiringOrganization']", "[data-company]", ".company"]) ??
        metaContent("og:site_name"),
      location: firstText(["[itemprop='jobLocation']", "[data-location]", ".location"]),
      description: visibleText(root),
      applyUrl: findApplyUrl() ?? undefined,
      requirements: bulletsUnder(REQUIREMENTS, root),
      preferredRequirements: bulletsUnder(PREFERRED, root),
    };
  },
};
