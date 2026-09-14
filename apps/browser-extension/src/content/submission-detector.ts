/** Spotting the confirmation a job board shows after you send an application.
 *
 * Precision over recall, deliberately. A missed confirmation costs one click on
 * "La envié yo". A false one writes a wrong status into the tracking and credits
 * a search with an application that never happened, so the patterns are anchored
 * phrases rather than loose keywords.
 */

export interface SubmissionEvidence {
  matched: string;
  /** The sentence the phrase appeared in, for the audit note. */
  excerpt: string;
  source: "text" | "dom" | "url";
}

/** Phrases that only appear once an application really went through. */
const CONFIRMATION_PATTERNS: RegExp[] = [
  // Spanish
  /se\s+ha\s+enviado\s+tu\s+solicitud/i,
  /tu\s+solicitud\s+(se\s+ha\s+enviado|ha\s+sido\s+enviada|fue\s+enviada)/i,
  /solicitud\s+enviada/i,
  /candidatura\s+(enviada|recibida|registrada)/i,
  /hemos\s+recibido\s+tu\s+(solicitud|candidatura)/i,
  /gracias\s+por\s+(postular|inscribirte|tu\s+candidatura)/i,
  /te\s+has\s+inscrito\s+(en|a)\s+esta\s+oferta/i,
  // English
  /your\s+application\s+(was|has\s+been)\s+(sent|submitted|received)/i,
  /application\s+(sent|submitted|received)\b/i,
  /we(?:'ve|\s+have)\s+received\s+your\s+application/i,
  /thank\s+you\s+for\s+applying/i,
  /thanks\s+for\s+applying/i,
  /submission\s+successful/i,
  // Catalan, since the candidate applies in Barcelona
  /s'ha\s+enviat\s+la\s+teva\s+sol·licitud/i,
  /sol·licitud\s+enviada/i,
];

/** Confirmation containers the big boards render, checked before free text. */
const CONFIRMATION_SELECTORS = [
  "[data-test-modal-id='post-apply-modal']",
  ".post-apply-modal",
  ".jobs-post-apply-modal",
  "#application_confirmation",
  ".application-confirmation",
  "[data-qa='application-success']",
  "[class*='confirmationMessage']",
];

/** Phrases that look like a confirmation but are not one. */
const NEGATIVE_PATTERNS: RegExp[] = [
  /(no|not|nunca|todav[ií]a\s+no|a[úu]n\s+no)\s+[^.]{0,20}(enviad|submitted|sent)/i,
  /antes\s+de\s+enviar/i,
  /before\s+(you\s+)?submit/i,
  /revisa\s+tu\s+solicitud/i,
  /review\s+your\s+application/i,
  // A form still on screen is a form, not a receipt.
  /rellena\s+los\s+campos/i,
];

function sentenceAround(haystack: string, index: number): string {
  const start = Math.max(0, haystack.lastIndexOf(".", index) + 1);
  const dot = haystack.indexOf(".", index);
  const end = dot === -1 ? Math.min(haystack.length, index + 160) : dot + 1;
  return haystack.slice(start, end).replace(/\s+/g, " ").trim().slice(0, 220);
}

/** Exported so the patterns can be tested without a DOM. */
export function matchConfirmation(
  text: string,
  source: SubmissionEvidence["source"] = "text",
): SubmissionEvidence | null {
  return testPatterns(text, source);
}

function testPatterns(text: string, source: SubmissionEvidence["source"]): SubmissionEvidence | null {
  if (!text) return null;
  for (const pattern of CONFIRMATION_PATTERNS) {
    const match = pattern.exec(text);
    if (!match) continue;
    const excerpt = sentenceAround(text, match.index);
    // A negation in the same sentence flips the meaning entirely.
    if (NEGATIVE_PATTERNS.some((negative) => negative.test(excerpt))) continue;
    return { matched: match[0], excerpt, source };
  }
  return null;
}

function visibleTextOf(node: Element): string {
  const style = window.getComputedStyle(node);
  if (style.display === "none" || style.visibility === "hidden") return "";
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Looks for evidence that this page is a post-application confirmation. */
export function detectSubmission(): SubmissionEvidence | null {
  // 1. A dedicated confirmation container is the strongest signal there is.
  for (const selector of CONFIRMATION_SELECTORS) {
    for (const node of document.querySelectorAll(selector)) {
      const found = testPatterns(visibleTextOf(node).slice(0, 2000), "dom");
      if (found) return found;
    }
  }

  // 2. A confirmation URL, which most ATS platforms redirect to.
  const url = window.location.href.toLowerCase();
  if (/\/(thank[-_]?you|confirmation|application[-_]?(sent|complete|received))(\/|\?|$)/.test(url)) {
    return {
      matched: "confirmation URL",
      excerpt: window.location.href.slice(0, 220),
      source: "url",
    };
  }

  // 3. Free text, but only in the part of the page a person would be reading.
  //    Scanning the whole body matches boilerplate in footers and help panels.
  const candidates = [
    document.querySelector("[role='alert']"),
    document.querySelector("[role='status']"),
    document.querySelector("[role='dialog']"),
    document.querySelector("main"),
    document.querySelector("h1"),
    document.querySelector("h2"),
  ];
  for (const node of candidates) {
    if (!node) continue;
    const found = testPatterns(visibleTextOf(node).slice(0, 3000), "text");
    if (found) return found;
  }

  return null;
}
