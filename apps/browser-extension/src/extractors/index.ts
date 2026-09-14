/** Extractor registry.
 *
 * An extractor reads the parts of a page that its site puts in predictable
 * places. Everything it cannot find is left out: the backend fills gaps from
 * JSON-LD, semantic HTML and the visible text, in that order.
 */

import { ExtractedJob } from "../shared/types";

export interface JobExtractor {
  id: string;
  /** Hostnames this extractor handles. */
  matches: RegExp;
  extract(): ExtractedJob;
}

import { ashbyExtractor } from "./ashby";
import { genericExtractor } from "./generic";
import { greenhouseExtractor } from "./greenhouse";
import { indeedExtractor } from "./indeed";
import { infojobsExtractor } from "./infojobs";
import { leverExtractor } from "./lever";
import { linkedinExtractor } from "./linkedin";
import { workdayExtractor } from "./workday";

const extractors: JobExtractor[] = [
  linkedinExtractor,
  infojobsExtractor,
  indeedExtractor,
  greenhouseExtractor,
  leverExtractor,
  ashbyExtractor,
  workdayExtractor,
];

export function extractorFor(hostname: string): JobExtractor {
  return extractors.find((extractor) => extractor.matches.test(hostname)) ?? genericExtractor;
}

/** Runs the site extractor, then fills blanks from the generic one. */
export function runExtraction(hostname: string): { extracted: ExtractedJob; strategy: string } {
  const extractor = extractorFor(hostname);
  let extracted: ExtractedJob = {};
  try {
    extracted = extractor.extract();
  } catch {
    extracted = {};
  }

  let strategy = extractor.id;
  if (extractor.id !== genericExtractor.id) {
    try {
      const fallback = genericExtractor.extract();
      const before = Object.keys(extracted).length;
      extracted = { ...fallback, ...stripEmpty(extracted) };
      if (Object.keys(extracted).length > before) strategy = `${extractor.id}+generic`;
    } catch {
      // The site extractor's output stands on its own.
    }
  }
  return { extracted: stripEmpty(extracted), strategy };
}

function stripEmpty(job: ExtractedJob): ExtractedJob {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(job)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value) && value.length === 0) continue;
    result[key] = value;
  }
  return result as ExtractedJob;
}
