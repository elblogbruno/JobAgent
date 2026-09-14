/** The patterns that decide whether an application really went out.
 *
 * A missed confirmation costs one click. A false one writes a wrong status and
 * credits a search with an application that never happened, so the false
 * positives matter far more than the misses.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { matchConfirmation } from "../src/content/submission-detector";

const CONFIRMATIONS = [
  "Se ha enviado tu solicitud a Stealth Startup. Puedes hacer un seguimiento en Mis empleos.",
  "Tu solicitud se ha enviado correctamente.",
  "Solicitud enviada",
  "Hemos recibido tu candidatura y la revisaremos pronto.",
  "Gracias por postular a esta posición.",
  "Your application was sent to Acme Corp.",
  "Your application has been submitted.",
  "Thank you for applying to Studio Beta!",
  "We have received your application.",
  "Application received",
  "S'ha enviat la teva sol·licitud.",
];

const NOT_CONFIRMATIONS = [
  "Solicita este empleo en el sitio web de la empresa.",
  "Revisa tu solicitud antes de enviarla.",
  "Review your application before you submit it.",
  "Todavía no has enviado tu solicitud.",
  "Rellena los campos obligatorios para enviar la solicitud.",
  "Apply now to join our team.",
  "Sign in to apply for this job.",
  "Guardar empleo",
  "Se buscan candidatos con experiencia en Unity.",
  "",
];

test("recognises a real confirmation", () => {
  for (const text of CONFIRMATIONS) {
    const found = matchConfirmation(text);
    assert.ok(found, `should have matched: ${text}`);
    assert.ok(found.matched.length > 0);
    assert.ok(found.excerpt.length > 0);
  }
});

test("does not fire on a page that is still asking you to apply", () => {
  for (const text of NOT_CONFIRMATIONS) {
    assert.equal(matchConfirmation(text), null, `should not have matched: ${text}`);
  }
});

test("a negation in the same sentence cancels the match", () => {
  assert.equal(matchConfirmation("Tu solicitud no se ha enviado. Inténtalo de nuevo."), null);
  assert.equal(matchConfirmation("Your application was not sent."), null);
});

test("the excerpt is the sentence, for the audit note", () => {
  const found = matchConfirmation(
    "Hola. Se ha enviado tu solicitud a Stealth Startup. Sigue el proceso en Mis empleos.",
  );
  assert.ok(found);
  assert.equal(found.excerpt, "Se ha enviado tu solicitud a Stealth Startup.");
});

test("the source is carried through", () => {
  const found = matchConfirmation("Solicitud enviada", "dom");
  assert.ok(found);
  assert.equal(found.source, "dom");
});
