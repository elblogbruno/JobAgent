/** DOM capture helpers.
 *
 * The extension sends the least it can get away with. Scripts, styles, tracking
 * pixels, navigation, footers, hidden elements and "similar jobs" blocks are
 * stripped before anything leaves the page.
 */

const DROP_SELECTOR = [
  "script",
  "style",
  "noscript",
  "iframe",
  "svg",
  "canvas",
  "video",
  "audio",
  "nav",
  "footer",
  "header",
  "form",
  "link",
  "meta",
  "template",
  "[aria-hidden='true']",
  "[role='navigation']",
  "[role='banner']",
  "[role='contentinfo']",
  "[role='complementary']",
  "[role='search']",
].join(",");

const NOISE_PATTERN =
  /(cookie|consent|advert|promo|newsletter|recommend|similar|related|breadcrumb|social|share|tracking|sidebar|footer|nav-|carousel|jobs-you-may)/i;

const MAX_HTML_CHARS = 120_000;
const MAX_TEXT_CHARS = 40_000;

/** Candidate roots for the job content, most specific first. */
const CONTENT_SELECTORS = [
  "[itemtype*='JobPosting']",
  "main",
  "article",
  "[role='main']",
  "#content",
  ".job-view-layout",
  ".jobs-description",
  ".job-details",
  ".posting",
  ".opening",
];

export function findContentRoot(): Element {
  for (const selector of CONTENT_SELECTORS) {
    const node = document.querySelector(selector);
    if (node && node.textContent && node.textContent.trim().length > 400) return node;
  }
  return document.body;
}

function isHidden(element: Element): boolean {
  const style = window.getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
    return true;
  }
  const rect = element.getBoundingClientRect();
  return rect.width === 0 && rect.height === 0;
}

/** Returns cleaned HTML for the job content, capped in size. */
export function cleanedHtml(root: Element = findContentRoot()): string {
  const hiddenSelectors: string[] = [];
  root.querySelectorAll("div,section,aside,ul,p,span").forEach((element) => {
    if (isHidden(element) && element.textContent && element.textContent.length > 40) {
      element.setAttribute("data-job-agent-hidden", "true");
      hiddenSelectors.push("hidden");
    }
  });

  const clone = root.cloneNode(true) as Element;
  clone.querySelectorAll(DROP_SELECTOR).forEach((node) => node.remove());
  clone.querySelectorAll("[data-job-agent-hidden='true']").forEach((node) => node.remove());

  clone.querySelectorAll("*").forEach((node) => {
    const identity = `${node.className ?? ""} ${node.id ?? ""}`;
    if (typeof node.className === "string" && NOISE_PATTERN.test(identity)) {
      node.remove();
      return;
    }
    for (const attribute of [...node.attributes]) {
      if (!["href", "datetime", "itemprop", "content"].includes(attribute.name)) {
        node.removeAttribute(attribute.name);
      }
    }
  });

  // Undo the markers left on the live page.
  root
    .querySelectorAll("[data-job-agent-hidden]")
    .forEach((node) => node.removeAttribute("data-job-agent-hidden"));

  return clone.innerHTML.slice(0, MAX_HTML_CHARS);
}

/** The job text as the user is actually reading it. */
export function visibleText(root: Element = findContentRoot()): string {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node: Node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (parent.closest(DROP_SELECTOR)) return NodeFilter.FILTER_REJECT;
      if (!node.textContent || !node.textContent.trim()) return NodeFilter.FILTER_REJECT;
      if (isHidden(parent)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const lines: string[] = [];
  let total = 0;
  let current: Node | null;
  while ((current = walker.nextNode())) {
    const text = (current.textContent ?? "").replace(/\s+/g, " ").trim();
    if (!text) continue;
    if (lines[lines.length - 1] === text) continue;
    lines.push(text);
    total += text.length;
    if (total > MAX_TEXT_CHARS) break;
  }
  return lines.join("\n");
}

/** Every JSON-LD block on the page, parsed. The backend picks the JobPosting. */
export function collectJsonLd(): unknown[] {
  const blocks: unknown[] = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach((node) => {
    const raw = node.textContent?.trim();
    if (!raw) return;
    try {
      blocks.push(JSON.parse(raw));
    } catch {
      // Some sites emit invalid JSON-LD; the other extraction layers cover it.
    }
  });
  return blocks;
}

export function canonicalUrlHint(): string | null {
  const link = document.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (link?.href) return link.href;
  const og = document.querySelector<HTMLMetaElement>('meta[property="og:url"]');
  return og?.content ?? null;
}

const ATS_PATTERN =
  /(jobs\.ashbyhq\.com|boards\.greenhouse\.io|job-boards\.greenhouse\.io|jobs\.lever\.co|apply\.workable\.com|jobs\.smartrecruiters\.com|myworkdayjobs\.com)/i;

/** Looks for the company's own application link behind an aggregator listing. */
export function findApplyUrl(): string | null {
  const anchors = [...document.querySelectorAll<HTMLAnchorElement>("a[href]")];
  const ats = anchors.find((anchor) => ATS_PATTERN.test(anchor.href));
  if (ats) return ats.href;

  const applyLike = anchors.find((anchor) => {
    const label = `${anchor.textContent ?? ""} ${anchor.getAttribute("aria-label") ?? ""}`;
    return /apply|solicitar|postular|bewerben/i.test(label) && /^https?:/i.test(anchor.href);
  });
  return applyLike?.href ?? null;
}

export function text(selector: string, root: ParentNode = document): string | undefined {
  const node = root.querySelector(selector);
  const value = node?.textContent?.replace(/\s+/g, " ").trim();
  return value || undefined;
}

export function firstText(selectors: string[], root: ParentNode = document): string | undefined {
  for (const selector of selectors) {
    const value = text(selector, root);
    if (value) return value;
  }
  return undefined;
}

export function metaContent(name: string): string | undefined {
  const node =
    document.querySelector<HTMLMetaElement>(`meta[property="${name}"]`) ??
    document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  return node?.content?.trim() || undefined;
}

export function bulletsUnder(headingPattern: RegExp, root: ParentNode = document): string[] {
  const headings = [...root.querySelectorAll("h2,h3,h4,strong,b,p")];
  const heading = headings.find((node) => headingPattern.test(node.textContent ?? ""));
  if (!heading) return [];
  let sibling = heading.nextElementSibling;
  const bullets: string[] = [];
  while (sibling && bullets.length < 20) {
    if (/^H[1-4]$/.test(sibling.tagName)) break;
    if (sibling.tagName === "UL" || sibling.tagName === "OL") {
      sibling.querySelectorAll("li").forEach((item) => {
        const value = item.textContent?.replace(/\s+/g, " ").trim();
        if (value && value.length > 6) bullets.push(value);
      });
      break;
    }
    sibling = sibling.nextElementSibling;
  }
  return bullets;
}
