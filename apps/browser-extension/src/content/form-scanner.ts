/** Finding the questions an application form is asking.
 *
 * Runs entirely in the page. Nothing is sent anywhere by scanning: the result is
 * a list of labels the side panel can offer to help with, and the model is only
 * called when the user asks for a specific one.
 */

export interface FormQuestion {
  /** Stable within the page, used to fill the field back in. */
  id: string;
  label: string;
  type: string;
  required: boolean;
  options: string[];
  /** True when the field already has something in it. */
  filled: boolean;
}

const FIELD_SELECTOR =
  "textarea, input[type='text'], input[type='email'], input[type='tel'], input[type='url'], input[type='number'], select";

// Fields that are identity, not questions: the pipeline fills these from the
// profile and the assistant has nothing useful to add.
const BORING_LABEL =
  /^(first|last|full|given|family)?\s*name|^e?-?mail|^phone|^telephone|^address|^city|^post(al)?\s*code|^zip|^linkedin|^github|^portfolio|^website|^resume|^cv\b|^cover letter file|^upload/i;

const MEANINGFUL_TYPES = new Set(["textarea", "select"]);

function labelFor(field: HTMLElement): string {
  const id = field.getAttribute("id");
  if (id) {
    const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
    const text = explicit?.textContent?.replace(/\s+/g, " ").trim();
    if (text) return text;
  }

  const wrapping = field.closest("label");
  if (wrapping) {
    const clone = wrapping.cloneNode(true) as HTMLElement;
    clone.querySelectorAll("input, textarea, select").forEach((node) => node.remove());
    const text = clone.textContent?.replace(/\s+/g, " ").trim();
    if (text) return text;
  }

  const labelled = field.getAttribute("aria-label");
  if (labelled?.trim()) return labelled.trim();

  const describedBy = field.getAttribute("aria-labelledby");
  if (describedBy) {
    const text = document.getElementById(describedBy)?.textContent?.replace(/\s+/g, " ").trim();
    if (text) return text;
  }

  // Greenhouse, Lever and Ashby all put the question in a sibling above the field.
  const container = field.closest("div, fieldset, li");
  const heading = container?.querySelector("label, legend, .application-label, [class*='label']");
  const nearby = heading?.textContent?.replace(/\s+/g, " ").trim();
  if (nearby) return nearby;

  return (field.getAttribute("placeholder") ?? "").trim();
}

function isVisible(field: HTMLElement): boolean {
  const style = window.getComputedStyle(field);
  if (style.display === "none" || style.visibility === "hidden") return false;
  const rect = field.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function optionsFor(field: HTMLElement): string[] {
  if (!(field instanceof HTMLSelectElement)) return [];
  return [...field.options]
    .map((option) => option.textContent?.trim() ?? "")
    .filter((text) => text && !/^(select|choose|--)/i.test(text))
    .slice(0, 12);
}

/** Marks a field so it can be found again when filling the answer in. */
function ensureId(field: HTMLElement, index: number): string {
  const existing = field.getAttribute("data-job-agent-field");
  if (existing) return existing;
  const id = `ja-field-${index}`;
  field.setAttribute("data-job-agent-field", id);
  return id;
}

export function detectFormQuestions(limit = 25): FormQuestion[] {
  const questions: FormQuestion[] = [];
  const fields = [...document.querySelectorAll<HTMLElement>(FIELD_SELECTOR)];

  fields.forEach((field, index) => {
    if (questions.length >= limit) return;
    if (!isVisible(field)) return;

    const tag = field.tagName.toLowerCase();
    const label = labelFor(field);
    if (!label || label.length < 6 || label.length > 400) return;
    if (BORING_LABEL.test(label)) return;

    // A short text input is only interesting when it reads as a question. A
    // textarea or a select almost always is.
    const looksLikeQuestion = /\?|describe|why|tell us|explain|what|how|experience with/i.test(label);
    if (!MEANINGFUL_TYPES.has(tag) && !looksLikeQuestion) return;

    const value = (field as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value ?? "";

    questions.push({
      id: ensureId(field, index),
      label: label.replace(/\s*\*+\s*$/, "").trim(),
      type: tag === "select" ? "select" : tag === "textarea" ? "textarea" : "text",
      required: field.hasAttribute("required") || /\*\s*$/.test(label),
      options: optionsFor(field),
      filled: Boolean(value.trim()),
    });
  });

  return questions;
}

/** Writes an answer into a field the user chose, and tells the page about it. */
export function fillField(fieldId: string, value: string): boolean {
  const field = document.querySelector<HTMLElement>(`[data-job-agent-field="${CSS.escape(fieldId)}"]`);
  if (!field) return false;

  if (field instanceof HTMLSelectElement) {
    const match = [...field.options].find(
      (option) => option.textContent?.trim().toLowerCase() === value.trim().toLowerCase(),
    );
    if (!match) return false;
    field.value = match.value;
  } else if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
    // React and friends track the value on the DOM node, so setting .value
    // directly is ignored unless the native setter is used.
    const prototype =
      field instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (setter) setter.call(field, value);
    else field.value = value;
  } else {
    return false;
  }

  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
  field.focus();
  return true;
}
